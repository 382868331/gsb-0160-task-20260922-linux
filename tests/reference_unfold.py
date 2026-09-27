"""独立参考实现：把**无环图**完整展开为有限树后逐结构比较。

本模块刻意不 import ``recursive_types.equivalence`` 的任何判定逻辑，
只用其数据结构读取输入；期望值（展开树）由这里独立计算。
仅适用于边只指向更大下标（DAG）的无环图。
"""

from __future__ import annotations

from recursive_types.model import TypeGraph


def unfold(g: TypeGraph, root: int) -> tuple:
    """完整展开为嵌套元组树（按节点缓存纯值，不涉及任何等价算法）。"""
    memo: dict[int, tuple] = {}

    def build(i: int) -> tuple:
        if i in memo:
            return memo[i]
        node = g[i]
        k = node.kind
        if k in ("Int", "Bool"):
            tree = (k,)
        elif k in ("Product", "Sum"):
            fields = tuple(
                sorted(
                    ((f.name, f.mutable, build(f.target)) for f in node.fields),
                    key=lambda item: item[0],
                )
            )
            tree = (k, fields)
        else:  # Function
            params = tuple(build(p) for p in node.params)
            tree = ("Function", params, build(node.result))
        memo[i] = tree
        return tree

    return build(root)


def reference_equivalent(
    g1: TypeGraph, root1: int, g2: TypeGraph, root2: int
) -> bool:
    """无环图参考判据：无限展开树在无环时就是有限树，直接比树。"""
    return unfold(g1, root1) == unfold(g2, root2)


def reference_pair_children(
    g1: TypeGraph, i: int, g2: TypeGraph, j: int
) -> list[tuple[int, int]] | None:
    """独立的一层匹配：匹配返回子对列表，否则 None。"""
    n1, n2 = g1[i], g2[j]
    if n1.kind != n2.kind:
        return None
    if n1.kind in ("Int", "Bool"):
        return []
    if n1.kind in ("Product", "Sum"):
        f1 = sorted(n1.fields, key=lambda f: f.name)
        f2 = sorted(n2.fields, key=lambda f: f.name)
        if [(f.name, f.mutable) for f in f1] != [
            (f.name, f.mutable) for f in f2
        ]:
            return None
        return [(a.target, b.target) for a, b in zip(f1, f2)]
    # Function
    p1, p2 = list(n1.params), list(n2.params)
    if len(p1) != len(p2):
        return None
    return list(zip(p1, p2)) + [(n1.result, n2.result)]


def shortest_divergence_depth(
    g1: TypeGraph, root1: int, g2: TypeGraph, root2: int
) -> int | None:
    """独立 BFS：返回最浅结构分歧的深度；等价返回 None。

    在对图上按深度去重 BFS。最短分歧路径不可能重复同一节点对
    （重复则沿环可截取得更短），故对一般（含环）图同样成立。
    """
    from collections import deque

    start = (root1, root2)
    seen = {start}
    queue = deque([(start, 0)])
    while queue:
        (x, y), depth = queue.popleft()
        children = reference_pair_children(g1, x, g2, y)
        if children is None:
            return depth
        for pair in children:
            if pair not in seen:
                seen.add(pair)
                queue.append((pair, depth + 1))
    return None
