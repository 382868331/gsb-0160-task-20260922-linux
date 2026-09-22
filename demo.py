"""固定输入演示：equi-recursive 类型等价检查。

运行：``python demo.py``（数秒内完成，纯标准库，无网络/无随机压力测试）。

演示三部分：
  1. 正常结果：两个自递归“无限列表”类型（节点编号完全不同）被判等价，
     打印关系证书，并用独立验证器复核证书。
  2. 实际分歧：深处标签不同的两个类型，打印 BFS 找到的最短分歧路径。
  3. 异常边界：一张带悬空边的图在构造期被拒绝（DanglingEdgeError），
     对象不会被创建。
"""

from rectypes import (
    DanglingEdgeError,
    TypeGraph,
    check_equivalence,
    verify_certificate,
)


def list_type(prefix: str) -> TypeGraph:
    # L = Sum{Nil: Int, Cons: Product{head: Int, tail: L}}
    return TypeGraph(
        {
            f"{prefix}L": {
                "kind": "Sum",
                "fields": [
                    ("Nil", f"{prefix}unit"),
                    ("Cons", f"{prefix}cell"),
                ],
            },
            f"{prefix}unit": {"kind": "Int"},
            f"{prefix}cell": {
                "kind": "Product",
                "fields": [
                    ("head", f"{prefix}int"),
                    ("tail", f"{prefix}L"),
                ],
            },
            f"{prefix}int": {"kind": "Int"},
        },
        root=f"{prefix}L",
    )


def nested_sum_type(label: str) -> TypeGraph:
    # outer -first-> middle -second-> Sum{label: Int}
    return TypeGraph(
        {
            "outer": {"kind": "Product", "fields": [("first", "middle")]},
            "middle": {"kind": "Product", "fields": [("second", "inner")]},
            "inner": {"kind": "Sum", "fields": [(label, "payload")]},
            "payload": {"kind": "Int"},
        },
        root="outer",
    )


def main() -> None:
    print("=" * 68)
    print("1. 正常结果：自递归无限列表，两套完全不同的节点编号")
    print("=" * 68)
    g1, g2 = list_type("a_"), list_type("b_")
    result = check_equivalence(g1, g2)
    print(result.render())
    assert result.certificate is not None
    verify_certificate(result.certificate, g1, g2)
    print("独立验证器复核证书: 通过 (verify_certificate -> True)")

    print()
    print("=" * 68)
    print("2. 实际分歧：深度 2 处 Sum 标签 Some vs Other")
    print("=" * 68)
    bad = check_equivalence(nested_sum_type("Some"), nested_sum_type("Other"))
    print(bad.render())
    assert not bad.equivalent
    assert bad.divergence.depth == 2

    print()
    print("=" * 68)
    print("3. 异常边界：悬空边在构造期被拒绝")
    print("=" * 68)
    created = None
    try:
        created = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "missing-node")]},
            },
            root="r",
        )
    except DanglingEdgeError as exc:
        print(f"按预期拒绝 TypeGraph 构造: {type(exc).__name__}: {exc}")
    assert created is None, "非法图不应当被创建"
    print("非法图对象未被创建（created is None）")

    print()
    print("演示完成：1 个等价证书、1 条最短分歧、1 次构造期拒绝。")


if __name__ == "__main__":
    main()
