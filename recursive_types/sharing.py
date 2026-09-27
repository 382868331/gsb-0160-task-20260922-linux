"""把一张类型图整理成可共享（hash-consed / 最小化）的表示。

动机
----
等价检查回答“两个类型是否相同”；本模块回答另一个问题：把同一张图内
含义相同但写法不同的节点合并，得到一个去重后的共享表示，后续比较、
缓存、序列化都可以直接在更小的图上进行，而不必每次从头遍历原图。

语义
----
合并判据是单图内的 bisimulation（equi-recursive 等价）+ 字段可变性一致：
两个节点被合并，当且仅当它们的无限展开树相同，且对应路径上同名字段的
mutable 标记完全一致。字段名与可变性都是节点签名的一部分，合并不会
丢失它们；种类不同、字段名集合不同、同名可变性不同、参数元数不同的节点
永远不会合并。

循环不靠无限展开处理：用划分精化（partition refinement，DFA 最小化的
经典思想）在有限图上直接求最粗稳定划分——初始按一层签名分桶，随后反复
用“子节点所在类”细化签名直至不动点。有限图上该不动点恰好是 bisimulation
等价关系，环上的相互依赖在迭代中自然收敛，不需要任何展开。

输出
----
SharedForm 包含：

* graph：整理后的 TypeGraph，每个等价类恰好一个节点；
* mapping：mapping[i] 为原节点 i 在整理后图中的编号
  （覆盖原图全部节点，含从根不可达的节点）。

幂等性
----
整理是幂等的：对 share_graph(g).graph 再次整理不会引入任何新的结构
变化——节点序列、根、边逐一相同（确定性编号保证这一点，见
tests/test_sharing.py 的往返断言）。
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
    ProductNode,
    SumNode,
    TypeGraph,
)

__all__ = ["SharedForm", "share_graph"]


@dataclass(frozen=True)
class SharedForm:
    """一张类型图的共享（去重）表示及原节点对应关系。"""

    graph: TypeGraph
    mapping: tuple[int, ...]

    @property
    def merged_count(self) -> int:
        """被合并掉的节点数（原节点数 - 整理后节点数）。"""
        return len(self.mapping) - len(self.graph)

    def render(self) -> str:
        lines = [
            f"shared form: {len(self.mapping)} node(s) -> "
            f"{len(self.graph)} class node(s) "
            f"({self.merged_count} merged), root = {self.graph.root}",
        ]
        for cls_idx, node in enumerate(self.graph.nodes):
            members = [i for i, c in enumerate(self.mapping) if c == cls_idx]
            lines.append(
                f"  class {cls_idx} <- original {members}: {_describe(node)}"
            )
        return "\n".join(lines)


def _describe(node: object) -> str:
    kind = node.kind  # type: ignore[attr-defined]
    if kind in (INT, BOOL):
        return kind
    if kind in (PRODUCT, SUM):
        parts = ", ".join(
            f"{f.name}{'/mut' if f.mutable else ''}->{f.target}"
            for f in node.fields  # type: ignore[attr-defined]
        )
        return f"{kind}({parts})"
    params = ", ".join(str(p) for p in node.params)  # type: ignore[attr-defined]
    return f"Function(({params}) -> {node.result})"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 划分精化：求单图内的最粗稳定划分（bisimulation 等价类，含可变性判据）
# --------------------------------------------------------------------------- #


def _base_signature(node: object) -> tuple:
    """不依赖子节点类别的一层签名（种类 + 字段名/可变性 / 参数元数）。"""
    kind = node.kind  # type: ignore[attr-defined]
    if kind in (INT, BOOL):
        return (kind,)
    if kind in (PRODUCT, SUM):
        fields = tuple(
            sorted(
                (f.name, f.mutable)
                for f in node.fields  # type: ignore[attr-defined]
            )
        )
        return (kind, fields)
    # Function：有序参数个数（位置在精化签名里逐位体现）
    return (kind, len(node.params))  # type: ignore[attr-defined]


def _refined_signature(node: object, classes: tuple[int, ...]) -> tuple:
    """把子节点替换为其当前类编号后的完整签名。"""
    kind = node.kind  # type: ignore[attr-defined]
    if kind in (INT, BOOL):
        return (kind,)
    if kind in (PRODUCT, SUM):
        fields = tuple(
            sorted(
                (f.name, f.mutable, classes[f.target])
                for f in node.fields  # type: ignore[attr-defined]
            )
        )
        return (kind, fields)
    params = tuple(classes[p] for p in node.params)  # type: ignore[attr-defined]
    return (kind, params, classes[node.result])  # type: ignore[attr-defined]


def _equivalence_classes(g: TypeGraph) -> tuple[int, ...]:
    """返回 classes[i]：节点 i 的等价类编号（0..k-1，按首现顺序）。

    划分精化到不动点；有限图上最粗稳定划分即 bisimulation 等价。
    """
    nodes = g.nodes

    def repartition(signatures: list[tuple]) -> tuple[int, ...]:
        table: dict[tuple, int] = {}
        out: list[int] = []
        for sig in signatures:
            cls = table.get(sig)
            if cls is None:
                cls = len(table)
                table[sig] = cls
            out.append(cls)
        return tuple(out)

    classes = repartition([_base_signature(node) for node in nodes])
    while True:
        refined = repartition(
            [_refined_signature(node, classes) for node in nodes]
        )
        if len(set(refined)) == len(set(classes)):
            # 类数不再增加 => 划分稳定（同类节点的子节点仍同类）。
            return refined
        classes = refined


# --------------------------------------------------------------------------- #
# 确定性编号与重建
# --------------------------------------------------------------------------- #


def _class_children(node: object) -> list[int]:
    """按确定性顺序列出子节点目标：字段按名排序，函数按参数序再返回。"""
    kind = node.kind  # type: ignore[attr-defined]
    if kind in (PRODUCT, SUM):
        return [
            f.target
            for f in sorted(
                node.fields, key=lambda f: f.name  # type: ignore[attr-defined]
            )
        ]
    if kind == FUNCTION:
        return list(node.params) + [node.result]  # type: ignore[attr-defined]
    return []


def _canonical_order(g: TypeGraph, classes: tuple[int, ...]) -> list[int]:
    """给等价类一个确定性编号：从根所在类 BFS，再按最小成员补不可达类。"""
    representative: dict[int, int] = {}
    for i, cls in enumerate(classes):
        representative.setdefault(cls, i)

    order: list[int] = []
    seen: set[int] = set()

    def bfs(start_cls: int) -> None:
        queue: deque[int] = deque([start_cls])
        seen.add(start_cls)
        while queue:
            cls = queue.popleft()
            order.append(cls)
            rep = representative[cls]
            for target in _class_children(g[rep]):
                child_cls = classes[target]
                if child_cls not in seen:
                    seen.add(child_cls)
                    queue.append(child_cls)

    bfs(classes[g.root])
    for cls in sorted(representative, key=lambda c: representative[c]):
        if cls not in seen:
            bfs(cls)
    return order


def share_graph(g: TypeGraph) -> SharedForm:
    """把 g 整理成共享表示：合并含义相同的重复节点。

    :param g: 经 TypeGraph 校验的类型图。
    :returns: SharedForm，graph 为整理后的图，
        mapping[i] 为原节点 i 对应的整理后节点编号。
    :raises TypeError: g 不是 TypeGraph。

    保证：

    * 合并不改变语义——原节点 i 与 mapping[i] 处类型
      equi-recursive 等价，且字段名与 mutable 标记逐条保留；
    * 幂等——对结果再次 share_graph 不再产生任何结构变化。
    """
    if not isinstance(g, TypeGraph):
        raise TypeError(
            f"g must be a TypeGraph instance (got {type(g).__name__})"
        )
    classes = _equivalence_classes(g)
    order = _canonical_order(g, classes)
    new_index = {cls: idx for idx, cls in enumerate(order)}

    representative: dict[int, int] = {}
    for i, cls in enumerate(classes):
        representative.setdefault(cls, i)

    new_nodes: list = []
    for cls in order:
        node = g[representative[cls]]
        kind = node.kind
        if kind in (INT, BOOL):
            new_nodes.append(node)
        elif kind in (PRODUCT, SUM):
            fields = tuple(
                Field(f.name, new_index[classes[f.target]], f.mutable)
                for f in node.fields
            )
            new_nodes.append(
                ProductNode(fields) if kind == PRODUCT else SumNode(fields)
            )
        else:
            params = tuple(new_index[classes[p]] for p in node.params)
            new_nodes.append(
                FunctionNode(params, new_index[classes[node.result]])
            )

    shared = TypeGraph(new_nodes, new_index[classes[g.root]])
    mapping = tuple(new_index[cls] for cls in classes)
    return SharedForm(shared, mapping)

