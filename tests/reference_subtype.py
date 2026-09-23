"""独立参考：**无环图**展开为有限树后的结构子类型判据。

与 ``reference_unfold`` 一样，本模块刻意不 import
``recursive_types.subtyping`` / ``recursive_types.equivalence`` 的任何判定
逻辑，只读 ``TypeGraph`` 的节点数据；期望值（展开树、子类型关系、最浅违反
深度）全部在这里独立计算。仅适用于边只指向更小下标（DAG）的无环图。
Alias 节点在参考中同样透明（沿其 target 继续，不产生树节点）。
"""

from __future__ import annotations

from collections import deque

from recursive_types.model import TypeGraph


def _structural(g: TypeGraph, i: int) -> int:
    """沿 Alias 边走到结构节点（参考自己的解析，不调用被测实现）。"""
    seen: set[int] = set()
    while g[i].kind == "Alias":
        if i in seen:
            raise ValueError("alias-only cycle (unguarded graph) in reference")
        seen.add(i)
        i = g[i].target
    return i


def unfold(g: TypeGraph, root: int) -> tuple:
    """完整展开为嵌套元组树（按节点缓存纯值）。

    形状：``("Int",)`` / ``("Bool",)`` /
    ``("Product", (("name", tree), ...))`` /
    ``("Sum", ...)`` / ``("Function", (param_trees, ...), result_tree)``。
    """
    memo: dict[int, tuple] = {}

    def build(raw: int) -> tuple:
        i = _structural(g, raw)
        if i in memo:
            return memo[i]
        node = g[i]
        k = node.kind
        if k in ("Int", "Bool"):
            tree = (k,)
        elif k in ("Product", "Sum"):
            fields = tuple(sorted((f.name, build(f.target)) for f in node.fields))
            tree = (k, fields)
        else:  # Function
            params = tuple(build(p) for p in node.params)
            tree = ("Function", params, build(node.result))
        memo[i] = tree
        return tree

    return build(root)


def reference_subtype(s: tuple, t: tuple) -> bool:
    """有限展开树上的结构子类型判据（与被测算法相互独立）。"""
    if s[0] != t[0]:
        return False
    kind = s[0]
    if kind in ("Int", "Bool"):
        return True
    if kind == "Product":
        fs = dict(s[1])
        ft = dict(t[1])
        # 宽度：超类型要求的字段子类型必须全部具备；成分协变。
        return all(name in fs and reference_subtype(fs[name], ft[name])
                   for name in ft)
    if kind == "Sum":
        fs = dict(s[1])
        ft = dict(t[1])
        # 反向宽度：子类型提供的分支超类型必须都接受；成分协变。
        return all(name in ft and reference_subtype(fs[name], ft[name])
                   for name in fs)
    # Function：参数逆变、返回协变
    ps, pt = s[1], t[1]
    if len(ps) != len(pt):
        return False
    return (all(reference_subtype(pt[j], ps[j]) for j in range(len(ps)))
            and reference_subtype(s[2], t[2]))


def reference_subtype_on_graphs(
    g_sub: TypeGraph, root_sub: int, g_sup: TypeGraph, root_sup: int
) -> bool:
    """无环图参考判据：比较两侧完整展开树。"""
    return reference_subtype(unfold(g_sub, root_sub), unfold(g_sup, root_sup))


# 带极性的义务状态：(g_sub 结构下标, g_sup 结构下标, reversed)。
_State = tuple[int, int, bool]


def _state_obligations(
    g_sub: TypeGraph, g_sup: TypeGraph, state: _State
) -> list[tuple[_State, str]] | None:
    """参考自己的一层义务推导；违反返回 None。

    状态 ``(a, b, rev)``：``a`` 恒为 g_sub 下标、``b`` 恒为 g_sup 下标；
    ``rev=False`` 义务为 g_sub[a] <: g_sup[b]，``True`` 反向。
    """
    a, b, rev = state
    if not rev:
        g_left, i_left = g_sub, _structural(g_sub, a)
        g_right, i_right = g_sup, _structural(g_sup, b)
    else:
        g_left, i_left = g_sup, _structural(g_sup, b)
        g_right, i_right = g_sub, _structural(g_sub, a)
    n_left, n_right = g_left[i_left], g_right[i_right]
    if n_left.kind != n_right.kind:
        return None
    k = n_left.kind

    def to_state(li: int, ri: int, flip: bool) -> _State:
        ac, bc = (li, ri) if not rev else (ri, li)
        return (ac, bc, rev != flip)

    if k in ("Int", "Bool"):
        return []
    if k == "Product":
        fl = {f.name: f.target for f in n_left.fields}
        fr = {f.name: f.target for f in n_right.fields}
        if any(name not in fl for name in fr):
            return None
        return [
            (to_state(_structural(g_left, fl[name]),
                      _structural(g_right, fr[name]), False),
             f"field:{name}")
            for name in sorted(fr)
        ]
    if k == "Sum":
        fl = {f.name: f.target for f in n_left.fields}
        fr = {f.name: f.target for f in n_right.fields}
        if any(name not in fr for name in fl):
            return None
        return [
            (to_state(_structural(g_left, fl[name]),
                      _structural(g_right, fr[name]), False),
             f"field:{name}")
            for name in sorted(fl)
        ]
    # Function
    pl, pr = list(n_left.params), list(n_right.params)
    if len(pl) != len(pr):
        return None
    out: list[tuple[_State, str]] = [
        (to_state(_structural(g_left, pl[j]),
                  _structural(g_right, pr[j]), True),
         f"param:{j}")
        for j in range(len(pl))
    ]
    out.append(
        (to_state(_structural(g_left, n_left.result),
                  _structural(g_right, n_right.result), False),
         "result")
    )
    return out


def shortest_failure_depth(
    g_sub: TypeGraph, root_sub: int, g_sup: TypeGraph, root_sup: int
) -> int | None:
    """独立 BFS：最浅违反深度；子类型成立返回 None。对含环图同样适用
    （最浅违反路径不会重复同一带极性义务，重复即可截短）。"""
    start: _State = (
        _structural(g_sub, root_sub),
        _structural(g_sup, root_sup),
        False,
    )
    seen = {start}
    queue: deque[tuple[_State, int]] = deque([(start, 0)])
    while queue:
        state, depth = queue.popleft()
        obligations = _state_obligations(g_sub, g_sup, state)
        if obligations is None:
            return depth
        for child, _label in obligations:
            if child not in seen:
                seen.add(child)
                queue.append((child, depth + 1))
    return None
