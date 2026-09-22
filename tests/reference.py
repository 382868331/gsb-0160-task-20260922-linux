"""独立参考实现：无环类型图的有限树展开。

任务约定“把无环图展开作参考”。无环图从根展开得到一棵**有限树**，
直接用嵌套元组表示并做结构相等即可。该模块刻意不导入
:mod:`rectypes.checker`，只复用 :class:`rectypes.model.TypeGraph`
这一数据结构，期望值完全独立计算。

展开表示（字段名进入结构，顺序差异用 frozenset 消除）：

* ``Int``      -> ``("Int",)``
* ``Bool``     -> ``("Bool",)``
* ``Product`` -> ``("Product", frozenset({(名, 子展开), ...}))``
* ``Sum``      -> ``("Sum", frozenset({(名, 子展开), ...}))``
* ``Function`` -> ``("Function", (参数展开, ...), 返回展开)``

对带环图本参考不适用（调用方只在无环图上使用）。
"""

from __future__ import annotations

from rectypes.model import TypeGraph


class CyclicGraphError(ValueError):
    """参考实现只接受无环图。"""


def expand_acyclic(graph: TypeGraph) -> tuple:
    """把无环图从根展开为嵌套元组有限树。"""

    memo: dict[object, tuple] = {}
    visiting: set[object] = set()

    def go(ident: object) -> tuple:
        if ident in memo:
            return memo[ident]
        if ident in visiting:  # 防御：参考只应处理无环图
            raise CyclicGraphError(f"cycle through node {ident!r}")
        visiting.add(ident)
        node = graph.nodes[ident]
        kind = node["kind"]
        if kind == "Int":
            value: tuple = ("Int",)
        elif kind == "Bool":
            value = ("Bool",)
        elif kind in ("Product", "Sum"):
            value = (
                kind,
                frozenset((name, go(target)) for name, target in node["fields"]),
            )
        else:
            value = (
                "Function",
                tuple(go(p) for p in node["params"]),
                go(node["result"]),
            )
        visiting.discard(ident)
        memo[ident] = value
        return value

    return go(graph.root)


def reference_equal(g1: TypeGraph, g2: TypeGraph) -> bool:
    """参考判定：两棵有限展开树结构相等。"""
    return expand_acyclic(g1) == expand_acyclic(g2)


def _head_ok(t1: tuple, t2: tuple) -> bool:
    """有限树上的头条件，独立于 checker 重新书写。"""
    if t1[0] != t2[0]:
        return False
    kind = t1[0]
    if kind in ("Product", "Sum"):
        return {name for name, _ in t1[1]} == {name for name, _ in t2[1]}
    if kind == "Function":
        return len(t1[1]) == len(t2[1])
    return True


def _children(t1: tuple, t2: tuple) -> list[tuple[tuple, tuple]]:
    kind = t1[0]
    if kind in ("Product", "Sum"):
        m1 = dict(t1[1])
        m2 = dict(t2[1])
        return [(m1[name], m2[name]) for name in sorted(m1)]
    if kind == "Function":
        return list(zip(t1[1], t2[1])) + [(t1[2], t2[2])]
    return []


def shortest_divergence_depth(g1: TypeGraph, g2: TypeGraph) -> int | None:
    """在有限展开树上独立 BFS：等价返回 ``None``，否则返回最浅冲突深度。

    有限树无环，直接在展开表示上按层配对即可，不做任何循环闭合。
    """
    t1, t2 = expand_acyclic(g1), expand_acyclic(g2)
    if _head_ok(t1, t2):
        pass
    else:
        return 0
    current = [(t1, t2)]
    depth = 0
    while current:
        nxt: list[tuple[tuple, tuple]] = []
        for a, b in current:
            for c1, c2 in _children(a, b):
                if not _head_ok(c1, c2):
                    return depth + 1
                nxt.append((c1, c2))
        current = nxt
        depth += 1
    return None
