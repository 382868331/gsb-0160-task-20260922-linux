"""固定输入演示：等价证书 + 最短分歧 + 结构子类型 + 构造期拒绝。

运行：``python demo.py``（90 秒内，纯本地计算，无网络/无第三方依赖）。
所有示例数据在本文件中确定性构造，无预录结果、无 sleep。
"""

from __future__ import annotations

from recursive_types import (
    BoolNode,
    DanglingEdgeError,
    Divergence,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SubtypeCertificate,
    SubtypeFailure,
    SumNode,
    TypeGraph,
    TypeGraphError,
    AliasNode,
    UnguardedRecursionError,
    check_equivalence,
    check_subtype,
    verify_certificate,
    verify_subtype_certificate,
)


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def demo_equivalence_certificate() -> None:
    section("[1] 正常结果：equi-recursive 等价，给出 bisimulation 证书")

    # 左侧：T = (T -> Int) × Bool，Product 两个字段共享同一自环节点。
    g1 = TypeGraph(
        [
            FunctionNode((0,), 2),   # 0: T -> Int（参数自指）
            ProductNode(             # 1: 根 T
                (Field("f", 0), Field("flag", 3))
            ),
            IntNode(),               # 2
            BoolNode(),              # 3
        ],
        root=1,
    )

    # 右侧：同构但换布局（根在最后、编号重排），自环节点复制成两个互指副本；
    # 字段声明顺序也故意打乱（按名对应，不按位置）。
    g2 = TypeGraph(
        [
            BoolNode(),                                  # 0
            IntNode(),                                   # 1
            FunctionNode((3,), 1),                       # 2: 自环节点副本 a
            FunctionNode((2,), 1),                       # 3: 自环节点副本 b，互指
            ProductNode(                                 # 4: 根
                (Field("flag", 0), Field("f", 2))
            ),
        ],
        root=4,
    )

    result = check_equivalence(g1, g2)
    assert isinstance(result, EquivalenceCertificate)
    print("类型 T = (μX. X -> Int) × Bool 的两种图布局：")
    print("  g1: 4 节点、字段顺序 (f, flag)，根 = 1")
    print("  g2: 5 节点、字段顺序 (flag, f)，根 = 4，自环复制后绕回")
    print()
    print(result.render())
    print()
    ok = verify_certificate(g1, g2, result)
    print(f"verify_certificate 独立逐条复核: {ok}")
    assert ok is True


def demo_divergence() -> None:
    section("[2] 正常结果：不等价，给出最短分歧路径（实际计算）")

    # 深层标签差异：k 层 Product("a") 之后，左 Sum 有标签 y，右为 z。
    k = 5
    left: list = [
        SumNode((Field("x", 1), Field("y", 2))),
        IntNode(),
        BoolNode(),
    ]
    right: list = [
        SumNode((Field("x", 1), Field("z", 2))),
        IntNode(),
        BoolNode(),
    ]
    for t in range(k):
        target1 = 0 if t == 0 else len(left) - 1
        target2 = 0 if t == 0 else len(right) - 1
        left.append(ProductNode((Field("a", target1),)))
        right.append(ProductNode((Field("a", target2),)))
    g1 = TypeGraph(left, len(left) - 1)
    g2 = TypeGraph(right, len(right) - 1)

    result = check_equivalence(g1, g2)
    assert isinstance(result, Divergence)
    print(f"两图均为 {k} 层 Product('a') 包裹的 Sum，仅最深标签 y vs z 不同")
    print(result.render())
    print()
    print(f"分歧深度 depth = {result.depth}（BFS 对图搜索保证最浅）")
    print(f"分歧点: {result.mismatch.reason}")


def demo_rejection() -> None:
    section("[3] 异常边界：构造期拒绝悬空边（可定位错误，不静默纠正）")

    try:
        TypeGraph(
            [
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 9))),  # 9 不存在
            ],
            root=1,
        )
    except DanglingEdgeError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}")
    else:  # pragma: no cover
        raise AssertionError("悬空边必须被拒绝")

    # 同一错误层级也覆盖 bool 冒充整数编号。
    try:
        TypeGraph([IntNode(), ProductNode((Field("a", True),))], root=1)
    except TypeGraphError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}")
    else:  # pragma: no cover
        raise AssertionError("bool 编号必须被拒绝")


def demo_subtype_success() -> None:
    section("[4] 正常结果：结构子类型成立（宽度 + 只读协变 + 函数逆变）")

    # 子类型 A = (N) -> R_sub，超类型 B = (W) -> R_sup，其中：
    #   W = {a:Int, extra:Bool}  <:  N = {a:Int}          （宽度 + 只读协变）
    #   R_sub = {ok:W}           <:  R_sup = {ok:N}       （只读字段协变）
    # 函数参数逆变要求 B 的参数 W <: A 的参数 N —— 成立；结果协变也成立。
    # 节点布局：0=Int 1=Bool 2=W 3=N 4=R_sub 5=R_sup 6=A(root) 7=B
    g_sub = TypeGraph(
        [
            IntNode(),                                              # 0
            BoolNode(),                                             # 1
            ProductNode((Field("a", 0), Field("extra", 1))),        # 2 W
            ProductNode((Field("a", 0),)),                          # 3 N
            ProductNode((Field("ok", 2),)),                         # 4 R_sub
            FunctionNode((3,), 4),                                  # 5 A(root)
        ],
        5,
    )
    g_sup = TypeGraph(
        [
            IntNode(),                                              # 0
            BoolNode(),                                             # 1
            ProductNode((Field("a", 0), Field("extra", 1))),        # 2 W
            ProductNode((Field("a", 0),)),                          # 3 N
            ProductNode((Field("ok", 3),)),                         # 5 R_sup
            FunctionNode((2,), 4),                                  # 根 B
        ],
        5,
    )
    result = check_subtype(g_sub, g_sup)
    assert isinstance(result, SubtypeCertificate)
    print("A = (N={a}) -> {ok: W={a,extra}}")
    print("B = (W={a,extra}) -> {ok: N={a}}")
    print("判 A <: B：函数参数逆变（W <: N）、结果协变（{ok:W} <: {ok:N}）")
    print()
    print(result.render())
    print()
    ok = verify_subtype_certificate(g_sub, g_sup, result)
    print(f"verify_subtype_certificate 独立逐条复核: {ok}")
    assert ok is True
    # 反向不成立：宽度规则在根函数的参数位置被违反。
    back = check_subtype(g_sup, g_sub)
    assert isinstance(back, SubtypeFailure)
    print("反向 B <: A 不成立，失败定位：", back.render())


def demo_subtype_failure_and_mutability() -> None:
    section("[5] 边界：可写字段不变 + 可定位类型路径")

    # 超类型 {pos: rw {x:Int}}；子类型 {pos: rw {x:Int, y:Bool}}。
    # pos 可写 => 不变：即使多出字段也不允许协变，失败路径 field(pos)。
    g_sup = TypeGraph(
        [
            IntNode(),
            ProductNode((Field("x", 0),)),                       # 1
            ProductNode((Field("pos", 1, readonly=False),)),     # 2 root
        ],
        2,
    )
    g_sub = TypeGraph(
        [
            IntNode(),
            BoolNode(),
            ProductNode((Field("x", 0), Field("y", 1))),         # 2 更宽
            ProductNode((Field("pos", 2, readonly=False),)),     # 3 root
        ],
        3,
    )
    result = check_subtype(g_sub, g_sup)
    assert isinstance(result, SubtypeFailure)
    print("可写槽位要求不变：子类型字段即使“更宽”也不接受协变")
    print(result.render())
    print()
    # 对照：同一结构把 pos 改成只读后，宽度协变立即成立。
    g_sub_ro = TypeGraph(
        [
            IntNode(),
            BoolNode(),
            ProductNode((Field("x", 0), Field("y", 1))),
            ProductNode((Field("pos", 2),)),                     # 只读
        ],
        3,
    )
    g_sup_ro = TypeGraph(
        [
            IntNode(),
            ProductNode((Field("x", 0),)),
            ProductNode((Field("pos", 1),)),
        ],
        2,
    )
    ok_result = check_subtype(g_sub_ro, g_sup_ro)
    assert isinstance(ok_result, SubtypeCertificate)
    print("对照：pos 改为只读后成立 =>", ok_result.render())


def demo_unguarded_recursion_rejected() -> None:
    section("[6] 实际错误：无保护递归 μX.X 构图期拒绝（给环路径）")

    # node1 -> node2 -> node1：环上只有透明 Alias，没有任何构造子保护。
    try:
        TypeGraph(
            [
                IntNode(),          # 0（与环无关也要整图拒绝）
                AliasNode(2),       # 1
                AliasNode(1),       # 2
            ],
            root=0,
        )
    except UnguardedRecursionError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}")
    else:  # pragma: no cover
        raise AssertionError("无保护递归必须被拒绝")

    # 对照：回边经过 Product 构造子即为受保护递归，正常接受并参与子类型判定。
    g = TypeGraph(
        [
            IntNode(),                                  # 0
            ProductNode((Field("a", 2), Field("b", 0))),  # 1
            AliasNode(1),                               # 2 root（透明）
        ],
        root=2,
    )
    g_plain = TypeGraph(
        [IntNode(), ProductNode((Field("a", 1), Field("b", 0)))], 1
    )
    result = check_subtype(g, g_plain)
    assert isinstance(result, SubtypeCertificate)
    print("对照：Alias 指向受保护 Product 环，透明穿透后子类型成立：")
    print(" ", result.render())


def main() -> None:
    print("递归类型等价检查 + 结构子类型判断 —— 固定输入演示")
    demo_equivalence_certificate()
    demo_divergence()
    demo_rejection()
    demo_subtype_success()
    demo_subtype_failure_and_mutability()
    demo_unguarded_recursion_rejected()
    print()
    print(
        "演示完成：等价证书、最短分歧、2 个构造期拒绝、"
        "子类型成功证书（含独立复核）、可写不变失败路径、无保护递归拒绝。"
    )


if __name__ == "__main__":
    main()
