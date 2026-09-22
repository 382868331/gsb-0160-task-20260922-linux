"""成对节点协同检查：equi-recursive 类型等价判定核心。

语义
----

两个有根图表示的类型按其**无限展开树**定义等价（equi-recursive）。
无限树相等是余归纳概念：根对相关，当且仅当两端节点头构造一致且
按对应关系产生的每个子节点对也相关。在有限图上，这通过在节点对的
乘积图上求一个有界的一致关系（互模拟）来判定：

* 从根对出发做协同遍历；
* 节点对 ``(u, v)`` 的**头条件**：kind 相同；Product/Sum 的字段名集合
  相同；Function 的参数个数相同（原子节点无进一步条件）；
* 头条件满足时产生**义务子对**：Product/Sum 按字段名对应（与书写顺序
  无关），Function 按参数位置对应再加返回对；
* 再次遇到已访问的对时闭合（递归被关系吸收）。

遍历采用 BFS。若整棵乘积可达部分无头冲突，访问过的对集合本身就是
互模拟证书；若遇到冲突，BFS 父链给出**展开深度最短**的分歧路径。

节点标识从不参与比较：编号只用于在图中定位，重命名节点、共享子图或
复制子图都不影响结果。

预算
----

每个出队处理的节点对计一个工作单元，可达对至多 ``n1 * n2`` 个，
默认预算 ``n1 * n2 + 1`` 在数学上足以完成检查（预算耗尽在默认配置下
不会发生）。调用方可传入更小的预算；耗尽时抛
:class:`~rectypes.errors.BudgetExhaustedError`，它与“已证明不等价”
（:class:`Divergence`）严格区分：耗尽只表示没算完，无结论。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .certificate import Certificate, verify_certificate
from .errors import BudgetExhaustedError, RecTypeError
from .model import TypeGraph


class InvalidArgument(RecTypeError):
    """调用参数本身不合法（如图对象类型错误、预算非法）。"""


@dataclass(frozen=True)
class Step:
    """分歧/展开路径上的一步。

    :param left: 左图节点标识。
    :param right: 右图节点标识。
    :param access: 到达该对所用的访问子，``"root"`` 或
        ``("field", 字段名)`` / ``("param", 下标)`` / ``("result",)``。
    """

    left: object
    right: object
    access: object

    def access_text(self) -> str:
        if self.access == "root":
            return "root"
        kind = self.access[0]
        if kind == "field":
            return f"field {self.access[1]!r}"
        if kind == "param":
            return f"param #{self.access[1]}"
        return "result"


@dataclass(frozen=True)
class Divergence:
    """最短分歧路径及其原因。"""

    steps: tuple[Step, ...]
    reason: str

    @property
    def depth(self) -> int:
        """分歧点在无限展开树上的深度（根对为 0）。"""
        return len(self.steps) - 1

    @property
    def clashing_pair(self) -> tuple[object, object]:
        last = self.steps[-1]
        return (last.left, last.right)

    def render(self) -> str:
        lines = [
            f"NOT equivalent: {self.reason}",
            f"shortest divergence path (depth {self.depth}):",
        ]
        for depth, step in enumerate(self.steps):
            lines.append(
                f"  [{depth}] {step.access_text():>12}: "
                f"{step.left!r}  vs  {step.right!r}"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class EquivalenceResult:
    """检查结果。恰有一个结论字段非空。

    :param equivalent: 是否等价。
    :param certificate: 等价时的关系证书（并已通过独立验证器）。
    :param divergence: 不等价时的最短分歧路径。
    :param work_units: 实际消耗的工作单元数。
    """

    equivalent: bool
    certificate: Optional[Certificate]
    divergence: Optional[Divergence]
    work_units: int

    def render(self) -> str:
        if self.equivalent:
            assert self.certificate is not None
            return (
                f"equivalent: relation with {len(self.certificate.pairs)} "
                f"pair(s) closes (work units: {self.work_units})"
            )
        assert self.divergence is not None
        return self.divergence.render()


def _check_budget(budget: object) -> int:
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise InvalidArgument(
            "budget must be a non-negative int (bool and float rejected), "
            f"got {type(budget).__name__}"
        )
    if budget < 0:
        raise InvalidArgument(f"budget must be >= 0, got {budget}")
    return budget


def _head_clash(g1: TypeGraph, g2: TypeGraph, u: object, v: object) -> Optional[str]:
    """返回头冲突原因；一致时返回 ``None``。"""
    n1, n2 = g1.nodes[u], g2.nodes[v]
    k1, k2 = n1["kind"], n2["kind"]
    if k1 != k2:
        return f"node kinds differ: {k1} vs {k2}"
    if k1 in ("Product", "Sum"):
        s1 = {name for name, _ in n1["fields"]}
        s2 = {name for name, _ in n2["fields"]}
        if s1 != s2:
            noun = "field names" if k1 == "Product" else "labels"
            only1 = sorted(s1 - s2)
            only2 = sorted(s2 - s1)
            return (
                f"{k1} {noun} differ: only-left={only1!r}, only-right={only2!r}"
            )
        return None
    if k1 == "Function":
        c1, c2 = len(n1["params"]), len(n2["params"])
        if c1 != c2:
            return f"parameter counts differ: {c1} vs {c2}"
        return None
    return None  # Int / Bool 且 kind 相同


def _obligations(
    g1: TypeGraph, g2: TypeGraph, u: object, v: object
) -> list[tuple[tuple[object, object], object]]:
    """头条件一致后，产生有序的义务子对（仅在无冲突时调用）。"""
    n1, n2 = g1.nodes[u], g2.nodes[v]
    kind = n1["kind"]
    out: list[tuple[tuple[object, object], object]] = []
    if kind in ("Product", "Sum"):
        f1 = dict(n1["fields"])
        f2 = dict(n2["fields"])
        for name in sorted(set(f1)):  # 名称集合同，按名排序保证确定性
            out.append(((f1[name], f2[name]), ("field", name)))
    elif kind == "Function":
        for i, (a, b) in enumerate(zip(n1["params"], n2["params"])):
            out.append(((a, b), ("param", i)))
        out.append(((n1["result"], n2["result"]), ("result",)))
    return out


def check_equivalence(
    g1: TypeGraph,
    g2: TypeGraph,
    *,
    budget: Optional[int] = None,
) -> EquivalenceResult:
    """检查两个有根类型图的 equi-recursive 等价性。

    :param g1: 左类型图（:class:`~rectypes.model.TypeGraph`）。
    :param g2: 右类型图。
    :param budget: 搜索预算（工作单元 = 处理的节点对数）；``None`` 时取
        ``len(g1) * len(g2) + 1``，对本接口的图规模必然足够。
    :returns: :class:`EquivalenceResult`。
    :raises BudgetExhaustedError: 预算先于结论耗尽（无结论，区别于不等价）。
    :raises InvalidArgument: 参数类型错误。
    """
    if not isinstance(g1, TypeGraph) or not isinstance(g2, TypeGraph):
        raise InvalidArgument(
            "both arguments must be TypeGraph instances constructed beforehand"
        )
    if budget is None:
        budget = len(g1) * len(g2) + 1
    budget = _check_budget(budget)

    root_pair: tuple[object, object] = (g1.root, g2.root)
    visited: set[tuple[object, object]] = {root_pair}
    order: list[tuple[object, object]] = [root_pair]
    # pair -> (父对, 到达访问子)；根对为 None
    parent: dict[tuple[object, object], Optional[tuple[object, object]]] = {
        root_pair: None
    }
    access_of: dict[tuple[object, object], object] = {root_pair: "root"}
    queue: deque[tuple[object, object]] = deque([root_pair])
    used = 0

    while queue:
        if used >= budget:
            raise BudgetExhaustedError(used, budget)
        u, v = queue.popleft()
        used += 1

        reason = _head_clash(g1, g2, u, v)
        if reason is not None:
            divergence = _build_divergence((u, v), parent, access_of, reason)
            return EquivalenceResult(False, None, divergence, used)

        for child_pair, access in _obligations(g1, g2, u, v):
            if child_pair not in visited:
                visited.add(child_pair)
                parent[child_pair] = (u, v)
                access_of[child_pair] = access
                order.append(child_pair)
                queue.append(child_pair)

    # 无冲突：visited 即互模拟关系；用独立验证器核验后再作为证书返回。
    cert = Certificate(
        roots=root_pair,
        pairs=tuple(order),
        graph_sizes=(len(g1), len(g2)),
    )
    verify_certificate(cert, g1, g2)
    return EquivalenceResult(True, cert, None, used)


def _build_divergence(
    clash_pair: tuple[object, object],
    parent: dict[tuple[object, object], Optional[tuple[object, object]]],
    access_of: dict[tuple[object, object], object],
    reason: str,
) -> Divergence:
    chain: list[tuple[object, object]] = []
    cur: Optional[tuple[object, object]] = clash_pair
    while cur is not None:
        chain.append(cur)
        cur = parent[cur]
    chain.reverse()
    steps = tuple(
        Step(left=u, right=v, access=access_of[(u, v)]) for u, v in chain
    )
    return Divergence(steps=steps, reason=reason)


def are_equivalent(g1: TypeGraph, g2: TypeGraph, *, budget: Optional[int] = None) -> bool:
    """便捷布尔接口；预算耗尽仍抛 :class:`BudgetExhaustedError`。"""
    return check_equivalence(g1, g2, budget=budget).equivalent
