"""递归类型的结构子类型判断（structural subtyping）。

规则（对无穷展开树成立，equi-recursive）
----------------------------------------

* ``Int``/``Bool``：同种类才可互为子类型。
* **记录（Product）宽度子类型**：超类型的每个字段都必须在子类型中出现，
  子类型可以多出字段。深度规则按*超类型*字段的可变性决定：

  - 超类型字段**只读**：字段类型协变（``T1 <: T2``），子类型该字段只读或
    可写均可（可写槽用于只读位置安全）；
  - 超类型字段**可写**：子类型该字段也必须可写，且字段类型**不变**
    （``T1 ≡ T2``）——只读字段不能满足写入要求，协变/逆变都不能保证读写双向安全。

* **Sum**：题面只给记录开宽度子类型，故标签集合必须精确一致；负载只读，
  逐标签协变。
* **Function**：参数个数相同；参数**逆变**（``P2 <: P1``），
  返回值**协变**（``R1 <: R2``）。
* **Alias**：透明别名，比较前直接穿透（构图期已保证不存在只经过 Alias 的环，
  即无保护递归 μX.X）。

算法
----

与等价检查同为带假设集的成对协同检查，但每条义务带关系标记：

* ``sub``：左 <: 右；``sup``：右 <: 左（由函数参数逆变产生）；
* ``eq``：左右不变（由可写字段产生），按等价规则逐层封闭。

完全成立时，检查中建立的全部 ``(关系, 左节点, 右节点)`` 条目构成一个
模拟关系证书（:class:`SubtypeCertificate`），可独立逐条复核。
不成立时返回 :class:`SubtypeFailure`，``path`` 是从根对到第一处违反点的
可定位类型路径（字段名 / ``param k`` / ``result``）。本迭代不要求最短路径证明，
故失败定位用 DFS 顺序的首条路径即可。

预算语义与 :mod:`recursive_types.equivalence` 一致：``budget`` 限定展开新
“关系-节点对”的次数，结论前耗尽抛 :class:`BudgetExceededError`（未知），
绝不报告成失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import BudgetExceededError
from .equivalence import Mismatch, Step, _check_root
from .model import (
    FUNCTION,
    INT,
    BOOL,
    PRODUCT,
    SUM,
    FunctionNode,
    ProductNode,
    SumNode,
    TypeGraph,
    resolve_alias,
)

#: 默认关系-节点对展开预算。
#: 义务有 sub/sup/eq 三种关系标记，300×300 对图、每对在三种关系下各至多
#: 出现一次，故 3*300*300=270000 覆盖接口上限内的最坏情况。
DEFAULT_SUBTYPE_BUDGET = 270_000

# 关系标记。
SUB = "sub"  # g1[a] <: g2[b]
SUP = "sup"  # g2[b] <: g1[a]（逆变参数位置产生）
EQ = "eq"    # g1[a] ≡ g2[b]（可写字段的不变要求）

_RELATIONS = (SUB, SUP, EQ)


@dataclass(frozen=True)
class SubtypeCertificate:
    """``g1[root1] <: g2[root2]`` 成立的证书：检查中建立的模拟关系。

    ``entries`` 为 ``(relation, node1, node2)`` 三元组的 frozenset：

    * ``("sub", a, b)`` 表示 ``g1[a] <: g2[b]``；
    * ``("sup", a, b)`` 表示 ``g2[b] <: g1[a]``（逆变参数位置）；
    * ``("eq", a, b)`` 表示 ``g1[a] ≡ g2[b]``（可写字段的不变要求）。

    关系覆盖根义务 ``("sub", root1, root2)``，且每条义务的直接子义务仍在
    关系内——可由 :func:`verify_subtype_certificate` 独立逐条复核。
    """

    root_pair: tuple[int, int]
    entries: frozenset[tuple[str, int, int]]

    def __len__(self) -> int:
        return len(self.entries)

    def render(self) -> str:
        body = ", ".join(f"{r}({a},{b})" for r, a, b in sorted(self.entries))
        return (
            f"SUBTYPE: simulation relation with {len(self.entries)} entr(ies) "
            f"covering root {self.root_pair}: {body}"
        )


@dataclass(frozen=True)
class SubtypeFailure:
    """子类型不成立的证据：从根对到第一处违反点的类型路径。"""

    root_pair: tuple[int, int]
    path: tuple[Step, ...]
    mismatch: Mismatch
    depth: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "depth", len(self.path))

    def render(self) -> str:
        if self.path:
            trace = " -> ".join(s.render() for s in self.path)
            return (
                f"NOT SUBTYPE: rule violation at depth {self.depth} "
                f"via {trace}: {self.mismatch.render()}"
            )
        return (
            f"NOT SUBTYPE: rule violation at depth 0 (at root): "
            f"{self.mismatch.render()}"
        )


SubtypeResult = SubtypeCertificate | SubtypeFailure


# --------------------------------------------------------------------------- #
# 一层规则：给定义务，生成直接子义务，或给出结构层面的违反说明
# --------------------------------------------------------------------------- #


def _fields_by_name(node: ProductNode | SumNode) -> dict[str, object]:
    return {f.name: f for f in node.fields}


def _orient(
    relation: str,
    node_sub_side: int,
    node_super_side: int,
    step: Step,
    *,
    flip: bool = False,
) -> tuple[str, int, int, Step]:
    """把“子侧/超侧”节点编号按当前义务视角摆回 (g1 侧, g2 侧)。

    ``relation`` 为 SUB 时子侧就是 g1；SUP 时子侧是 g2。
    ``flip`` 用于函数逆变参数位置：仅把子义务方向标记取反（SUB↔SUP），
    编号仍按各自所在的图归位。
    """
    child_rel = SUP if (flip and relation == SUB) else (
        SUB if (flip and relation == SUP) else relation
    )
    if relation == SUB:
        return (child_rel, node_sub_side, node_super_side, step)
    return (child_rel, node_super_side, node_sub_side, step)


def _obligation_children(
    g1: TypeGraph,
    a: int,
    g2: TypeGraph,
    b: int,
    relation: str,
) -> tuple[list[tuple[str, int, int, Step]] | None, Mismatch | None]:
    """一层规则展开。

    返回 ``(子义务, None)``：每项为 ``(子关系, g1 侧子节点, g2 侧子节点, 选择步)``；
    失败返回 ``(None, mismatch)``。Alias 在本层穿透。
    """
    n1 = g1[resolve_alias(g1, a)]
    n2 = g2[resolve_alias(g2, b)]

    # ------------------------------ 不变义务 ------------------------------- #
    if relation == EQ:
        k1, k2 = n1.kind, n2.kind
        if k1 != k2:
            return None, Mismatch("node kind differs (invariant position)", k1, k2)
        if k1 in (INT, BOOL):
            return [], None
        if k1 in (PRODUCT, SUM):
            assert isinstance(n1, (ProductNode, SumNode))
            assert isinstance(n2, (ProductNode, SumNode))
            f1, f2 = _fields_by_name(n1), _fields_by_name(n2)
            if set(f1) != set(f2):
                return None, Mismatch(
                    f"{k1} field-name sets differ (invariant position)",
                    f"only-left={sorted(set(f1) - set(f2))}",
                    f"only-right={sorted(set(f2) - set(f1))}",
                )
            kids: list[tuple[str, int, int, Step]] = []
            for name in sorted(f1):
                c1, c2 = f1[name], f2[name]
                if c1.readonly != c2.readonly:  # type: ignore[union-attr]
                    return None, Mismatch(
                        f"{k1} field {name!r} mutability differs "
                        "(invariant position)",
                        f"readonly={c1.readonly}",  # type: ignore[union-attr]
                        f"readonly={c2.readonly}",  # type: ignore[union-attr]
                    )
                kids.append(
                    (
                        EQ,
                        c1.target,  # type: ignore[union-attr]
                        c2.target,  # type: ignore[union-attr]
                        Step("field", name),
                    )
                )
            return kids, None
        if k1 == FUNCTION:
            assert isinstance(n1, FunctionNode) and isinstance(n2, FunctionNode)
            if len(n1.params) != len(n2.params):
                return None, Mismatch(
                    "Function parameter arity differs (invariant position)",
                    f"{len(n1.params)} param(s)",
                    f"{len(n2.params)} param(s)",
                )
            kids = [
                (EQ, p1, p2, Step("param", str(j)))
                for j, (p1, p2) in enumerate(zip(n1.params, n2.params))
            ]
            kids.append((EQ, n1.result, n2.result, Step("result", "")))
            return kids, None
        raise AssertionError(f"unhandled kind {k1!r}")  # pragma: no cover

    # ------------------------- 子类型义务（统一视角） ---------------------- #
    # SUB：子侧节点是 g1 的 n1；SUP：子侧节点是 g2 的 n2。
    ks, kt = (n1, n2) if relation == SUB else (n2, n1)
    sk, tk = ks.kind, kt.kind
    if sk != tk:
        return None, Mismatch(
            "node kind differs in subtype rule",
            f"sub={sk}",
            f"super={tk}",
        )
    if sk in (INT, BOOL):
        return [], None

    if sk == PRODUCT:
        assert isinstance(ks, ProductNode) and isinstance(kt, ProductNode)
        fs, ft = _fields_by_name(ks), _fields_by_name(kt)
        missing = sorted(set(ft) - set(fs))
        if missing:
            return None, Mismatch(
                "Product width rule violated: supertype field(s) absent "
                "from subtype",
                f"subtype fields={sorted(fs)}",
                f"missing={missing}",
            )
        kids = []
        for name in sorted(ft):
            cs, ct = fs[name], ft[name]
            step = Step("field", name)
            if ct.readonly:  # type: ignore[union-attr]
                # 超类型只读 => 字段位置协变。
                kids.append(
                    _orient(
                        relation,
                        cs.target,  # type: ignore[union-attr]
                        ct.target,  # type: ignore[union-attr]
                        step,
                    )
                )
            else:
                # 超类型可写 => 子侧必须可写，且类型不变。
                if cs.readonly:  # type: ignore[union-attr]
                    return None, Mismatch(
                        f"Product field {name!r} is writable in the supertype "
                        "but read-only in the subtype (a read-only field "
                        "cannot satisfy writes)",
                        f"sub readonly={cs.readonly}",  # type: ignore[union-attr]
                        f"super readonly={ct.readonly}",  # type: ignore[union-attr]
                    )
                if relation == SUB:
                    kids.append(
                        (
                            EQ,
                            cs.target,  # type: ignore[union-attr]
                            ct.target,  # type: ignore[union-attr]
                            step,
                        )
                    )
                else:
                    kids.append(
                        (
                            EQ,
                            ct.target,  # type: ignore[union-attr]
                            cs.target,  # type: ignore[union-attr]
                            step,
                        )
                    )
        return kids, None

    if sk == SUM:
        assert isinstance(ks, SumNode) and isinstance(kt, SumNode)
        fs, ft = _fields_by_name(ks), _fields_by_name(kt)
        if set(fs) != set(ft):
            return None, Mismatch(
                "Sum label sets must match exactly (no width rule for sums)",
                f"only-subtype={sorted(set(fs) - set(ft))}",
                f"only-supertype={sorted(set(ft) - set(fs))}",
            )
        kids = []
        for name in sorted(ft):  # 负载只读 => 协变
            cs, ct = fs[name], ft[name]
            kids.append(
                _orient(
                    relation,
                    cs.target,  # type: ignore[union-attr]
                    ct.target,  # type: ignore[union-attr]
                    Step("field", name),
                )
            )
        return kids, None

    if sk == FUNCTION:
        assert isinstance(ks, FunctionNode) and isinstance(kt, FunctionNode)
        ps, pt = ks.params, kt.params
        if len(ps) != len(pt):
            return None, Mismatch(
                "Function parameter arity differs in subtype rule",
                f"sub {len(ps)} param(s)",
                f"super {len(pt)} param(s)",
            )
        kids = []
        for j, (p_sub, p_sup) in enumerate(zip(ps, pt)):
            # 参数逆变：要求“超侧参数 <: 子侧参数”。
            kids.append(
                _orient(relation, p_sub, p_sup, Step("param", str(j)), flip=True)
            )
        # 返回协变。
        kids.append(_orient(relation, ks.result, kt.result, Step("result", "")))
        return kids, None

    raise AssertionError(f"unhandled kind {sk!r}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# 协同检查（迭代式 DFS，带假设集；失败给可定位路径）
# --------------------------------------------------------------------------- #


def _check(
    g1: TypeGraph,
    root1: int,
    g2: TypeGraph,
    root2: int,
    budget: int,
) -> SubtypeResult:
    assumed: set[tuple[str, int, int]] = set()
    related: set[tuple[str, int, int]] = set()

    root_key = (SUB, root1, root2)
    root_kids, mismatch = _obligation_children(g1, root1, g2, root2, SUB)
    if mismatch is not None:
        return SubtypeFailure((root1, root2), (), mismatch)
    used = 1
    if used > budget:
        raise BudgetExceededError(budget, used)
    assumed.add(root_key)
    related.add(root_key)

    # 帧: (rel, a, b, kids, next_index)；path 与栈同步，记录进入每帧时走过的步。
    stack: list[tuple[str, int, int, list[tuple[str, int, int, Step]], int]] = [
        (SUB, root1, root2, root_kids, 0)
    ]
    path: list[Step] = []

    while stack:
        rel, a, b, kids, idx = stack[-1]
        if idx >= len(kids):
            stack.pop()
            if path:
                path.pop()
            continue
        crel, ca, cb, step = kids[idx]
        stack[-1] = (rel, a, b, kids, idx + 1)
        key = (crel, ca, cb)
        if key in assumed:
            continue
        sub_kids, sub_mismatch = _obligation_children(g1, ca, g2, cb, crel)
        if sub_mismatch is not None:
            return SubtypeFailure((root1, root2), tuple(path + [step]), sub_mismatch)
        used += 1
        if used > budget:
            raise BudgetExceededError(budget, used)
        assumed.add(key)
        related.add(key)
        path.append(step)
        stack.append((crel, ca, cb, sub_kids, 0))

    return SubtypeCertificate((root1, root2), frozenset(related))


def check_subtype(
    g1: TypeGraph,
    g2: TypeGraph,
    *,
    root1: int | None = None,
    root2: int | None = None,
    budget: int = DEFAULT_SUBTYPE_BUDGET,
) -> SubtypeResult:
    """检查 ``g1[root1] <: g2[root2]``（g1 是子类型方）。

    :param g1, g2: 经 :class:`TypeGraph` 校验的类型图（无保护递归已在构图期拒绝）。
    :param root1, root2: 可选的根节点覆盖；缺省用各图的 ``root``。
        给定值必须是严格 int（非 bool）且在对应图范围内。
    :param budget: 关系-节点对展开次数上限（严格正整数，非 bool）。
    :returns: 成立返回 :class:`SubtypeCertificate`，
        不成立返回 :class:`SubtypeFailure`（含可定位类型路径）。
    :raises TypeError/ValueError: 参数种类或取值非法（在任何检查前拒绝）。
    :raises BudgetExceededError: 预算在结论前耗尽——结果未知。
    """
    if not isinstance(g1, TypeGraph) or not isinstance(g2, TypeGraph):
        raise TypeError(
            "g1 and g2 must be TypeGraph instances "
            f"(got {type(g1).__name__}, {type(g2).__name__})"
        )
    if type(budget) is not int:
        kind = "bool" if isinstance(budget, bool) else type(budget).__name__
        raise TypeError(f"budget must be a strict int (got {kind})")
    if budget <= 0:
        raise ValueError(f"budget must be a positive int (got {budget})")

    a = g1.root if root1 is None else _check_root(root1, g1, "root1")
    b = g2.root if root2 is None else _check_root(root2, g2, "root2")
    return _check(g1, a, g2, b, budget)


def is_subtype(g1: TypeGraph, g2: TypeGraph, **kwargs: object) -> bool:
    """:func:`check_subtype` 的布尔便捷封装；预算耗尽仍会抛异常。"""
    result = check_subtype(g1, g2, **kwargs)
    return isinstance(result, SubtypeCertificate)


def verify_subtype_certificate(
    g1: TypeGraph, g2: TypeGraph, certificate: SubtypeCertificate
) -> bool:
    """独立复核子类型证书：条目集合是否为覆盖根义务的封闭模拟关系。

    逐条检查：根义务 ``("sub", root1, root2)`` 在关系中；每个条目节点编号
    合法、关系标记合法；其一层规则展开出的全部子义务仍在关系中。
    任何一条不满足返回 ``False``。
    """
    if not isinstance(g1, TypeGraph) or not isinstance(g2, TypeGraph):
        raise TypeError("g1 and g2 must be TypeGraph instances")
    if not isinstance(certificate, SubtypeCertificate):
        raise TypeError("certificate must be a SubtypeCertificate")
    relation = set(certificate.entries)
    root1, root2 = certificate.root_pair
    if (SUB, root1, root2) not in relation:
        return False
    for rel, a, b in relation:
        if rel not in _RELATIONS:
            return False
        if not (0 <= a < len(g1)) or not (0 <= b < len(g2)):
            return False
        kids, mismatch = _obligation_children(g1, a, g2, b, rel)
        if mismatch is not None or kids is None:
            return False
        for crel, ca, cb, _step in kids:
            if (crel, ca, cb) not in relation:
                return False
    return True
