"""固定输入演示：等价证书 + 最短分歧 + 结构子类型（含逆变递归）+ 非法输入拒绝。

运行：``python demo.py``（90 秒内，纯本地计算，无网络/无第三方依赖）。
所有示例数据在本文件中确定性构造，无预录结果、无 sleep。
各节的“手算预期”写在注释里，程序对实际计算结果做 assert 核对。
"""

from __future__ import annotations

from recursive_types import (
    AliasNode,
    BoolNode,
    DanglingEdgeError,
    Divergence,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SubtypeFailure,
    SubtypingCertificate,
    SumNode,
    TypeGraph,
    TypeGraphError,
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


def demo_subtype_success() -> None:
    section("[3] 正常结果：结构子类型成立（宽度 + 协变 + 参数逆变 + 协递归）")

    # 手算例：
    #   Rw = {a: Int, b: Bool}      Rn = {a: Int}
    #   Fn = (Rn) -> Int            Fw = (Rw) -> Int
    # 逆变标准方向：Fn <: Fw（实现只要求 {a}，调用方给足 {a,b} 也安全）。
    g_narrow = TypeGraph(   # Fn = (Rn) -> Int
        [
            IntNode(),                                  # 0
            ProductNode((Field("a", 0),)),              # 1 Rn
            FunctionNode((1,), 0),                      # 2 根
        ],
        root=2,
    )
    g_wide = TypeGraph(     # Fw = (Rw) -> Int
        [
            IntNode(),                                  # 0
            BoolNode(),                                 # 1
            ProductNode((Field("a", 0), Field("b", 1))),  # 2 Rw
            FunctionNode((2,), 0),                      # 3 根
        ],
        root=3,
    )
    result = check_subtype(g_narrow, g_wide)
    assert isinstance(result, SubtypingCertificate)
    print("Fn = ({a: Int}) -> Int    Fw = ({a: Int, b: Bool}) -> Int")
    print("检查 Fn <: Fw：参数逆变（需要 Rw <: Rn，宽度成立），返回 Int~Int")
    print()
    print(result.render())
    print()
    ok = verify_subtype_certificate(g_narrow, g_wide, result)
    print(f"verify_subtype_certificate 独立逐条复核: {ok}")
    assert ok is True

    # 协递归 + 宽度：S = μX.{a: X, b: Int} <: T = μY.{a: Y}。
    g_s = TypeGraph(
        [IntNode(),
         ProductNode((Field("a", 1), Field("b", 0)))],
        root=1,
    )
    g_t = TypeGraph([ProductNode((Field("a", 0),))], root=0)
    result2 = check_subtype(g_s, g_t)
    assert isinstance(result2, SubtypingCertificate)
    print()
    print("递归宽度：μX.{a:X, b:Int} <: μY.{a:Y}（超类型不要 b，a 位回到协递归假设）")
    print(result2.render())


def demo_subtype_failure() -> None:
    section("[4] 边界与失败：逆变递归导致的子类型不成立，给出最浅类型路径")

    # 手算经典反例（沿对图走两步即可推出矛盾）：
    #   S = μX. X -> Rw， T = μY. Y -> Rn， Rw={a,b} 宽、Rn={a} 窄。
    # S <: T 在根处要求参数位 T <: S（逆变），其返回位又要求 Rn <: Rw，
    # 但 Rn 缺字段 b —— 最浅违反 depth 2：param(0) -> result。
    g_s = TypeGraph(   # S
        [
            IntNode(),                                        # 0
            BoolNode(),                                       # 1
            ProductNode((Field("a", 0), Field("b", 1))),      # 2 Rw
            FunctionNode((3,), 2),                           # 3 根，参数自指
        ],
        root=3,
    )
    g_t = TypeGraph(   # T
        [
            IntNode(),                                  # 0
            ProductNode((Field("a", 0),)),              # 1 Rn
            FunctionNode((2,), 1),                      # 2 根，参数自指
        ],
        root=2,
    )
    result = check_subtype(g_s, g_t)
    assert isinstance(result, SubtypeFailure)
    print("S = μX. X -> {a,b}   T = μY. Y -> {a}，检查 S <: T")
    print(result.render())
    print()
    print(f"违反深度 depth = {result.depth}（BFS 对图搜索保证最浅）")
    print(f"违反点: {result.mismatch.reason} | {result.mismatch.left}")
    assert result.depth == 2
    assert [s.render() for s in result.path] == ["param(0)", "result"]

    # 简单宽度边界：{a:Int} 不是 {a:Int,b:Bool} 的子类型，根处即缺 b。
    g_narrow_rec = TypeGraph(
        [IntNode(), ProductNode((Field("a", 0),))], root=1
    )
    g_wide_rec = TypeGraph(
        [IntNode(), BoolNode(),
         ProductNode((Field("a", 0), Field("b", 1)))],
        root=2,
    )
    width_fail = check_subtype(g_narrow_rec, g_wide_rec)
    assert isinstance(width_fail, SubtypeFailure) and width_fail.depth == 0
    print()
    print("宽度边界：{a:Int} </: {a:Int,b:Bool} ->", width_fail.mismatch.left)


def demo_rejections() -> None:
    section("[5] 实际错误：无保护递归 μX.X 与悬空边在构造期被拒绝")

    # 无保护递归：根节点是指向自己的纯 Alias 边（μX. X），展开无树。
    try:
        TypeGraph([AliasNode(0)], root=0)
    except UnguardedRecursionError as exc:
        print(f"捕获 {type(exc).__name__}")
        print(f"  {exc}")
    else:  # pragma: no cover
        raise AssertionError("μX.X 必须被拒绝")

    # 多节点纯 Alias 环同样拒绝，错误消息把环上节点序列点出来。
    try:
        TypeGraph(
            [
                AliasNode(1),
                AliasNode(2),
                AliasNode(0),
            ],
            root=0,
        )
    except UnguardedRecursionError as exc:
        print(f"捕获 {type(exc).__name__}（多节点环）")
        print(f"  {exc}")
    else:  # pragma: no cover
        raise AssertionError("纯 Alias 多节点环必须被拒绝")

    # 悬空边（旧的构造期校验继续生效）。
    try:
        TypeGraph(
            [
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 9))),  # 9 不存在
            ],
            root=1,
        )
    except DanglingEdgeError as exc:
        print(f"捕获 {type(exc).__name__}")
        print(f"  {exc}")
    else:  # pragma: no cover
        raise AssertionError("悬空边必须被拒绝")

    # bool 冒充整数编号也继续被同一错误层级拒绝。
    try:
        TypeGraph([IntNode(), ProductNode((Field("a", True),))], root=1)
    except TypeGraphError as exc:
        print(f"捕获 {type(exc).__name__}")
        print(f"  {exc}")
    else:  # pragma: no cover
        raise AssertionError("bool 编号必须被拒绝")


def main() -> None:
    print("递归类型判定 —— 等价检查 + 结构子类型 + 受保护递归（固定输入演示）")
    demo_equivalence_certificate()
    demo_divergence()
    demo_subtype_success()
    demo_subtype_failure()
    demo_rejections()
    print()
    print(
        "演示完成：1 个等价证书、1 条最短分歧、2 个子类型结论（成立/不成立）、"
        "4 个构造期拒绝。"
    )


if __name__ == "__main__":
    main()
