"""规范化：把互为双模拟的节点合并成有限商图（共享表示的缓存键）。

动机
----
缓存类型时，同一种无限展开类型可能有许多不同编号的图：共享方式不同、
子图被复制、环长不同但展开相同。本模块提供规范化入口
:func:`canonicalize`，按本库既有的 equi-recursive 等价语义
（无限展开树相等，即双模拟）把一张图内互为双模拟的节点合并，
返回**有限商图**、**旧节点到新节点的映射**和**从根开始的确定编号**。

算法
----
1. **只处理根可达部分**：从根出发遍历（Product/Sum 字段按名排序、
   Function 参数按次序、返回最后），不可达节点不进入商图，
   其映射为 ``None``。
2. **稳定等价划分**：在可达节点上按“一层标签 + 各后继所在类”迭代细分，
   直到划分稳定（最粗稳定划分 = 双模拟等价类）。细分只按结构签名进行，
   旧节点编号从不参与语义平局裁决。
3. **确定编号**：从商图根出发 BFS，子节点访问顺序固定为
   “字段按名排序 / 参数按次序 / 返回最后”，首次遇到的类依次编号
   0, 1, 2, …。编号完全由结构决定：输入编号任意置换后输出字节序列不变。

保证
----
* 不同共享方式、复制子图、环长不同但展开相同的图，输出同一表示
  （``to_bytes()`` 相同）；
* 不相同的类型不会因局部标签相同而合并（稳定划分对整棵展开树负责，
  不只对一层标签负责）；
* 原根与商图根在 :func:`recursive_types.check_equivalence` 意义下等价，
  且每个合并类内节点的标签与后继类一致（可独立复核，见测试）。
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
    Field,
    FunctionNode,
    IntNode,
    Node,
    ProductNode,
    SumNode,
    TypeGraph,
)

_LEAF_KINDS = (INT, BOOL)
_LABELLED_KINDS = (PRODUCT, SUM)


@dataclass(frozen=True)
class CanonicalForm:
    """一张类型图的规范化结果。

    * ``graph``：有限商图。根恒为 ``0``，节点按“从根 BFS、字段按名 /
      参数按序 / 返回最后”的约定顺序编号，不含不可达节点。
    * ``mapping``：``mapping[旧编号] = 新编号``；根不可达的旧节点为 ``None``。
    * ``classes``：``classes[新编号]`` 为该合并类的旧节点成员（升序）。
    """

    graph: TypeGraph
    mapping: tuple[int | None, ...]
    classes: tuple[tuple[int, ...], ...]

    def to_bytes(self) -> bytes:
        """商图的确定字节序列（缓存键）。

        只依赖商图结构：字段按名排序后顺序序列化。同一无限展开类型的
        任何输入编号/布局都产生相同的字节序列；``mapping``/``classes``
        含旧编号，不参与本序列。
        """
        parts: list[tuple] = []
        for node in self.graph.nodes:
            kind = node.kind
            if kind in _LEAF_KINDS:
                parts.append((kind,))
            elif kind in _LABELLED_KINDS:
                assert isinstance(node, (ProductNode, SumNode))
                fields = tuple(
                    (f.name, f.target)
                    for f in sorted(node.fields, key=lambda f: f.name)
                )
                parts.append((kind, fields))
            else:
                assert isinstance(node, FunctionNode)
                parts.append((kind, node.params, node.result))
        return repr((self.graph.root, tuple(parts))).encode("utf-8")

    def render(self) -> str:
        """人类可读的商图摘要（调试用）。"""
        lines = [
            f"CanonicalForm: {len(self.graph)} class node(s), root=0",
        ]
        for i, node in enumerate(self.graph.nodes):
            members = ",".join(str(m) for m in self.classes[i])
            lines.append(f"  #{i} <- old[{members}]: {_render_node(node)}")
        unreachable = [
            i for i, m in enumerate(self.mapping) if m is None
        ]
        if unreachable:
            lines.append(f"  unreachable old nodes dropped: {unreachable}")
        return "\n".join(lines)


def _render_node(node: Node) -> str:
    if isinstance(node, (ProductNode, SumNode)):
        body = ", ".join(f"{f.name}->#{f.target}" for f in node.fields)
        return f"{node.kind}{{{body}}}"
    if isinstance(node, FunctionNode):
        params = ", ".join(f"#{p}" for p in node.params)
        return f"Function({params}) -> #{node.result}"
    return node.kind


def _ordered_targets(node: Node) -> tuple[int, ...]:
    """约定的子节点遍历顺序：字段按名排序；参数按次序、返回最后。"""
    if isinstance(node, (ProductNode, SumNode)):
        return tuple(f.target for f in sorted(node.fields, key=lambda f: f.name))
    if isinstance(node, FunctionNode):
        return tuple(node.params) + (node.result,)
    return ()


def _initial_key(node: Node) -> tuple:
    """一层标签签名（不含后继）：细分迭代的起点。"""
    kind = node.kind
    if kind in _LEAF_KINDS:
        return (kind,)
    if kind in _LABELLED_KINDS:
        assert isinstance(node, (ProductNode, SumNode))
        return (kind, tuple(sorted(f.name for f in node.fields)))
    assert isinstance(node, FunctionNode)
    return (kind, len(node.params))


def _refined_key(node: Node, class_of: list[int]) -> tuple:
    """一层标签 + 各后继当前所在类；相同 iff 当前划分下不可区分。"""
    kind = node.kind
    if kind in _LEAF_KINDS:
        return (kind,)
    if kind in _LABELLED_KINDS:
        assert isinstance(node, (ProductNode, SumNode))
        return (
            kind,
            tuple(
                (f.name, class_of[f.target])
                for f in sorted(node.fields, key=lambda f: f.name)
            ),
        )
    assert isinstance(node, FunctionNode)
    return (
        kind,
        tuple(class_of[p] for p in node.params),
        class_of[node.result],
    )


def _reachable_nodes(graph: TypeGraph) -> list[int]:
    """从根可达的旧节点集合（升序返回）。"""
    seen: set[int] = {graph.root}
    queue: deque[int] = deque([graph.root])
    while queue:
        x = queue.popleft()
        for t in _ordered_targets(graph[x]):
            if t not in seen:
                seen.add(t)
                queue.append(t)
    return sorted(seen)


def _stable_partition(
    graph: TypeGraph, reachable: list[int]
) -> dict[int, int]:
    """可达节点上的最粗稳定划分（双模拟等价类）。

    返回 ``{旧编号: 类内部号}``。迭代细分只按结构签名分裂，
    细分是单调的（只裂不合），类数不变即达到不动点。
    """
    class_of: dict[int, int] = {}
    keys: dict[int, tuple] = {i: _initial_key(graph[i]) for i in reachable}

    def renumber(current: dict[int, tuple]) -> dict[int, int]:
        ids: dict[tuple, int] = {}
        out: dict[int, int] = {}
        for i in reachable:  # 扫描顺序只影响内部号，不影响最终划分
            key = current[i]
            if key not in ids:
                ids[key] = len(ids)
            out[i] = ids[key]
        return out

    class_of = renumber(keys)
    while True:
        next_keys = {
            i: _refined_key(graph[i], _class_list(class_of, len(graph)))
            for i in reachable
        }
        # 键里混入了“当前类号”，不同轮的类号不可直接比较；
        # 统一在本轮内重新编号后再比较类数。
        next_class_of = renumber(next_keys)
        if len(set(next_class_of.values())) == len(set(class_of.values())):
            # 细分单调：类数不变 => 划分已稳定（不动点）。
            return next_class_of
        class_of = next_class_of
        keys = next_keys


def _class_list(class_of: dict[int, int], n: int) -> list[int]:
    """把 ``{旧编号: 类号}`` 转成按下标取类号的列表（仅可达项有意义）。"""
    out = [-1] * n
    for i, c in class_of.items():
        out[i] = c
    return out


def canonicalize(graph: TypeGraph) -> CanonicalForm:
    """把 ``graph`` 规范化为有限商图。

    :param graph: 经 :class:`TypeGraph` 校验的类型图。
    :returns: :class:`CanonicalForm`（商图 + 旧→新映射 + 各类成员）。
    :raises TypeError: ``graph`` 不是 :class:`TypeGraph`。
    """
    if not isinstance(graph, TypeGraph):
        raise TypeError(
            f"graph must be a TypeGraph instance (got {type(graph).__name__})"
        )

    reachable = _reachable_nodes(graph)
    class_of = _stable_partition(graph, reachable)

    # 从商图根按约定顺序 BFS 编号：0, 1, 2, …
    # 子节点顺序由 _ordered_targets 固定，编号与旧节点编号无关。
    new_id: dict[int, int] = {class_of[graph.root]: 0}
    queue: deque[int] = deque([class_of[graph.root]])
    while queue:
        c = queue.popleft()
        rep = min(i for i in reachable if class_of[i] == c)
        for t in _ordered_targets(graph[rep]):
            tc = class_of[t]
            if tc not in new_id:
                new_id[tc] = len(new_id)
                queue.append(tc)

    # 用各类任一成员搭建商图节点：同类成员的一层标签与后继类一致，
    # 故取最小旧编号作代表不改变结果结构。
    quotient: list[Node] = [IntNode()] * len(new_id)  # 占位，随即全部覆写
    for c, nid in new_id.items():
        rep = min(i for i in reachable if class_of[i] == c)
        node = graph[rep]
        if isinstance(node, (ProductNode, SumNode)):
            fields = tuple(
                Field(f.name, new_id[class_of[f.target]]) for f in node.fields
            )
            quotient[nid] = (
                ProductNode(fields) if isinstance(node, ProductNode)
                else SumNode(fields)
            )
        elif isinstance(node, FunctionNode):
            quotient[nid] = FunctionNode(
                tuple(new_id[class_of[p]] for p in node.params),
                new_id[class_of[node.result]],
            )
        else:
            quotient[nid] = node

    # 旧→新映射；不可达旧节点为 None。
    mapping: list[int | None] = [None] * len(graph)
    for i in reachable:
        mapping[i] = new_id[class_of[i]]

    # 各类成员（按新编号索引，成员升序）。
    members: list[list[int]] = [[] for _ in range(len(new_id))]
    for i in reachable:
        members[new_id[class_of[i]]].append(i)
    classes = tuple(tuple(sorted(m)) for m in members)

    return CanonicalForm(
        graph=TypeGraph(quotient, 0),
        mapping=tuple(mapping),
        classes=classes,
    )
