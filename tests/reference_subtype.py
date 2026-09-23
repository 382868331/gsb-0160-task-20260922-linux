"""独立参考：无环图（含透明 Alias）的结构子类型判据。

本模块刻意不 import ``recursive_types.subtyping`` 的任何判定逻辑，
只读 ``recursive_types.model`` 的数据结构；期望值由这里独立计算。
规则直接按题面手写：

* Product 宽度：超类型字段 ⊆ 子类型字段；
* 超类型只读字段 => 负载协变；超类型可写字段 => 子侧可写且负载相等（不变）；
* Sum 标签集精确相等、负载协变；
* Function 参数逆变、结果协变、元数相等；叶子同种类。

仅适用于边只指向更小下标（DAG）的无环图；Alias 被透明展开。
"""

from __future__ import annotations

from recursive_types.model import TypeGraph

# 展开值形态：
#   Int  -> ("Int",)
#   Bool -> ("Bool",)
#   Product/Sum -> (kind, frozenset((name, readonly, 子值)))
#   Function -> ("Function", tuple(参数值), 结果值)


def expand(g: TypeGraph, root: int) -> tuple:
    memo: dict[int, tuple] = {}

    def build(i: int) -> tuple:
        if i in memo:
            return memo[i]
        node = g[i]
        k = node.kind
        if k in ("Int", "Bool"):
            tree = (k,)
        elif k == "Alias":
            tree = build(node.target)
        elif k in ("Product", "Sum"):
            tree = (
                k,
                frozenset(
                    (f.name, f.readonly, build(f.target)) for f in node.fields
                ),
            )
        else:  # Function
            tree = (
                "Function",
                tuple(build(p) for p in node.params),
                build(node.result),
            )
        memo[i] = tree
        return tree

    return build(root)


def reference_subtype(t1: tuple, t2: tuple) -> bool:
    """t1 <: t2 是否成立（对展开值直接递归；无环故终止）。"""
    k1, k2 = t1[0], t2[0]
    if k1 != k2:
        return False
    if k1 in ("Int", "Bool"):
        return True
    if k1 == "Product":
        f1 = {name: (ro, ty) for name, ro, ty in t1[1]}
        f2 = {name: (ro, ty) for name, ro, ty in t2[1]}
        for name, (ro_super, ty_super) in f2.items():
            if name not in f1:
                return False  # 宽度违反
            ro_sub, ty_sub = f1[name]
            if ro_super:
                if not reference_subtype(ty_sub, ty_super):
                    return False  # 只读协变
            else:
                if ro_sub or ty_sub != ty_super:
                    return False  # 可写不变（子侧必须可写且类型相等）
        return True
    if k1 == "Sum":
        f1 = {name: ty for name, _ro, ty in t1[1]}
        f2 = {name: ty for name, _ro, ty in t2[1]}
        if set(f1) != set(f2):
            return False  # Sum 不开宽度
        return all(reference_subtype(f1[name], f2[name]) for name in f2)
    # Function：参数逆变、结果协变
    _k, params1, result1 = t1
    _k2, params2, result2 = t2
    if len(params1) != len(params2):
        return False
    if not all(reference_subtype(p2, p1) for p1, p2 in zip(params1, params2)):
        return False
    return reference_subtype(result1, result2)


def reference_equivalent(t1: tuple, t2: tuple) -> bool:
    """无环图结构相等（展开值直接比较；Alias 已透传）。"""
    return t1 == t2
