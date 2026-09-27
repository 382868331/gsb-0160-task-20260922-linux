"""固定输入演示：递归类型等价证书 + 最短分歧路径 + 非法输入拒绝。

运行：``python demo.py``（约 8 秒内，纯本地计算，无网络/无第三方依赖）。
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
    SumNode,
    TypeGraph,
    TypeGraphError,
    canonicalize,
    check_equivalence,
    verify_certificate,
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


def demo_canonicalization() -> None:
    section("[4] 正常结果：一组递归类型整理成可共享的规范化表示")

    # 三种写法的同一递归类型 T = μX. Product{a: X, flag: Bool}：
    #  * g1 单环；
    #  * g2 换成互指的两个副本（共享 vs 复制不区分）、字段顺序打乱；
    #  * g3 只把 flag 字段改成可变——可变性不同，禁止与前两者合并。
    # 另放一个无关的 Int 叶子验证跨图共享。
    g1 = TypeGraph(
        [
            ProductNode((Field("a", 0), Field("flag", 1))),  # 0 T
            BoolNode(),                                         # 1
        ],
        root=0,
    )
    g2 = TypeGraph(
        [
            BoolNode(),                                  # 0
            ProductNode((Field("flag", 0), Field("a", 2))),  # 1 副本 b
            ProductNode((Field("a", 1), Field("flag", 0))),  # 2 副本 a
        ],
        root=2,
    )
    g3 = TypeGraph(
        [
            ProductNode((Field("a", 0), Field("flag", 1, True))),
            BoolNode(),
        ],
        root=0,
    )
    g_int = TypeGraph([IntNode()], root=0)

    result = canonicalize((g1, g2, g3, g_int))
    print("输入 4 张图共 8 个节点（含两种 T 写法 + 可变 T + Int）")
    print(result.render())
    print("逐图根的规范化对应:", result.roots)
    print("逐节点对应 mapping:", result.mapping)
    print()
    assert result.roots[0] == result.roots[1], "同构不同写法必须合并"
    assert result.roots[0] != result.roots[2], "可变性不同不得合并"
    # 规范化结果保留可变性。
    mutable_fields = {
        f.name: f.mutable for f in result.graph[result.roots[2]].fields
    }
    assert mutable_fields == {"a": False, "flag": True}

    # 幂等：对整理结果再次整理，节点不再变化，对应为恒等。
    again = canonicalize(result.graph)
    assert again.class_count == result.class_count
    assert tuple(again.mapping[0]) == tuple(range(result.class_count))
    print(
        "再次整理：节点数仍为",
        again.class_count,
        "，对应关系为恒等",
        tuple(again.mapping[0]),
        "（幂等）",
    )
    # 后续比较只看规范化节点号即可，不必再从头协同遍历。
    print(
        "g1 根与 g2 根规范化节点相同 => 直接判定等价，无需再遍历",
        result.roots[0] == result.roots[1],
    )


def main() -> None:
    print("递归类型 equi-recursive 等价检查 —— 固定输入演示")
    demo_equivalence_certificate()
    demo_divergence()
    demo_rejection()
    demo_canonicalization()
    print()
    print(
        "演示完成：1 个等价证书（含独立复核）、1 条最短分歧、2 个构造期"
        "拒绝、1 个共享规范化整理（含可变性与幂等校验）。"
    )


if __name__ == "__main__":
    main()
