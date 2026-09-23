"""受保护递归（contractiveness）校验与 Alias 透明性的测试。

所有非法用例的期望均按定义手工给出：无保护环 = 从根可达且环上每条边都是
Alias；含任一结构构造子的环即受保护。
"""

from __future__ import annotations

import unittest

from recursive_types import (
    AliasNode,
    BoolNode,
    DanglingEdgeError,
    Divergence,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    InvalidNodeError,
    ProductNode,
    SumNode,
    TypeGraph,
    UnguardedRecursionError,
    are_equivalent,
    check_equivalence,
    verify_certificate,
)


class GuardedRecursionTests(unittest.TestCase):
    def test_direct_self_alias_rejected(self) -> None:
        # μX. X：根节点直接 Alias 自指。
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph([AliasNode(0)], 0)
        msg = str(cm.exception)
        self.assertIn("node 0", msg)
        self.assertIn("alias-only cycle", msg)

    def test_alias_chain_cycle_rejected(self) -> None:
        # μX. 链回自己：0 -> 1 -> 2 -> 0，全是 Alias。
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph([AliasNode(1), AliasNode(2), AliasNode(0)], 0)
        msg = str(cm.exception)
        # 环序列把三个节点都点出来（顺序从回边目标开始），便于定位。
        for i in (0, 1, 2):
            self.assertIn(f"node {i}", msg)

    def test_cycle_message_locates_suffix_cycle(self) -> None:
        # 0 -> 1 -> 2 -> 1：前缀 0 不在环上，消息应定位后缀环 1 -> 2 -> 1。
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph([AliasNode(1), AliasNode(2), AliasNode(1)], 0)
        msg = str(cm.exception)
        self.assertIn("node 1 -> node 2 -> node 1", msg)
        self.assertNotIn("node 0 -> node 1 -> node 2 -> node 1", msg)

    def test_unguarded_cycle_reachable_through_alias_chain(self) -> None:
        # 根 3(alias) -> 0(alias) -> 1(alias) -> 0：可达的纯 alias 环，拒绝。
        with self.assertRaises(UnguardedRecursionError):
            TypeGraph(
                [AliasNode(1), AliasNode(0), IntNode(), AliasNode(0)], 3
            )

    def test_alias_only_cycle_behind_field_is_still_rejected(self) -> None:
        # 0=Product{a:1}, 1=Alias(1)：守卫必须在*环上*。字段 a 的类型
        # 本身是 μX.X（展开无任何构造子），整棵树仍无定义，必须拒绝。
        with self.assertRaises(UnguardedRecursionError):
            TypeGraph(
                [ProductNode((Field("a", 1),)), AliasNode(1)], 0
            )

    def test_alias_pointing_into_guarded_cycle_is_fine(self) -> None:
        # 边界：0=Product{a:1}, 1=Alias(0)。环 0->1->0 含 Product 构造子，
        # 无限树为 Product{a: Product{a: ...}}，合法。
        g = TypeGraph(
            [ProductNode((Field("a", 1),)), AliasNode(0)], 0
        )
        target = TypeGraph([ProductNode((Field("a", 0),))], 0)
        self.assertTrue(are_equivalent(g, target))

    def test_function_guards_self_reference(self) -> None:
        # μX. X -> Int：函数构造子守卫，合法（旧行为继续可用）。
        g = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        self.assertTrue(are_equivalent(g, g))

    def test_product_guards_self_reference(self) -> None:
        g = TypeGraph([ProductNode((Field("a", 0),))], 0)
        self.assertTrue(are_equivalent(g, g))

    def test_sum_guards_self_reference(self) -> None:
        g = TypeGraph([SumNode((Field("x", 0),))], 0)
        self.assertTrue(are_equivalent(g, g))

    def test_alias_indirection_before_guarded_cycle(self) -> None:
        # 根 Alias(2) -> μX.Product{a: X}（节点 2 自指环）：透明合法。
        g = TypeGraph(
            [IntNode(), IntNode(),
             ProductNode((Field("a", 2),)), AliasNode(2)],
            3,
        )
        target = TypeGraph([ProductNode((Field("a", 0),))], 0)
        result = check_equivalence(g, target)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g, target, result))

    def test_mutual_recursion_via_aliases_equivalent(self) -> None:
        # T = Product{a: U}；U = Bool 之外 T 的别名——用显式 Alias 表达：
        # 0=Product{a: 2}, 1=Bool, 2=Alias(0) => T 的 a 字段绕回 T，
        # 与直接自指 μX.Product{a:X} 等价。
        g = TypeGraph(
            [ProductNode((Field("a", 2),)), BoolNode(), AliasNode(0)], 0
        )
        target = TypeGraph([ProductNode((Field("a", 0),))], 0)
        result = check_equivalence(g, target)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g, target, result))

    def test_unguarded_cycle_unreachable_from_root_allowed(self) -> None:
        # 不可达部分存在 μX.X 不影响根类型的树；根是 Int。
        g = TypeGraph([IntNode(), AliasNode(1)], 0)
        self.assertEqual(g.root, 0)
        # 根类型仍是 Int。
        other = TypeGraph([IntNode()], 0)
        self.assertTrue(are_equivalent(g, other))

    def test_changing_root_to_reach_bad_cycle_rejects(self) -> None:
        # 同一组节点：根=0(Int) 合法，根=1(μX.X) 必须在构造期拒绝——
        # 不允许“构造半个图”的灰色状态。
        TypeGraph([IntNode(), AliasNode(1)], 0)
        with self.assertRaises(UnguardedRecursionError):
            TypeGraph([IntNode(), AliasNode(1)], 1)

    def test_error_is_rec_type_error_and_type_graph_error(self) -> None:
        from recursive_types import RecTypeError, TypeGraphError

        with self.assertRaises(RecTypeError):
            TypeGraph([AliasNode(0)], 0)
        with self.assertRaises(TypeGraphError):
            TypeGraph([AliasNode(0)], 0)

    def test_alias_target_dangling_rejected(self) -> None:
        with self.assertRaises(DanglingEdgeError) as cm:
            TypeGraph([IntNode(), AliasNode(7)], 1)
        self.assertIn("node 1", str(cm.exception))
        self.assertIn("Alias target", str(cm.exception))

    def test_alias_target_bool_rejected(self) -> None:
        with self.assertRaises(InvalidNodeError):
            TypeGraph([IntNode(), AliasNode(True)], 1)  # type: ignore[arg-type]


class AliasEquivalenceTests(unittest.TestCase):
    def test_alias_chain_transparent(self) -> None:
        # 根 Alias(2)->Alias(1)? 构造: 0=Int,1=Alias(0),2=Alias(1)，根 2。
        g = TypeGraph([IntNode(), AliasNode(0), AliasNode(1)], 2)
        plain = TypeGraph([IntNode()], 0)
        self.assertTrue(are_equivalent(g, plain))

    def test_alias_wrapped_recursive_type_equivalent(self) -> None:
        # μX. X -> Int 的别名包裹写法 vs 直接自环写法。
        g_alias = TypeGraph(
            [FunctionNode((2,), 1), IntNode(), AliasNode(0)], 2
        )
        g_direct = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        result = check_equivalence(g_alias, g_direct)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g_alias, g_direct, result))

    def test_alias_does_not_mask_a_mismatch(self) -> None:
        # 左根 alias 链到 Int，右根 alias 到 Bool：仍在 depth 0 分歧。
        g1 = TypeGraph([IntNode(), BoolNode(), AliasNode(0)], 2)
        g2 = TypeGraph([IntNode(), BoolNode(), AliasNode(1)], 2)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 0)

    def test_deep_alias_path_does_not_count_as_structure(self) -> None:
        # 10 层 Alias 之后接 Product 链；Alias 不应出现在分歧深度里。
        k = 3
        g1_nodes = [
            SumNode((Field("x", 1), Field("y", 2))),
            IntNode(),
            BoolNode(),
        ]
        g2_nodes = [
            SumNode((Field("x", 1), Field("z", 2))),
            IntNode(),
            BoolNode(),
        ]
        for t in range(k):
            t1 = 0 if t == 0 else len(g1_nodes) - 1
            t2 = 0 if t == 0 else len(g2_nodes) - 1
            g1_nodes.append(ProductNode((Field("a", t1),)))
            g2_nodes.append(ProductNode((Field("a", t2),)))
        # 根前再各加两层纯 Alias（合法：后接结构守卫）。
        root1 = len(g1_nodes)
        g1_nodes.append(AliasNode(root1 - 1))
        g1_nodes.append(AliasNode(root1))
        root2 = len(g2_nodes)
        g2_nodes.append(AliasNode(root2 - 1))
        g2_nodes.append(AliasNode(root2))
        g1 = TypeGraph(g1_nodes, len(g1_nodes) - 1)
        g2 = TypeGraph(g2_nodes, len(g2_nodes) - 1)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, k)  # Alias 层不计深度


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
