"""规范化（canonicalization）：把等价节点压成共享表示的有限商图。

动机
----
缓存类型时，同一种无限展开类型可能有许多不同编号的图（共享方式不同、
子图被复制、环长不同但展开相同）。本模块提供规范化入口
:func:`canonicalize`：按与 :mod:`recursive_types.equivalence` 相同的
equi-recursive 语义，把根可达部分中**互为双模拟**的节点合并，返回

* 有限**商图**（:class:`TypeGraph`，从根开始的确定编号）；
* 旧节点到新节点的映射 ``old_to_new``（不可达节点映射为 ``-1``）；
* 确定性的**字节表示**（:meth:`CanonicalForm.to_bytes`），
  输入编号任意置换后字节序列不变。

算法
----
1. **可达性**：只处理根可达节点；遍历顺序固定为——Product/Sum 字段按名
   （字典序）、Function 参数按声明次序、返回最后。
2. **稳定等价划分**：以一层标签（种类；Product/Sum 的字段名集合；
   Function 的参数个数）为初始划分，反复按
   ``(一层标签, 后继类编号元组)`` 精化，直到不动点。所得划分即
   bisimulation 等价类（最大不动点），同类节点无限展开树相同，
   异类节点必不同——不会只因局部标签相同而合并。
3. **商图编号**：从根所在类出发按同一约定顺序做 BFS，按首次访问顺序
   编号 0,1,2,…。编号只依赖商图结构与遍历约定，**不使用旧节点编号
   打破语义平局**，因此同语义的不同输入得到逐字节相同的表示。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .model import (
    BOOL,
    FUNCTION,
    INT,
    PRODUCT,
    SUM,
    BoolNode,
    Field,
    FunctionNode,
    IntNode,
    Node,
    ProductNode,
    SumNode,
    TypeGraph,
)

__all__ = ["CanonicalForm", "canonicalize"]


# --------------------------------------------------------------------------- #
# 一层标签与约定顺序的后继
# --------------------------------------------------------------------------- #


def _local_label(node: Node) -> tuple:
    """节点的一层标签：种类 + 局部结构（不含任何后继编号）。"""
    kind = node.kind
    if kind in (INT, BOOL):
        return (kind,)
    if kind in (PRODUCT, SUM):
        assert isinstance(node, (ProductNode, SumNode))
        return (kind, tuple(sorted(f.name for f in node.fields)))
    if kind == FUNCTION:
        assert isinstance(node, FunctionNode)
        return (kind, len(node.params))
    raise AssertionError(f"unhandled kind {kind!r}")  # pragma: no cover


def _ordered_successors(node: Node) -> tuple[int, ...]:
    """按约定顺序的后继：字段按名（字典序）；参数按次序，返回最后。"""
    kind = node.kind
    if kind in (INT, BOOL):
        return ()
    if kind in (PRODUCT, SUM):
        assert isinstance(node, (ProductNode, SumNode))
        return tuple(f.target for f in sorted(node.fields, key=lambda f: f.name))
    if kind == FUNCTION:
        assert isinstance(node, FunctionNode)
        return (*node.params, node.result)
    raise AssertionError(f"unhandled kind {kind!r}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# 规范化结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CanonicalForm:
    """一张类型图根类型的规范化表示。

    * ``graph``：商图，只含根可达部分的等价类，根编号为 0，
      其余编号按约定顺序 BFS 首次访问次序确定；
    * ``old_to_new``：长度等于原图节点数的元组，``old_to_new[i]`` 为原节点
      ``i`` 所属等价类在商图中的编号；根不可达的节点为 ``-1``；
    * ``root``：商图根编号（恒为 0，显式给出以便阅读）。
    """

    graph: TypeGraph
    old_to_new: tuple[int, ...]
    root: int

    def to_bytes(self) -> bytes:
        """确定性字节表示：只依赖商图结构，与输入编号无关。

        布局：``[节点数 u32][根 u32][逐节点记录]``；整数均为 4 字节大端。
        节点记录：种类字节（``I/B/P/S/F``）；Product/Sum 随后为字段数与
        逐字段 ``[名字长 u32][名字 UTF-8][目标 u32]``（字段已按名排序）；
        Function 随后为参数个数、各参数编号与返回编号。
        """
        g = self.graph
        out = bytearray()
        out += len(g).to_bytes(4, "big")
        out += self.root.to_bytes(4, "big")
        for i in range(len(g)):
            node = g[i]
            kind = node.kind
            if kind == INT:
                out += b"I"
            elif kind == BOOL:
                out += b"B"
            elif kind in (PRODUCT, SUM):
                assert isinstance(node, (ProductNode, SumNode))
                out += b"P" if kind == PRODUCT else b"S"
                fields = sorted(node.fields, key=lambda f: f.name)
                out += len(fields).to_bytes(4, "big")
                for f in fields:
                    name = f.name.encode("utf-8")
                    out += len(name).to_bytes(4, "big")
                    out += name
                    out += f.target.to_bytes(4, "big")
            elif kind == FUNCTION:
                assert isinstance(node, FunctionNode)
                out += b"F"
                out += len(node.params).to_bytes(4, "big")
                for p in node.params:
                    out += p.to_bytes(4, "big")
                out += node.result.to_bytes(4, "big")
            else:  # pragma: no cover
                raise AssertionError(f"unhandled kind {kind!r}")
        return bytes(out)


# --------------------------------------------------------------------------- #
# 规范化入口
# --------------------------------------------------------------------------- #


def _check_root(root: object, g: TypeGraph, name: str) -> int:
    if type(root) is not int:
        kind = "bool" if isinstance(root, bool) else type(root).__name__
        raise TypeError(f"{name} must be a strict int (got {kind})")
    if not 0 <= root < len(g):
        raise ValueError(
            f"{name}={root} out of range for graph with {len(g)} node(s)"
        )
    return root  # type: ignore[return-value]


def _reachable(g: TypeGraph, root: int) -> list[int]:
    """按约定顺序 BFS 收集根可达节点（返回顺序即首次访问顺序）。"""
    seen = {root}
    order = [root]
    queue: deque[int] = deque([root])
    while queue:
        x = queue.popleft()
        for s in _ordered_successors(g[x]):
            if s not in seen:
                seen.add(s)
                order.append(s)
                queue.append(s)
    return order


def _stable_partition(g: TypeGraph, reachable: list[int]) -> dict[int, int]:
    """对可达节点求 bisimulation 稳定划分；返回 ``节点 -> 类编号``。

    初始按一层标签分类；随后反复用 ``(一层标签, 后继类编号元组)`` 精化，
    类编号每轮按签名字典序重排（确定性，与旧节点编号无关），直到收敛。
    """
    labels = {i: _local_label(g[i]) for i in reachable}
    class_of = {i: 0 for i in reachable}
    distinct = sorted({labels[i] for i in reachable})
    rank = {label: k for k, label in enumerate(distinct)}
    for i in reachable:
        class_of[i] = rank[labels[i]]

    while True:
        signatures = {
            i: (labels[i], tuple(class_of[s] for s in _ordered_successors(g[i])))
            for i in reachable
        }
        distinct = sorted({signatures[i] for i in reachable})
        rank = {sig: k for k, sig in enumerate(distinct)}
        new_class_of = {i: rank[signatures[i]] for i in reachable}
        if len(distinct) == len(set(class_of.values())):
            # 类数不再增加：划分已稳定（精化只会细分，不会合并）。
            return new_class_of
        class_of = new_class_of


def canonicalize(graph: TypeGraph, *, root: int | None = None) -> CanonicalForm:
    """把 ``graph`` 根类型压缩为共享表示的有限商图。

    :param graph: 经 :class:`TypeGraph` 校验的类型图。
    :param root: 可选的根节点覆盖；缺省用图的 ``root``。
        给定值必须是严格 int（非 bool）且在图范围内。
    :returns: :class:`CanonicalForm`，含商图、旧节点到新节点的映射
        （不可达节点为 ``-1``）与商图根编号。
    :raises TypeError/ValueError: 参数种类或取值非法（在任何计算前拒绝）。
    """
    if not isinstance(graph, TypeGraph):
        raise TypeError(
            f"graph must be a TypeGraph instance (got {type(graph).__name__})"
        )
    r = graph.root if root is None else _check_root(root, graph, "root")

    reachable = _reachable(graph, r)
    class_of = _stable_partition(graph, reachable)

    # 类 -> 该类在约定顺序下的后继类（商图边）。
    rep: dict[int, int] = {}  # 类编号 -> 代表节点（任取其一；结构同类一致）
    for i in reachable:
        rep.setdefault(class_of[i], i)

    # 从根类按约定顺序 BFS，按首次访问次序确定新编号；不用旧编号打破平局。
    root_class = class_of[r]
    new_id: dict[int, int] = {root_class: 0}
    queue: deque[int] = deque([root_class])
    while queue:
        c = queue.popleft()
        for s in _ordered_successors(graph[rep[c]]):
            sc = class_of[s]
            if sc not in new_id:
                new_id[sc] = len(new_id)
                queue.append(sc)

    # 按新编号构造商图节点。
    new_nodes: list[Node] = [IntNode()] * len(new_id)
    for c, nid in new_id.items():
        node = graph[rep[c]]
        kind = node.kind
        if kind == INT:
            new_nodes[nid] = IntNode()
        elif kind == BOOL:
            new_nodes[nid] = BoolNode()
        elif kind in (PRODUCT, SUM):
            assert isinstance(node, (ProductNode, SumNode))
            fields = tuple(
                Field(f.name, new_id[class_of[f.target]])
                for f in sorted(node.fields, key=lambda f: f.name)
            )
            if kind == PRODUCT:
                new_nodes[nid] = ProductNode(fields)
            else:
                new_nodes[nid] = SumNode(fields)
        elif kind == FUNCTION:
            assert isinstance(node, FunctionNode)
            new_nodes[nid] = FunctionNode(
                tuple(new_id[class_of[p]] for p in node.params),
                new_id[class_of[node.result]],
            )
        else:  # pragma: no cover
            raise AssertionError(f"unhandled kind {kind!r}")

    quotient = TypeGraph(new_nodes, 0)
    old_to_new = tuple(
        new_id[class_of[i]] if i in class_of else -1 for i in range(len(graph))
    )
    return CanonicalForm(quotient, old_to_new, 0)
