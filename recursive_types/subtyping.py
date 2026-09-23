"""显式节点递归类型的结构子类型（structural subtyping）检查。

与 :mod:`recursive_types.equivalence` 并列的第二个公开判定入口，复用同一套
数据结构（:class:`~recursive_types.model.TypeGraph`），并同样按无限展开树的
equi-recursive 观点处理递归。

子类型规则（逐层）
------------------
1. ``Int <: Int``、``Bool <: Bool``；不同构造子之间无子类型关系。
2. **Product（只读记录）字段协变 + 宽度子类型**：
   超类型要求的每个字段都必须在子类型记录中出现，且对应字段类型协变；
   子类型可以**多出**字段（宽记录可用于要求窄记录之处）。
3. **Sum（变体）反向宽度 + 成分协变**：
   子类型提供的每个变体超类型都必须接受，成分类型协变；超类型可多分分支。
4. **Function 参数逆变、返回值协变、元数不变**：
   元数相同；第 j 个参数方向反转，返回方向保持。

本库 Product 字段只有“只读”一种极性，故字段一律协变；没有可写字段不变的
单独构造（见 README“设计取舍”）。

极性状态与递归
--------------
参数逆变会在证明中翻转“谁是子类型一侧”。遍历状态统一表示为
``(a, b, reversed)``：``a`` 永远是 ``g_sub`` 的结构节点号、``b`` 永远是
``g_super`` 的结构节点号；``reversed=False`` 表示义务 ``g_sub[a] <: g_sup[b]``，
``True`` 表示反向义务 ``g_sup[b] <: g_sub[a]``。协变边（字段/返回）保持极性，
逆变边（参数）翻转极性。协递归假设按 ``(a, b, reversed)`` 去重——再遇同一
*带极性*义务即成功，因此受保护的递归环（宽度递归、沿参数位翻转后回到同一
义务的环等）都可证；而 ``μX. X -> T`` 这类在两次逆变后产生矛盾的类型会沿
最浅路径被驳回。无保护递归（``μX. X``）已在 :class:`TypeGraph` 构造期拒绝；
``Alias`` 节点透明，不计结构层。

返回与预算
----------
成立返回 :class:`SubtypingCertificate`（带极性的模拟关系，可独立逐条复核）；
不成立返回 :class:`SubtypeFailure`，``path`` 是从根到**最浅**违反点的类型
路径（字段名 / 参数位置 / result）。``budget`` 语义与等价检查一致：
结论前耗尽抛 :class:`BudgetExceededError`（未知），绝不报告成已证伪。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .errors import BudgetExceededError
from .equivalence import Mismatch, Step, _check_root
from .model import (
    BOOL,
    FUNCTION,
    INT,
    PRODUCT,
    SUM,
    FunctionNode,
    ProductNode,
    SumNode,
    TypeGraph,
)

#: 默认成对展开预算。带极性义务状态最多 2×300×300 = 180000 个，
#: 故取该理论上界，保证接口边界内的合法输入不会因默认预算中断。
DEFAULT_SUBTYPE_BUDGET = 180_000

# 带极性的义务状态：(g_sub 结构节点号, g_sup 结构节点号, reversed)。
# False: g_sub[a] <: g_sup[b]；True: g_sup[b] <: g_sub[a]。
State = tuple[int, int, bool]


@dataclass(frozen=True)
class SubtypingCertificate:
    """``g_sub`` 根类型是 ``g_super`` 根类型子类型的证书。

    ``related_pairs`` 的每项为带极性的义务 ``(a, b, reversed)``：
    ``reversed=False`` 表示已证 ``g_sub[a] <: g_super[b]``，
    ``True`` 表示已证反向义务 ``g_super[b] <: g_sub[a]``（产生于逆变位置）。
    它们构成一个对一层子类型规则封闭的关系：根义务
    ``(root_pair[0], root_pair[1], False)`` 在其中，每项的全部子义务
    （协变/逆变方向已算好）仍在关系中，可用
    :func:`verify_subtype_certificate` 独立逐条复核。节点号均为解析 Alias
    后的结构节点，只用于指回输入图。
    """

    root_pair: tuple[int, int]
    related_pairs: frozenset[tuple[int, int, bool]]

    def __len__(self) -> int:
        return len(self.related_pairs)

    def render(self) -> str:
        def show(item: tuple[int, int, bool]) -> str:
            # 节点号来自不同的图，标注 g1=g_sub / g2=g_super 以免歧义；
            # rev=True 的义务方向为 g2#b <: g1#a（逆变位置产生）。
            a, b, rev = item
            return f"(g2#{b} <: g1#{a})" if rev else f"(g1#{a} <: g2#{b})"

        body = ", ".join(show(item) for item in sorted(self.related_pairs))
        return (
            f"SUBTYPE: simulation with {len(self.related_pairs)} obligation(s) "
            f"covering root (g1#{self.root_pair[0]} <: g2#{self.root_pair[1]}): "
            f"{body}"
        )


@dataclass(frozen=True)
class SubtypeFailure:
    """子类型不成立的证据：从根对到最浅违反点的最短类型路径。"""

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
                f"NOT SUBTYPE: shortest violation at depth {self.depth} "
                f"via {trace}: {self.mismatch.render()}"
            )
        return (
            "NOT SUBTYPE: violation at depth 0 (at root): "
            f"{self.mismatch.render()}"
        )


SubtypingResult = SubtypingCertificate | SubtypeFailure


def _state_obligations(
    g_sub: TypeGraph,
    g_sup: TypeGraph,
    state: State,
) -> tuple[list[tuple[State, Step]] | None, Mismatch | None]:
    """计算一个带极性义务的一层子义务。

    成功返回 ``(子状态列表, None)``；失败返回 ``(None, mismatch)``。不递归。
    Alias 透明：状态携带的节点号在进入时已解析到结构层。
    """
    a, b, rev = state
    # 当前义务的“子类型一侧 L <: 超类型一侧 R”。
    if not rev:
        g_left, i_left = g_sub, a
        g_right, i_right = g_sup, b
    else:
        g_left, i_left = g_sup, b
        g_right, i_right = g_sub, a
    n_left = g_left[i_left]
    n_right = g_right[i_right]
    k_left, k_right = n_left.kind, n_right.kind
    if k_left != k_right:
        return None, Mismatch("node kind differs", k_left, k_right)

    if k_left in (INT, BOOL):
        return [], None

    def to_state(li: int, ri: int, flip: bool) -> State:
        """把 (左图子节点, 右图子节点) 映射回 (a, b, reversed)。

        协变边 flip=False 保持极性；逆变边 flip=True 翻转极性。
        """
        if not rev:
            ac, bc = li, ri
        else:
            ac, bc = ri, li
        return (ac, bc, rev != flip)

    if k_left == PRODUCT:
        assert isinstance(n_left, ProductNode)
        assert isinstance(n_right, ProductNode)
        f_left = {f.name: f.target for f in n_left.fields}
        f_right = {f.name: f.target for f in n_right.fields}
        missing = sorted(set(f_right) - set(f_left))
        if missing:
            return None, Mismatch(
                "Product width: subtype-side record is missing required "
                "field(s)",
                f"missing={missing}",
                f"required={sorted(f_right)}",
            )
        out: list[tuple[State, Step]] = []
        for name in sorted(f_right):  # 只需检查超类型一侧要求的字段
            li = g_left.resolve_alias(f_left[name])
            ri = g_right.resolve_alias(f_right[name])
            out.append((to_state(li, ri, False), Step("field", name)))
        return out, None

    if k_left == SUM:
        assert isinstance(n_left, SumNode)
        assert isinstance(n_right, SumNode)
        f_left = {f.name: f.target for f in n_left.fields}
        f_right = {f.name: f.target for f in n_right.fields}
        extra = sorted(set(f_left) - set(f_right))
        if extra:
            return None, Mismatch(
                "Sum width: subtype side offers variant(s) the supertype "
                "does not accept",
                f"extra={extra}",
                f"accepted={sorted(f_right)}",
            )
        out = []
        for name in sorted(f_left):  # 只需检查子类型一侧实际提供的分支
            li = g_left.resolve_alias(f_left[name])
            ri = g_right.resolve_alias(f_right[name])
            out.append((to_state(li, ri, False), Step("field", name)))
        return out, None

    if k_left == FUNCTION:
        assert isinstance(n_left, FunctionNode)
        assert isinstance(n_right, FunctionNode)
        pl, pr = n_left.params, n_right.params
        if len(pl) != len(pr):
            return None, Mismatch(
                "Function parameter arity differs",
                f"{len(pl)} param(s)",
                f"{len(pr)} param(s)",
            )
        out = []
        for j, (pa, pb) in enumerate(zip(pl, pr)):
            li = g_left.resolve_alias(pa)
            ri = g_right.resolve_alias(pb)
            out.append((to_state(li, ri, True), Step("param", str(j))))
        li = g_left.resolve_alias(n_left.result)
        ri = g_right.resolve_alias(n_right.result)
        out.append((to_state(li, ri, False), Step("result", "")))
        return out, None

    raise AssertionError(f"unhandled kind {k_left!r}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# 成功路径：协递归 DFS 收集带极性的模拟关系
# --------------------------------------------------------------------------- #


def _collect_simulation(
    g_sub: TypeGraph,
    g_sup: TypeGraph,
    start: State,
    budget: int,
) -> tuple[frozenset[State] | None, Mismatch | None, int]:
    """带假设集的协递归 DFS（迭代式），按带极性义务去重。

    返回 ``(related, None, used)`` 表示子类型成立；``(None, mismatch, used)``
    表示 DFS 顺序下先撞到的一层违反（最短路径另由 BFS 定位）。
    """
    assumed: set[State] = set()
    related: set[State] = set()
    used = 0

    children, mismatch = _state_obligations(g_sub, g_sup, start)
    if mismatch is not None:
        return None, mismatch, used
    used += 1
    if used > budget:
        return None, None, used
    assumed.add(start)
    related.add(start)
    stack: list[tuple[State, list[tuple[State, Step]], int]] = [
        (start, children, 0)
    ]

    while stack:
        state, kids, idx = stack[-1]
        if idx >= len(kids):
            stack.pop()
            continue
        child, _step = kids[idx]
        stack[-1] = (state, kids, idx + 1)
        if child in assumed:
            continue
        sub_kids, mismatch = _state_obligations(g_sub, g_sup, child)
        if mismatch is not None:
            return None, mismatch, used
        used += 1
        if used > budget:
            return None, None, used
        assumed.add(child)
        related.add(child)
        stack.append((child, sub_kids, 0))

    return frozenset(related), None, used


# --------------------------------------------------------------------------- #
# 失败路径：带极性对图 BFS 定位最浅违反
# --------------------------------------------------------------------------- #


def _shortest_violation(
    g_sub: TypeGraph,
    g_sup: TypeGraph,
    start: State,
    budget: int,
) -> tuple[SubtypeFailure | None, bool]:
    """在带极性的“子类型对图”上 BFS，返回最浅违反与完整类型路径。

    返回 ``(failure, budget_hit)``；预算先耗尽时 ``failure`` 为 None。
    """
    used = 0
    seen: dict[State, State | None] = {start: None}
    step_to: dict[State, Step] = {}
    queue: deque[State] = deque([start])

    while queue:
        state = queue.popleft()
        kids, mismatch = _state_obligations(g_sub, g_sup, state)
        if mismatch is not None:
            chain: list[State] = []
            cur: State | None = state
            while cur is not None:
                chain.append(cur)
                cur = seen[cur]
            chain.reverse()
            path = tuple(step_to[s] for s in chain[1:])
            return SubtypeFailure((start[0], start[1]), path, mismatch), False
        used += 1
        if used > budget:
            return None, True
        assert kids is not None
        for child, step in kids:
            if child in seen:
                continue
            seen[child] = state
            step_to[child] = step
            queue.append(child)

    return None, False  # pragma: no cover - 排空意味着成立，正常流程先由 DFS 判定


def check_subtype(
    g_sub: TypeGraph,
    g_super: TypeGraph,
    *,
    root_sub: int | None = None,
    root_super: int | None = None,
    budget: int = DEFAULT_SUBTYPE_BUDGET,
) -> SubtypingResult:
    """检查 ``g_sub`` 的根类型是否为 ``g_super`` 根类型的结构子类型。

    :param g_sub: 子类型候选（更“具体”的一侧）。
    :param g_super: 超类型候选（更“宽泛”的一侧）。
    :param root_sub, root_super: 可选的根节点覆盖；缺省用各图 ``root``。
        给定值必须是严格 int（非 bool）且在对应图范围内。
    :param budget: 成对展开次数上限（严格正整数，非 bool）。
    :returns: 成立返回 :class:`SubtypingCertificate`，
        不成立返回 :class:`SubtypeFailure`（含最浅违反路径）。
    :raises TypeError/ValueError: 参数种类或取值非法（在任何检查前拒绝）。
    :raises BudgetExceededError: 预算在结论前耗尽——结果未知，
        与“已证明不成立”严格区分。
    """
    if not isinstance(g_sub, TypeGraph) or not isinstance(g_super, TypeGraph):
        raise TypeError(
            "g_sub and g_super must be TypeGraph instances "
            f"(got {type(g_sub).__name__}, {type(g_super).__name__})"
        )
    if type(budget) is not int:
        kind = "bool" if isinstance(budget, bool) else type(budget).__name__
        raise TypeError(f"budget must be a strict int (got {kind})")
    if budget <= 0:
        raise ValueError(f"budget must be a positive int (got {budget})")

    ra = g_sub.root if root_sub is None else _check_root(root_sub, g_sub, "root_sub")
    rb = (
        g_super.root
        if root_super is None
        else _check_root(root_super, g_super, "root_super")
    )
    a = g_sub.resolve_alias(ra)
    b = g_super.resolve_alias(rb)
    start: State = (a, b, False)

    related, mismatch, used = _collect_simulation(g_sub, g_super, start, budget)
    if related is not None:
        return SubtypingCertificate((a, b), related)

    if mismatch is not None:
        failure, budget_hit = _shortest_violation(g_sub, g_super, start, budget)
        if budget_hit:
            raise BudgetExceededError(budget, used)
        assert failure is not None
        return failure

    raise BudgetExceededError(budget, used)


def is_subtype(g_sub: TypeGraph, g_super: TypeGraph, **kwargs: object) -> bool:
    """:func:`check_subtype` 的布尔便捷封装；预算耗尽仍会抛异常。"""
    result = check_subtype(g_sub, g_super, **kwargs)
    return isinstance(result, SubtypingCertificate)


def verify_subtype_certificate(
    g_sub: TypeGraph,
    g_super: TypeGraph,
    certificate: SubtypingCertificate,
) -> bool:
    """独立复核证书：``related_pairs`` 是否确为覆盖根义务的封闭模拟关系。

    逐条检查：根义务 ``(root_sub, root_super, False)`` 在关系中；节点号在图内；
    每条带极性义务的一层子类型规则成立；其全部子义务（含参数逆变翻转后的
    极性）仍在关系中。任一不满足返回 ``False``。
    """
    if not isinstance(g_sub, TypeGraph) or not isinstance(g_super, TypeGraph):
        raise TypeError("g_sub and g_super must be TypeGraph instances")
    if not isinstance(certificate, SubtypingCertificate):
        raise TypeError("certificate must be a SubtypingCertificate")
    relation = set(certificate.related_pairs)
    root_state: State = (certificate.root_pair[0], certificate.root_pair[1], False)
    if root_state not in relation:
        return False
    for a, b, rev in relation:
        if not (0 <= a < len(g_sub)) or not (0 <= b < len(g_super)):
            return False
        kids, mismatch = _state_obligations(g_sub, g_super, (a, b, rev))
        if mismatch is not None or kids is None:
            return False
        for child, _step in kids:
            if child not in relation:
                return False
    return True
