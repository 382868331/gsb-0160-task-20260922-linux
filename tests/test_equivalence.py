"""equi-recursive 等价检查的核心测试。

期望值来源：
* 无环图一律与独立参考 ``reference_unfold``（完整展开树 / 独立 BFS 深度）交叉验证，
  该参考不 import 被测的判定算法；
* 递归（含环）用例为手工固定构造并给出显式断言。
"""

from __future__ import annotations

import random
import unittest

from recursive_types import (
    BoolNode,
    BudgetExceededError,
    Divergence,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SumNode,
    TypeGraph,
    are_equivalent,
    check_equivalence,
    verify_certificate,
)
from recursive_types.model import Node

from tests.reference_unfold import (
    reference_equivalent,
    shortest_divergence_depth,
    unfold,
)

FIELD_POOL = ("a", "b", "c", "d", "e")
SUM_POOL = ("x", "y", "z", "w")


def random_dag(rng: random.Random, n: int) -> list[Node]:
    """确定性生成 n 节点无环图：所有边只指向更小下标。"""
    nodes: list[Node] = [IntNode()]
    for i in range(1, n):
        choice = rng.random()
        if choice < 0.3:
            nodes.append(IntNode() if rng.random() < 0.5 else BoolNode())
        elif choice < 0.65:
            count = rng.randint(1, min(3, len(FIELD_POOL)))
            names = rng.sample(FIELD_POOL, count)
            fields = tuple(
                Field(name, rng.randrange(i)) for name in names
            )
            nodes.append(ProductNode(fields))
        elif choice < 0.85:
            count = rng.randint(1, min(2, len(SUM_POOL)))
            names = rng.sample(SUM_POOL, count)
            fields = tuple(
                Field(name, rng.randrange(i)) for name in names
            )
            nodes.append(SumNode(fields))
        else:
            argc = rng.randint(1, 2)
            params = tuple(rng.randrange(i) for _ in range(argc))
            nodes.append(FunctionNode(params, rng.randrange(i)))
    return nodes


def reorder_fields(nodes: list[Node]) -> list[Node]:
    """结构变体：反转每个 labelled 节点的字段声明顺序（按名对应应等价）。"""
    out: list[Node] = []
    for node in nodes:
        if isinstance(node, (ProductNode, SumNode)):
            cls = type(node)
            out.append(cls(tuple(reversed(node.fields))))
        else:
            out.append(node)
    return out


def reverse_layout(nodes: list[Node]) -> list[Node]:
    """结构变体：整体反转下标布局并重映射边（节点编号无语义）。"""
    n = len(nodes)
    remap = {i: n - 1 - i for i in range(n)}
    out: list[Node | None] = [None] * n
    for i, node in enumerate(nodes):
        j = remap[i]
        if isinstance(node, (ProductNode, SumNode)):
            cls = type(node)
            fields = tuple(
                Field(f.name, remap[f.target]) for f in node.fields
            )
            out[j] = cls(fields)
        elif isinstance(node, FunctionNode):
            out[j] = FunctionNode(
                tuple(remap[p] for p in node.params), remap[node.result]
            )
        else:
            out[j] = node
    return out  # type: ignore[return-value]


class DAGReferenceCrossTests(unittest.TestCase):
    """无环图：被测结论必须与独立展开参考一致。"""

    def test_random_dags_against_unfold_reference(self) -> None:
        rng = random.Random(20260922)
        graphs: list[TypeGraph] = []
        for _ in range(36):
            n = rng.randint(1, 12)
            g = TypeGraph(random_dag(rng, n), n - 1)
            graphs.append(g)

        compared = 0
        for i, g1 in enumerate(graphs):
            for j, g2 in enumerate(graphs):
                result = check_equivalence(g1, g2)
                expected = reference_equivalent(g1, g1.root, g2, g2.root)
                self.assertEqual(
                    isinstance(result, EquivalenceCertificate),
                    expected,
                    msg=f"DAG pair {i},{j} disagrees with unfold reference",
                )
                if not expected:
                    got_depth = result.depth
                    ref_depth = shortest_divergence_depth(
                        g1, g1.root, g2, g2.root
                    )
                    self.assertEqual(
                        got_depth,
                        ref_depth,
                        msg=f"DAG pair {i},{j} divergence depth disagreement",
                    )
                compared += 1
        self.assertGreater(compared, 100)
        # 随机集合中必须确实出现过正反两类结论，否则该测试无区分力。
        self.assertTrue(
            any(
                reference_equivalent(g1, g1.root, g2, g2.root)
                for g1 in graphs
                for g2 in graphs
            )
        )
        self.assertTrue(
            any(
                not reference_equivalent(g1, g1.root, g2, g2.root)
                for g1 in graphs
                for g2 in graphs
            )
        )

    def test_field_reorder_and_reverse_layout_equivalent(self) -> None:
        rng = random.Random(4242)
        for _ in range(10):
            n = rng.randint(2, 12)
            base = random_dag(rng, n)
            g = TypeGraph(base, n - 1)

            g_reorder = TypeGraph(reorder_fields(base), n - 1)
            self.assertTrue(are_equivalent(g, g_reorder))
            # 独立参考同样判等价（不是用被测算期望）。
            self.assertTrue(
                reference_equivalent(g, g.root, g_reorder, g_reorder.root)
            )

            rev = reverse_layout(base)
            g_rev = TypeGraph(rev, 0)
            self.assertTrue(are_equivalent(g, g_rev))
            self.assertTrue(
                reference_equivalent(g, g.root, g_rev, g_rev.root)
            )

    def test_unfold_reference_value_shape(self) -> None:
        # 对参考本身做一个固定形状断言，防止参考退化。
        g = TypeGraph(
            [
                IntNode(),
                BoolNode(),
                FunctionNode((0,), 1),
            ],
            2,
        )
        self.assertEqual(
            unfold(g, 2),
            ("Function", (("Int",),), ("Bool",)),
        )


class RecursiveEquivalenceTests(unittest.TestCase):
    def test_self_recursion_same_type_different_layout(self) -> None:
        # T = T -> Int
        g1 = TypeGraph(
            [FunctionNode((0,), 1), IntNode()], 0
        )
        # 另一布局：参数指向一个独立但同构的自环节点（共享 vs 复制不区分）。
        # node0 = node1 -> node2 ; node1 = node1 -> node2 ; node2 = Int
        g2 = TypeGraph(
            [
                FunctionNode((1,), 2),
                FunctionNode((1,), 2),
                IntNode(),
            ],
            0,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))

    def test_self_recursion_negative_result_type(self) -> None:
        # T = T -> Int  vs  T = T -> Bool：最短分歧在 depth 1（result）。
        g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        g2 = TypeGraph([FunctionNode((0,), 1), BoolNode()], 0)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 1)
        self.assertEqual(result.path[0].selector, "result")
        self.assertIn("Int", result.render())

    def test_two_node_mutual_recursion_equivalent_when_swapped(self) -> None:
        # T = Product{a: U, b: Int}; U = Sum{x: T, y: Bool}
        g1 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),  # 0 T
                SumNode((Field("x", 0), Field("y", 3))),      # 1 U
                IntNode(),                                     # 2
                BoolNode(),                                    # 3
            ],
            0,
        )
        # 交换 T/U 与叶子的下标布局，根改放最后。
        # new: 0=Bool(=old3), 1=Int(=old2), 2=U(=old1)-> edges 3,0
        #      3=T(=old0)-> edges 2(a),1(b)
        g2 = TypeGraph(
            [
                BoolNode(),
                IntNode(),
                SumNode((Field("x", 3), Field("y", 0))),
                ProductNode((Field("a", 2), Field("b", 1))),
            ],
            3,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))
        # 节点编号不参与语义：根对 (0, 3) 而不是 (0, 0)。
        self.assertEqual(result.root_pair, (0, 3))

    def test_mutual_recursion_deep_leaf_change_diverges(self) -> None:
        # U 的 y 负载 Bool -> Int：无限树在某条路径上必然分歧。
        g1 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                BoolNode(),
            ],
            0,
        )
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                IntNode(),  # 原为 Bool
            ],
            0,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        # 最浅路径 root(T) -field a-> U -field y-> leaf：depth 2。
        self.assertEqual(result.depth, 2)
        self.assertEqual(
            [s.detail for s in result.path], ["a", "y"]
        )
        ref_depth = shortest_divergence_depth(g1, 0, g2, 0)
        self.assertEqual(result.depth, ref_depth)


    def test_wrapper_loop_unfolds_identically(self) -> None:
        # T = Product{a: T}  vs  U = Product{a: Product{a: U}}：
        # 无限展开都是 Product{a: Product{a: ...}}，必须靠协同假设判等价，
        # 朴素有限展开/同余比较会在这里失效。
        g1 = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1),)),  # 0 U
                ProductNode((Field("a", 0),)),   # 1 包装层，绕回 U
            ],
            0,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))

    def test_cyclic_divergence_depth_matches_independent_bfs(self) -> None:
        # 0 = Product{a: 1}; 1 = Sum{x: 0(回边), y: 2}
        # 左 y 负载 Int(2)，右 y 负载 Bool(3)：最浅分歧 depth 2，
        # 与独立参考 BFS（自行处理环）交叉核对。
        g1 = TypeGraph(
            [
                ProductNode((Field("a", 1),)),
                SumNode((Field("x", 0), Field("y", 2))),
                IntNode(),
            ],
            0,
        )
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1),)),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                BoolNode(),
            ],
            0,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 2)
        self.assertEqual([s.detail for s in result.path], ["a", "y"])
        self.assertEqual(shortest_divergence_depth(g1, 0, g2, 0), 2)


class StructuralRulesTests(unittest.TestCase):
    def test_function_parameter_order_matters(self) -> None:
        g1 = TypeGraph(
            [IntNode(), BoolNode(), FunctionNode((0, 1), 0)], 2
        )
        g2 = TypeGraph(
            [IntNode(), BoolNode(), FunctionNode((1, 0), 0)], 2
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 1)
        self.assertEqual(result.path[0].render(), "param(0)")

    def test_function_arity_differs(self) -> None:
        g1 = TypeGraph([IntNode(), FunctionNode((0,), 0)], 1)
        g2 = TypeGraph(
            [IntNode(), FunctionNode((0, 0), 0)], 1
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 0)
        self.assertIn("arity", result.mismatch.reason)

    def test_products_match_by_field_name_not_position(self) -> None:
        g1 = TypeGraph(
            [
                IntNode(),
                BoolNode(),
                ProductNode((Field("a", 0), Field("b", 1))),
            ],
            2,
        )
        g2 = TypeGraph(
            [
                IntNode(),
                BoolNode(),
                ProductNode((Field("b", 1), Field("a", 0))),
            ],
            2,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))

    def test_product_vs_sum_kind_mismatch_at_root(self) -> None:
        g1 = TypeGraph([IntNode(), ProductNode((Field("a", 0),))], 1)
        g2 = TypeGraph([IntNode(), SumNode((Field("a", 0),))], 1)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 0)
        self.assertIn("kind differs", result.mismatch.reason)

    def test_deep_label_difference_at_exact_depth(self) -> None:
        k = 7
        # 0 端是 Sum，1..k 是 field "a" 的 Product 链。
        g1_nodes: list[Node] = [
            SumNode((Field("x", 1), Field("y", 2))),
            IntNode(),
            BoolNode(),
        ]
        g2_nodes: list[Node] = [
            SumNode((Field("x", 1), Field("z", 2))),  # y -> z
            IntNode(),
            BoolNode(),
        ]
        for t in range(k):
            # 第一段链接到 Sum（节点 0），之后逐段链接到上一段；根为最后节点。
            target1 = 0 if t == 0 else len(g1_nodes) - 1
            target2 = 0 if t == 0 else len(g2_nodes) - 1
            g1_nodes.append(ProductNode((Field("a", target1),)))
            g2_nodes.append(ProductNode((Field("a", target2),)))
        g1 = TypeGraph(g1_nodes, len(g1_nodes) - 1)
        g2 = TypeGraph(g2_nodes, len(g2_nodes) - 1)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, k)
        self.assertTrue(all(s.selector == "field" for s in result.path))
        self.assertIn("field-name sets differ", result.mismatch.reason)

    def test_field_mutability_difference_diverges(self) -> None:
        g1 = TypeGraph(
            [ProductNode((Field("a", 1),)), IntNode()], 0
        )
        g2 = TypeGraph(
            [ProductNode((Field("a", 1, True),)), IntNode()], 0
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 0)
        self.assertIn("mutability", result.mismatch.reason)
        self.assertFalse(are_equivalent(g1, g2))

    def test_field_mutability_match_equivalent(self) -> None:
        g1 = TypeGraph(
            [
                ProductNode((Field("a", 0, True), Field("b", 1, False),)),
                IntNode(),
            ],
            0,
        )
        g2 = TypeGraph(
            [
                IntNode(),
                ProductNode((Field("b", 0), Field("a", 2, True),)),
                ProductNode((Field("a", 2, True), Field("b", 0),)),
            ],
            1,
        )
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))

    def test_sharing_vs_duplication_indistinguishable(self) -> None:
        # Product{a: Int, b: Int}：共享同一 Int 节点 vs 复制两个 Int 节点。
        g1 = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        g2 = TypeGraph(
            [
                IntNode(),
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 1))),
            ],
            2,
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_node_numbers_not_semantic(self) -> None:
        g1 = TypeGraph([IntNode(), BoolNode()], 0)
        g2 = TypeGraph([BoolNode(), IntNode()], 1)  # 同是 Int 根
        self.assertTrue(are_equivalent(g1, g2))
        g3 = TypeGraph([BoolNode(), IntNode()], 0)  # 根是 Bool
        self.assertFalse(are_equivalent(g1, g3))

    def test_root_override(self) -> None:
        g = TypeGraph([IntNode(), BoolNode()], 1)
        self.assertTrue(
            are_equivalent(g, g, root1=0, root2=0)
        )
        result = check_equivalence(g, g, root1=0, root2=1)
        self.assertIsInstance(result, Divergence)


class CertificateTests(unittest.TestCase):
    def test_tampered_certificate_rejected(self) -> None:
        g1 = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        g2 = TypeGraph(
            [
                IntNode(),
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 1))),
            ],
            2,
        )
        cert = check_equivalence(g1, g2)
        self.assertIsInstance(cert, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, cert))
        # 删去一个成员对：子对不再封闭 -> 不是 bisimulation。
        shrunk = EquivalenceCertificate(
            cert.root_pair, frozenset(list(cert.related_pairs)[:1])
        )
        self.assertFalse(verify_certificate(g1, g2, shrunk))
        # 根对换成关系外的对（Product vs Int）：未覆盖给定根。
        bad_root = EquivalenceCertificate(
            (1, 0), cert.related_pairs
        )
        self.assertFalse(verify_certificate(g1, g2, bad_root))

    def test_certificate_contains_root_pair(self) -> None:
        g1 = TypeGraph([IntNode()], 0)
        g2 = TypeGraph([IntNode(), BoolNode()], 1)
        result = check_equivalence(g1, g2, root2=0)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertIn((0, 0), result.related_pairs)


class BudgetTests(unittest.TestCase):
    def test_budget_exhaustion_is_separate_from_disproof(self) -> None:
        # 需要展开 >=2 个不同对的等价递归类型；budget=1 必须报“未知”，
        # 绝不能给出 Divergence（那意味着已证伪）。
        g1 = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        g2 = TypeGraph(
            [
                IntNode(),
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 1))),
            ],
            2,
        )
        with self.assertRaises(BudgetExceededError) as cm:
            check_equivalence(g1, g2, budget=1)
        self.assertEqual(cm.exception.budget, 1)

    def test_budget_allows_shallow_equivalence(self) -> None:
        g1 = TypeGraph([IntNode()], 0)
        g2 = TypeGraph([IntNode()], 0)
        result = check_equivalence(g1, g2, budget=1)
        self.assertIsInstance(result, EquivalenceCertificate)

    def test_proven_divergence_not_reported_as_budget(self) -> None:
        # 预算极小，但结论（depth-1 分歧）在预算内可证：必须给 Divergence。
        g1 = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )
        g2 = TypeGraph(
            [BoolNode(), ProductNode((Field("a", 0),))], 1
        )
        result = check_equivalence(g1, g2, budget=1)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, 1)

    def test_invalid_budget_rejected_upfront(self) -> None:
        g = TypeGraph([IntNode()], 0)
        for bad in (0, -1, True, 1.0, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    check_equivalence(g, g, budget=bad)

    def test_invalid_root_override_rejected(self) -> None:
        g = TypeGraph([IntNode()], 0)
        with self.assertRaises(ValueError):
            check_equivalence(g, g, root1=5, root2=0)
        with self.assertRaises(TypeError):
            check_equivalence(g, g, root1=True, root2=0)  # type: ignore[arg-type]

    def test_wrong_graph_type_rejected(self) -> None:
        g = TypeGraph([IntNode()], 0)
        with self.assertRaises(TypeError):
            check_equivalence(g, [IntNode()])  # type: ignore[arg-type]


class ScaleTests(unittest.TestCase):
    def test_300_node_chains_equivalent(self) -> None:
        # 两张 300 节点深链：无递归深度问题（迭代实现），结论等价。
        def chain() -> list[Node]:
            nodes: list[Node] = [IntNode()]
            for i in range(1, 300):
                nodes.append(ProductNode((Field("a", i - 1),)))
            return nodes

        g1 = TypeGraph(chain(), 299)
        g2 = TypeGraph(reverse_layout(chain()), 0)
        result = check_equivalence(g1, g2)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g1, g2, result))

    def test_300_node_self_recursive_equivalent(self) -> None:
        # μX. X -> Int：单自环布局 vs 沿 299 个复制节点绕回的大环布局。
        g_small = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        big: list[Node] = []
        for i in range(299):
            nxt = i + 1 if i < 298 else 0  # 末节点回指 0，形成大环
            big.append(FunctionNode((nxt,), 299))
        big.append(IntNode())
        g_big = TypeGraph(big, 0)
        self.assertEqual(len(g_big), 300)
        result = check_equivalence(g_small, g_big)
        self.assertIsInstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g_small, g_big, result))

    def test_finite_unfold_is_not_recursive_type(self) -> None:
        # 反向断言：有限深度的函数链末型 Int 与 μX. X -> Int 不等价，
        # 最浅分歧恰在链底（depth = 链长）。
        g_rec = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        finite: list[Node] = [IntNode()]
        depth = 5
        for _ in range(depth):
            finite.append(FunctionNode((len(finite) - 1,), 0))
        g_fin = TypeGraph(finite, len(finite) - 1)
        result = check_equivalence(g_rec, g_fin)
        self.assertIsInstance(result, Divergence)
        self.assertEqual(result.depth, depth)
        self.assertEqual(
            shortest_divergence_depth(g_rec, 0, g_fin, g_fin.root), depth
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
