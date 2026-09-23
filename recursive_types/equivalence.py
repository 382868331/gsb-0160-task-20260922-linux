"""equi-recursive 类型等价的成对协同检查（核心算法）。

语义
----
类型按其*无限展开树*相等定义（equi-recursive equivalence）：把每个节点沿出边
无限展开得到一棵可能无限的树，两类型等价当且仅当这两棵树逐路径同构——
节点种类一致；Product/Sum 同一字段名下的子树一致；Function 参数按有序位置
一一对应且返回一致。节点编号与共享程度都不是语义。

算法
----
对一对根 ``(a, b)`` 做带假设集的协同递归（coinductive pairwise check）：

* ``(x, y)`` 已在当前假设集中：按 coinductive 假设成功（再遇到即视为一致）；
* 否则先做*一层*结构匹配：种类不同、字段名集合不同、元数不同则立即分歧；
* 把 ``(x, y)`` 加入假设集后递归检查所有子对；任一子对分歧则整体分歧。

完全等价时，检查过程中加入假设集的全部节点对构成一个 bisimulation，
作为等价关系证书（:class:`EquivalenceCertificate`）返回。

不等价时返回 :class:`Divergence`，其中 ``path`` 是从根到第一处分歧点的
**最短**选择路径，``depth`` 为其长度：搜索用 BFS 按深度展开“对图”，
深度 0 为根对，首次发现的结构不匹配即为最浅分歧，路径上的每个选择都带
定位描述（字段名 / ``param k`` / ``result``）。

预算
----
``budget`` 限定检查中“展开新节点对”的次数；预算在结论前耗尽抛
:class:`BudgetExceededError`（结果未知），与已证伪的 :class:`Divergence`
严格分开。默认预算对 300+300 节点的输入充裕（对图最多 90000 对）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .errors import BudgetExceededError
from .model import (
    BOOL,
    FUNCTION,
    INT,
    PRODUCT,
    SUM,
    Field,
    FunctionNode,
    ProductNode,
    SumNode,
    TypeGraph,
    resolve_alias,
)

#: 默认成对展开预算（90000 为 300×300 对图的理论对数上界）。
DEFAULT_BUDGET = 90_000


@dataclass(frozen=True)
class Step:
    """分歧路径上的一步：从某个节点对走到其子对时所做的选择。"""

    selector: str
    detail: str

    def render(self) -> str:
        return f"{self.selector}({self.detail})" if self.detail else self.selector


@dataclass(frozen=True)
class Mismatch:
    """分歧点处的一层结构不匹配说明。"""

    reason: str
    left: str
    right: str

    def render(self) -> str:
        return f"{self.reason}: {self.left} != {self.right}"


@dataclass(frozen=True)
class EquivalenceCertificate:
    """两类型等价的证书：检查中建立的节点对关系。

    ``related_pairs`` 是一个 bisimulation 关系的节点对集合（``(g1 节点号,
    g2 节点号)``），覆盖根对且每对子节点仍落在关系内——逐条可复核。
    节点号只用于在证书里*指回*输入图，不参与语义判定。
    """

    root_pair: tuple[int, int]
    related_pairs: frozenset[tuple[int, int]]

    def __len__(self) -> int:
        return len(self.related_pairs)

    def render(self) -> str:
        pairs = sorted(self.related_pairs)
        body = ", ".join(f"({a},{b})" for a, b in pairs)
        return (
            f"EQUIVALENT: bisimulation with {len(self.related_pairs)} pair(s) "
            f"covering root {self.root_pair}: {body}"
        )


@dataclass(frozen=True)
class Divergence:
    """两类型不等价的证据：从根对到最浅分歧点的最短路径。"""

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
                f"NOT EQUIVALENT: shortest divergence at depth {self.depth} "
                f"via {trace}: {self.mismatch.render()}"
            )
        return (
            f"NOT EQUIVALENT: divergence at depth 0 (at root): "
            f"{self.mismatch.render()}"
        )


EquivalenceResult = EquivalenceCertificate | Divergence


# --------------------------------------------------------------------------- #
# 一层结构匹配
# --------------------------------------------------------------------------- #


def _kind_name(kind: str) -> str:
    return kind


def _structural_children(
    g1: TypeGraph, x: int, g2: TypeGraph, y: int
) -> tuple[list[tuple[int, int, Step]] | None, Mismatch | None]:
    """比较 ``(g1[x], g2[y])`` 的一层骨架。

    成功返回 ``(child_pairs, None)``，``child_pairs`` 为需要继续协同检查的
    ``(子节点1, 子节点2, 走到该子对的选择)`` 列表；
    失败返回 ``(None, mismatch)``。本函数不做递归。
    """
    n1 = g1[resolve_alias(g1, x)]
    n2 = g2[resolve_alias(g2, y)]
    k1, k2 = n1.kind, n2.kind
    if k1 != k2:
        return None, Mismatch(
            "node kind differs", _kind_name(k1), _kind_name(k2)
        )

    if k1 == INT or k1 == BOOL:
        return [], None

    if k1 in (PRODUCT, SUM):
        assert isinstance(n1, (ProductNode, SumNode))
        assert isinstance(n2, (ProductNode, SumNode))
        f1 = {f.name: f for f in n1.fields}
        f2 = {f.name: f for f in n2.fields}
        names1 = set(f1)
        names2 = set(f2)
        if names1 != names2:
            only1 = sorted(names1 - names2)
            only2 = sorted(names2 - names1)
            return None, Mismatch(
                f"{k1} field-name sets differ",
                f"extra/only-left={only1}",
                f"only-right={only2}",
            )
        children: list[tuple[int, int, Step]] = []
        for name in sorted(names1):  # 确定性顺序；不影响按名对应
            c1, c2 = f1[name], f2[name]
            if c1.readonly != c2.readonly:
                return None, Mismatch(
                    f"{k1} field {name!r} mutability differs",
                    f"readonly={c1.readonly}",
                    f"readonly={c2.readonly}",
                )
            children.append(
                (
                    c1.target,
                    c2.target,
                    Step("field", name),
                )
            )
        return children, None

    if k1 == FUNCTION:
        assert isinstance(n1, FunctionNode) and isinstance(n2, FunctionNode)
        p1, p2 = n1.params, n2.params
        if len(p1) != len(p2):
            return None, Mismatch(
                "Function parameter arity differs",
                f"{len(p1)} param(s)",
                f"{len(p2)} param(s)",
            )
        children = [
            (a, b, Step("param", str(j)))
            for j, (a, b) in enumerate(zip(p1, p2))
        ]
        children.append((n1.result, n2.result, Step("result", "")))
        return children, None

    raise AssertionError(f"unhandled kind {k1!r}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# 等价检查（成功路径：带假设集的 DFS，收集 bisimulation 证书）
# --------------------------------------------------------------------------- #


def _collect_bisimulation(
    g1: TypeGraph,
    root_a: int,
    g2: TypeGraph,
    root_b: int,
    budget: int,
) -> tuple[frozenset[tuple[int, int]] | None, Mismatch | None, int]:
    """带假设集的协同 DFS。

    返回 ``(related, None, used)`` 表示等价，``related`` 为 bisimulation；
    返回 ``(None, mismatch, used)`` 表示在 DFS 顺序下首先撞到的一层不匹配
    （仅用于预算耗尽前提前发现的明显分歧；最短路径由 BFS 负责）。
    ``used`` 为已展开的新对数。
    """
    assumed: set[tuple[int, int]] = set()
    related: set[tuple[int, int]] = set()
    used = 0

    # 迭代式 DFS，避免 300 节点量级下的 Python 递归深度问题。
    # 帧: (x, y, children, next_index)；进入帧前 pair 已放入 assumed。
    stack: list[tuple[int, int, list[tuple[int, int, Step]], int]] = []

    def start_pair(x: int, y: int) -> tuple[object, Mismatch | None, int]:
        """尝试建立新对；返回 ('push', children) / ('assumed', None) / ('fail', m)。"""
        nonlocal used
        pair = (x, y)
        if pair in assumed:
            return ("assumed", None, used)
        children, mismatch = _structural_children(g1, x, g2, y)
        if mismatch is not None:
            return ("fail", mismatch, used)
        used += 1
        if used > budget:
            return ("budget", None, used)
        assumed.add(pair)
        related.add(pair)
        return ("push", children, used)

    action, payload, used = start_pair(root_a, root_b)
    if action == "fail":
        return None, payload, used
    if action == "budget":
        return None, None, used
    assert action == "push"
    stack.append((root_a, root_b, payload, 0))  # type: ignore[arg-type]

    while stack:
        x, y, children, idx = stack[-1]
        if idx >= len(children):
            stack.pop()
            continue
        cx, cy, _step = children[idx]
        stack[-1] = (x, y, children, idx + 1)
        pair = (cx, cy)
        if pair in assumed:
            continue
        sub_children, mismatch = _structural_children(g1, cx, g2, cy)
        if mismatch is not None:
            return None, mismatch, used
        used += 1
        if used > budget:
            return None, None, used
        assumed.add(pair)
        related.add(pair)
        stack.append((cx, cy, sub_children, 0))

    return frozenset(related), None, used


# --------------------------------------------------------------------------- #
# 最短分歧（失败路径：对图上的 BFS）
# --------------------------------------------------------------------------- #


def _shortest_divergence(
    g1: TypeGraph,
    root_a: int,
    g2: TypeGraph,
    root_b: int,
    budget: int,
) -> tuple[Divergence | None, bool]:
    """在“对图”上 BFS，返回最浅分歧与完整路径。

    返回 ``(divergence, budget_hit)``；若预算先耗尽 ``divergence`` 为 None
    且 ``budget_hit`` 为 True。
    """
    used = 0
    root_pair = (root_a, root_b)
    seen: dict[tuple[int, int], tuple[int, int] | None] = {root_pair: None}
    step_to: dict[tuple[int, int], Step] = {}
    queue: deque[tuple[int, int]] = deque([root_pair])

    while queue:
        x, y = queue.popleft()
        children, mismatch = _structural_children(g1, x, g2, y)
        if mismatch is not None:
            # 回溯生成路径
            path: list[Step] = []
            cur: tuple[int, int] | None = (x, y)
            chain: list[tuple[int, int]] = []
            while cur is not None:
                chain.append(cur)
                cur = seen[cur]
            chain.reverse()
            for child_pair in chain[1:]:
                path.append(step_to[child_pair])
            return Divergence(root_pair, tuple(path), mismatch), False
        used += 1
        if used > budget:
            return None, True
        assert children is not None
        for cx, cy, step in children:
            pair = (cx, cy)
            if pair in seen:
                continue
            seen[pair] = (x, y)
            step_to[pair] = step
            queue.append(pair)

    # BFS 排空仍无分歧 => 实际等价（正常流程不会走到这里；先由 DFS 判定）。
    return None, False


def check_equivalence(
    g1: TypeGraph,
    g2: TypeGraph,
    *,
    root1: int | None = None,
    root2: int | None = None,
    budget: int = DEFAULT_BUDGET,
) -> EquivalenceResult:
    """检查两张类型图根类型的 equi-recursive 等价性。

    :param g1, g2: 经 :class:`TypeGraph` 校验的类型图。
    :param root1, root2: 可选的根节点覆盖；缺省用各图的 ``root``。
        给定值必须是严格 int（非 bool）且在对应图范围内。
    :param budget: 成对展开次数上限（严格正整数，非 bool）。
    :returns: 等价返回 :class:`EquivalenceCertificate`，
        不等价返回 :class:`Divergence`（含最短分歧路径）。
    :raises TypeError/ValueError: 参数种类或取值非法（在任何检查前拒绝）。
    :raises BudgetExceededError: 预算在结论前耗尽——结果未知，
        与“已证明不等价”严格区分。
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

    related, mismatch, used = _collect_bisimulation(g1, a, g2, b, budget)
    if related is not None:
        return EquivalenceCertificate((a, b), related)

    if mismatch is not None:
        # DFS 已发现一处不匹配，但契约要求最短路径，交给 BFS 精确定位。
        divergence, budget_hit = _shortest_divergence(g1, a, g2, b, budget)
        if budget_hit:
            raise BudgetExceededError(budget, used)
        assert divergence is not None
        return divergence

    # DFS 预算耗尽：可能等价也可能深处不等价，必须与“证伪”分开。
    raise BudgetExceededError(budget, used)


def _check_root(root: object, g: TypeGraph, name: str) -> int:
    if type(root) is not int:
        kind = "bool" if isinstance(root, bool) else type(root).__name__
        raise TypeError(f"{name} must be a strict int (got {kind})")
    if not 0 <= root < len(g):
        raise ValueError(
            f"{name}={root} out of range for graph with {len(g)} node(s)"
        )
    return root  # type: ignore[return-value]


def verify_certificate(
    g1: TypeGraph, g2: TypeGraph, certificate: EquivalenceCertificate
) -> bool:
    """独立复核证书：``related_pairs`` 是否确为覆盖根对的 bisimulation。

    逐条检查：根对在关系中；关系中每对的一层骨架匹配；且其全部子对仍在
    关系中。任何一条不满足返回 ``False``。
    """
    if not isinstance(g1, TypeGraph) or not isinstance(g2, TypeGraph):
        raise TypeError("g1 and g2 must be TypeGraph instances")
    if not isinstance(certificate, EquivalenceCertificate):
        raise TypeError("certificate must be an EquivalenceCertificate")
    relation = set(certificate.related_pairs)
    root_a, root_b = certificate.root_pair
    if (root_a, root_b) not in relation:
        return False
    for x, y in relation:
        if not (0 <= x < len(g1)) or not (0 <= y < len(g2)):
            return False
        children, mismatch = _structural_children(g1, x, g2, y)
        if mismatch is not None or children is None:
            return False
        for cx, cy, _step in children:
            if (cx, cy) not in relation:
                return False
    return True


def are_equivalent(g1: TypeGraph, g2: TypeGraph, **kwargs: object) -> bool:
    """:func:`check_equivalence` 的布尔便捷封装；预算耗尽仍会抛异常。"""
    result = check_equivalence(g1, g2, **kwargs)
    return isinstance(result, EquivalenceCertificate)
