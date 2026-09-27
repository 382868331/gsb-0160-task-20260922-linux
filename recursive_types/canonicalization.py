"""把一组类型图整理成可共享的规范化表示（核心算法）。

目标
----
equivalence.check_equivalence 只能回答“两张图是否等价”，每次比较都要从根
协同遍历。本模块则把**一组**（一张或多张）类型图一次性整理为一张**共享的**
规范化类型图 graph：

* 无限展开树相同（equi-recursive 等价）的所有节点，无论写法（节点编号、
  字段声明顺序、共享 vs 复制子图、跨哪张输入图）如何，都合并为同一个
  规范化节点；
* 字段名与字段**可变性**（Field.mutable）是语义的一部分，不一致绝不合并；
* 循环类型靠分区精化（partition refinement / coarsest stable partition）
  处理，**不做任何无限展开**；
* 返回每个原节点到规范化节点的对应关系，后续比较只需比对规范化节点号，
  不必再从头遍历。

幂等
----
规范化是结构上的归一：对规范化结果再次运行 canonicalize，得到的图
节点数、结构与节点上的规范化编号都不再发生新变化（对应关系为恒等）。

预算
----
budget 限定“为节点计算一次签名”的次数；预算在精化收敛前耗尽抛
BudgetExceededError（结果未知）。每次精化扫描全部节点，最多 N 轮收敛。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import BudgetExceededError, GraphSizeError
from .model import (
    BOOL,
    FUNCTION,
    INT,
    MAX_NODES,
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

#: 默认签名计算预算（节点数 × 最多 N 轮精化）。
DEFAULT_CANONICAL_BUDGET = 100_000


@dataclass(frozen=True)
class Canonicalization:
    """一组输入图的规范化结果。

    :cvar graph: 共享的规范化 :class:`TypeGraph`；其根固定为第 0 张输入图
        的根所对应的规范化节点。多图整理时请使用 :attr:`roots`。
    :cvar roots: 每张输入图的根（或显式 roots 覆盖）对应的规范化节点号。
    :cvar mapping: mapping[i] 是第 i 张输入图的逐节点对应表，
        mapping[i][j] 为该图节点 j 的规范化节点号。
    :cvar class_count: 规范化图节点数（语义等价类数）。
    :cvar total_input_nodes: 所有输入图的节点总数（合并前）。
    """

    graph: TypeGraph
    roots: tuple[int, ...]
    mapping: tuple[tuple[int, ...], ...]
    class_count: int
    total_input_nodes: int = field(compare=False)

    def render(self) -> str:
        return (
            f"CANONICAL: {self.total_input_nodes} input node(s) merged into "
            f"{self.class_count} shared node(s); roots -> {list(self.roots)}"
        )


def _initial_class(node: Node) -> tuple:
    """初始类：只看一层静态骨架（种类 / 字段名与可变性 / 参数元数）。"""
    kind = node.kind
    if kind in (INT, BOOL):
        return (kind,)
    if kind in (PRODUCT, SUM):
        fields = tuple(
            (f.name, f.mutable)
            for f in sorted(node.fields, key=lambda f: f.name)
        )
        return (kind, fields)
    if kind == FUNCTION:
        assert isinstance(node, FunctionNode)
        return (FUNCTION, len(node.params))
    raise AssertionError(f"unhandled kind {kind!r}")  # pragma: no cover


def _check_root(root: object, g: TypeGraph, name: str) -> int:
    if type(root) is not int:
        kind = "bool" if isinstance(root, bool) else type(root).__name__
        raise TypeError(f"{name} must be a strict int (got {kind})")
    if not 0 <= root < len(g):
        raise ValueError(
            f"{name}={root} out of range for graph with {len(g)} node(s)"
        )
    return root  # type: ignore[return-value]


def _renumber(classes: list[int]) -> list[int]:
    """按首次出现把类号压缩成 0..k-1（用于稳定比较）。"""
    order: dict[int, int] = {}
    out = [0] * len(classes)
    for i, c in enumerate(classes):
        if c not in order:
            order[c] = len(order)
        out[i] = order[c]
    return out


def _refine_partition(
    graphs: tuple[TypeGraph, ...], budget: int
) -> tuple[list[list[int]], int]:
    """对所有输入图的并集节点求最粗稳定分区。

    节点用扁平下标 flat = offset[i] + j 表示。初始类按一层静态骨架划分；
    随后每轮用“签名 = 自身骨架 + 子节点当前类”重新分块，直到分块不再变化。
    收敛时同块节点恰为 equi-recursive 等价节点（互模拟等价类）。
    """
    offsets: list[int] = []
    total = 0
    for g in graphs:
        offsets.append(total)
        total += len(g)

    used = 0

    initial_index: dict[tuple, int] = {}
    classes = [0] * total
    for gi, g in enumerate(graphs):
        base = offsets[gi]
        for j, node in enumerate(g.nodes):
            sig = _initial_class(node)
            if sig not in initial_index:
                initial_index[sig] = len(initial_index)
            classes[base + j] = initial_index[sig]

    while True:
        new_index: dict[tuple, int] = {}
        new_classes = [0] * total
        for gi, g in enumerate(graphs):
            base = offsets[gi]
            for j in range(len(g)):
                node = g[j]
                kind = node.kind
                if kind in (INT, BOOL):
                    sig: tuple = (kind,)
                elif kind in (PRODUCT, SUM):
                    sig = (
                        kind,
                        tuple(
                            (f.name, f.mutable, classes[base + f.target])
                            for f in sorted(node.fields, key=lambda f: f.name)
                        ),
                    )
                else:
                    assert isinstance(node, FunctionNode)
                    sig = (
                        FUNCTION,
                        tuple(classes[base + p] for p in node.params),
                        classes[base + node.result],
                    )
                used += 1
                if used > budget:
                    raise BudgetExceededError(budget, used)
                if sig not in new_index:
                    new_index[sig] = len(new_index)
                new_classes[base + j] = new_index[sig]

        # 分块数不变、且按首次出现重编号后归属也不变 => 分区稳定。
        stable = len(new_index) == len(set(classes)) and (
            new_classes == _renumber(classes)
        )
        classes = new_classes
        if stable:
            break

    per_graph: list[list[int]] = []
    for gi, g in enumerate(graphs):
        base = offsets[gi]
        per_graph.append([classes[base + j] for j in range(len(g))])
    return per_graph, used


def canonicalize(
    graphs: TypeGraph | tuple[TypeGraph, ...] | list[TypeGraph],
    *,
    roots: int | tuple[int, ...] | list[int] | None = None,
    budget: int = DEFAULT_CANONICAL_BUDGET,
) -> Canonicalization:
    """把一张或多张类型图整理为一张共享的规范化类型图。

    :param graphs: 单张 TypeGraph，或其 tuple/list（至少 1 张）。
    :param roots: 可选的逐图根覆盖：单图时可给严格 int，多图时给与图数等长
        的序列；缺省使用每张图自身的 root。
    :param budget: 签名计算次数上限（正的严格 int，非 bool）。
    :returns: Canonicalization（共享图 + 逐节点对应 + 根对应）。
    :raises TypeError/ValueError: 参数种类或取值非法。
    :raises GraphSizeError: 合并后的语义类数超过 MAX_NODES。
    :raises BudgetExceededError: 预算在分区收敛前耗尽（结果未知）。
    """
    single = isinstance(graphs, TypeGraph)
    if single:
        graph_tuple: tuple[TypeGraph, ...] = (graphs,)  # type: ignore[arg-type]
    elif (
        isinstance(graphs, (tuple, list))
        and len(graphs) >= 1
        and all(isinstance(x, TypeGraph) for x in graphs)
    ):
        graph_tuple = tuple(graphs)
    else:
        raise TypeError(
            "graphs must be a TypeGraph or a non-empty tuple/list of "
            f"TypeGraph (got {type(graphs).__name__})"
        )

    if type(budget) is not int:
        kind = "bool" if isinstance(budget, bool) else type(budget).__name__
        raise TypeError(f"budget must be a strict int (got {kind})")
    if budget <= 0:
        raise ValueError(f"budget must be a positive int (got {budget})")

    if roots is None:
        root_tuple = tuple(g.root for g in graph_tuple)
    elif single:
        root_tuple = (_check_root(roots, graph_tuple[0], "roots"),)
    elif isinstance(roots, (tuple, list)) and len(roots) == len(graph_tuple):
        root_tuple = tuple(
            _check_root(r, g, f"roots[{i}]")
            for i, (r, g) in enumerate(zip(roots, graph_tuple))
        )
    else:
        raise ValueError(
            "roots must match the number of input graphs "
            f"({len(roots) if isinstance(roots, (tuple, list)) else 'n/a'} "
            f"given, {len(graph_tuple)} graphs)"
        )

    per_graph, _used = _refine_partition(graph_tuple, budget)

    # 确定性的规范化编号：每个语义类以其成员中最小的 (图序, 节点序) 为代表，
    # 按代表排序赋予 0..k-1。这样无论遍历顺序如何，结果都稳定。
    class_rep: dict[int, tuple[int, int]] = {}
    for gi, class_list in enumerate(per_graph):
        for j, c in enumerate(class_list):
            rep = (gi, j)
            if c not in class_rep or rep < class_rep[c]:
                class_rep[c] = rep
    ordered_classes = sorted(class_rep, key=lambda c: class_rep[c])
    remap = {old: new for new, old in enumerate(ordered_classes)}

    mapping: tuple[tuple[int, ...], ...] = tuple(
        tuple(remap[c] for c in class_list) for class_list in per_graph
    )
    canonical_roots = tuple(
        mapping[gi][root_tuple[gi]] for gi in range(len(graph_tuple))
    )
    class_count = len(ordered_classes)
    total_input_nodes = sum(len(g) for g in graph_tuple)

    canonical_nodes: list[Node] = []
    for old_class in ordered_classes:
        gi, j = class_rep[old_class]
        g = graph_tuple[gi]
        node = g[j]
        kind = node.kind
        local_map = mapping[gi]
        if kind in (INT, BOOL):
            canonical_nodes.append(IntNode() if kind == INT else BoolNode())
        elif kind in (PRODUCT, SUM):
            cls = ProductNode if kind == PRODUCT else SumNode
            fields = tuple(
                Field(f.name, local_map[f.target], f.mutable)
                for f in sorted(node.fields, key=lambda f: f.name)
            )
            canonical_nodes.append(cls(fields))
        else:
            assert isinstance(node, FunctionNode)
            canonical_nodes.append(
                FunctionNode(
                    tuple(local_map[p] for p in node.params),
                    local_map[node.result],
                )
            )

    if class_count > MAX_NODES:
        raise GraphSizeError(
            f"canonical graph has {class_count} semantic class(es); "
            f"limit is {MAX_NODES} shared nodes",
            "canonicalize",
        )

    canonical_graph = TypeGraph(canonical_nodes, canonical_roots[0])

    return Canonicalization(
        graph=canonical_graph,
        roots=canonical_roots,
        mapping=mapping,
        class_count=class_count,
        total_input_nodes=total_input_nodes,
    )


def canonical_node_of(
    result: Canonicalization, graph_index: int, node: int
) -> int:
    """便捷查询：第 graph_index 张输入图的 node 对应规范化节点号。"""
    if not isinstance(result, Canonicalization):
        raise TypeError("result must be a Canonicalization")
    if type(graph_index) is not int or type(node) is not int:
        raise TypeError("graph_index and node must be strict ints")
    if not 0 <= graph_index < len(result.mapping):
        raise IndexError(f"graph_index {graph_index} out of range")
    mapping = result.mapping[graph_index]
    if not 0 <= node < len(mapping):
        raise IndexError(f"node {node} out of range for graph {graph_index}")
    return mapping[node]
