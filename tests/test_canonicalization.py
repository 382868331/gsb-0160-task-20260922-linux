"""共享规范化表示（canonicalize）的测试。

期望值来源：
* 无环图上规范化的“合并正确性”与独立参考 reference_unfold 交叉验证
  （同展开树 => 同规范化节点；不同 => 不同节点），参考不调用被测核心；
* 循环、可变性、幂等用例为手工固定构造并给出显式断言。
"""

from __future__ import annotations

import random
import unittest

from recursive_types import (
    BoolNode,
    BudgetExceededError,
    Canonicalization,
    Field,
    FunctionNode,
    GraphSizeError,
    IntNode,
    InvalidNodeError,
    ProductNode,
    SumNode,
    TypeGraph,
    are_equivalent,
    canonical_node_of,
    canonicalize,
)
from tests.reference_unfold import reference_equivalent, unfold
from tests.test_equivalence import random_dag


def reversed_fields(nodes):
    out = []
    for node in nodes:
        if isinstance(node, (ProductNode, SumNode)):
            out.append(type(node)(tuple(reversed(node.fields))))
        else:
            out.append(node)
    return out


class DAGCanonicalTests(unittest.TestCase):
    def test_random_dags_agree_with_unfold_reference(self) -> None:
        rng = random.Random(20260927)
        graphs: list[TypeGraph] = []
        for _ in range(30):
            n = rng.randint(1, 10)
            g = TypeGraph(random_dag(rng, n), n - 1)
            graphs.append(g)
        # 再为前若干张加入“字段顺序打乱”的同构副本。
        variants = []
        for g in graphs[:12]:
            variants.append(
                TypeGraph(reversed_fields(list(g.nodes)), g.root)
            )
        all_graphs = graphs + variants

        result = canonicalize(all_graphs)

        # 逐对核对：规范化节点相等 <=> 独立展开树相等。
        trees = {id(g): {j: unfold(g, j) for j in range(len(g))}
                 for g in all_graphs}
        for i, g1 in enumerate(all_graphs):
            for j, g2 in enumerate(all_graphs):
                for a in range(len(g1)):
                    for b in range(len(g2)):
                        same_canon = (
                            result.mapping[i][a] == result.mapping[j][b]
                        )
                        same_tree = trees[id(g1)][a] == trees[id(g2)][b]
                        self.assertIs(
                            same_canon,
                            same_tree,
                            msg=(
                                f"merge disagreement at ({i},{a}) vs ({j},{b})"
                            ),
                        )

        # 根对应与 check_equivalence 的结论一致。
        for i, g1 in enumerate(all_graphs):
            for j, g2 in enumerate(all_graphs):
                expected = reference_equivalent(g1, g1.root, g2, g2.root)
                self.assertIs(
                    result.roots[i] == result.roots[j],
                    expected,
                )

    def test_dedup_reduces_node_count(self) -> None:
        # 4 个写法不同但都是 Int 的叶子 + 1 个 Bool => 仅 2 个语义类。
        g1 = TypeGraph([IntNode(), IntNode()], 0)
        g2 = TypeGraph([IntNode(), BoolNode(), IntNode()], 2)
        result = canonicalize((g1, g2))
        self.assertEqual(result.class_count, 2)
        self.assertEqual(result.total_input_nodes, 5)
        int_class = result.mapping[0][0]
        self.assertEqual(result.mapping[0][1], int_class)
        self.assertEqual(result.mapping[1][0], int_class)
        self.assertEqual(result.mapping[1][2], int_class)
        self.assertNotEqual(result.mapping[1][1], int_class)


class RecursiveCanonicalTests(unittest.TestCase):
    def test_self_recursion_merges_across_layouts(self) -> None:
        g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        g2 = TypeGraph(
            [FunctionNode((1,), 2), FunctionNode((1,), 2), IntNode()], 0
        )
        result = canonicalize((g1, g2))
        # μX. X -> Int 只产生两个语义类：自指函数 与 Int。
        self.assertEqual(result.class_count, 2)
        fn_class = result.mapping[0][0]
        self.assertEqual(result.mapping[1][0], fn_class)
        self.assertEqual(result.mapping[1][1], fn_class)  # 复制副本合并
        self.assertEqual(result.roots, (fn_class, fn_class))
        # 规范化图里函数节点自指。
        fn_node = result.graph[fn_class]
        self.assertIsInstance(fn_node, FunctionNode)
        self.assertEqual(fn_node.params, (fn_class,))
        self.assertTrue(are_equivalent(g1, g2))

    def test_wrapper_loop_merges_with_two_node_loop(self) -> None:
        # μX.P{a:X}  vs  μY.P{a:P{a:Y}}：无限树相同，必须合并。
        g1 = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g2 = TypeGraph(
            [ProductNode((Field("a", 1),)), ProductNode((Field("a", 0),))], 0
        )
        result = canonicalize((g1, g2))
        self.assertEqual(result.class_count, 1)
        node = result.graph[result.roots[0]]
        self.assertEqual(node.fields[0].target, result.roots[0])

    def test_distinct_recursive_types_stay_apart(self) -> None:
        # T = T -> Int  vs  U = U -> Bool：同形但叶子不同，禁止合并。
        g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        g2 = TypeGraph([FunctionNode((0,), 1), BoolNode()], 0)
        result = canonicalize((g1, g2))
        self.assertEqual(result.class_count, 4)
        self.assertNotEqual(result.roots[0], result.roots[1])

    def test_cycle_field_name_difference_stays_apart(self) -> None:
        g1 = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g2 = TypeGraph([ProductNode((Field("b", 0),))], 0)
        result = canonicalize((g1, g2))
        self.assertEqual(result.class_count, 2)


class MutabilityTests(unittest.TestCase):
    def test_mutability_part_of_semantics(self) -> None:
        immutable = TypeGraph(
            [ProductNode((Field("a", 1),)), IntNode()], 0
        )
        mutable = TypeGraph(
            [ProductNode((Field("a", 1, True),)), IntNode()], 0
        )
        self.assertFalse(are_equivalent(immutable, mutable))
        result = canonicalize((immutable, mutable))
        # Int 共享，两个 Product 因可变性不同分开 => 3 类。
        self.assertEqual(result.class_count, 3)
        self.assertNotEqual(result.roots[0], result.roots[1])
        self.assertEqual(
            result.mapping[0][1], result.mapping[1][1]
        )  # Int 仍共享
        self.assertFalse(result.graph[result.roots[0]].fields[0].mutable)
        self.assertTrue(result.graph[result.roots[1]].fields[0].mutable)

    def test_mutable_matching_layouts_merge(self) -> None:
        g1 = TypeGraph([ProductNode((Field("a", 0, True),))], 0)
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1, True),)),
                ProductNode((Field("a", 0, True),)),
            ],
            0,
        )
        result = canonicalize((g1, g2))
        self.assertEqual(result.class_count, 1)
        self.assertTrue(result.graph[0].fields[0].mutable)

    def test_non_bool_mutability_rejected(self) -> None:
        with self.assertRaises(InvalidNodeError):
            TypeGraph([ProductNode((Field("a", 0, 1),))], 0)


class IdempotenceTests(unittest.TestCase):
    def test_recanonicalize_is_identity(self) -> None:
        g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 0))),
                BoolNode(),
            ],
            0,
        )
        first = canonicalize((g1, g2))
        second = canonicalize(first.graph)
        self.assertEqual(second.class_count, first.class_count)
        self.assertEqual(second.total_input_nodes, first.class_count)
        # 对应关系为恒等：每个规范化节点映射到自己。
        self.assertEqual(
            tuple(second.mapping[0]), tuple(range(first.class_count))
        )
        self.assertEqual(second.roots[0], first.graph.root)
        # 节点骨架逐一同构（重映射后字段/参数指向相同编号）。
        for i in range(first.class_count):
            self.assertEqual(
                first.graph[i].kind, second.graph[i].kind
            )

    def test_canonicalize_twice_no_structure_change(self) -> None:
        # 对“整理结果再整理”反复做，第三次起必须完全不动。
        g = TypeGraph(
            [
                SumNode((Field("x", 1), Field("y", 0))),
                IntNode(),
            ],
            0,
        )
        r1 = canonicalize(g)
        r2 = canonicalize(r1.graph)
        r3 = canonicalize(r2.graph)
        self.assertEqual(r2.mapping, r3.mapping)
        self.assertEqual(r2.roots, r3.roots)


class CorrespondenceAndInterfaceTests(unittest.TestCase):
    def test_mapping_covers_every_node_and_edges_close(self) -> None:
        g1 = TypeGraph(
            [ProductNode((Field("a", 1),)), IntNode(), BoolNode()], 0
        )
        result = canonicalize(g1)
        self.assertEqual(len(result.mapping[0]), len(g1))
        # 每条边在规范化图中都有对应的边（对应关系是图同态）。
        for j, node in enumerate(g1.nodes):
            cj = result.mapping[0][j]
            if isinstance(node, (ProductNode, SumNode)):
                canon_fields = {
                    (f.name, f.mutable): f.target
                    for f in result.graph[cj].fields
                }
                for f in node.fields:
                    self.assertEqual(
                        canon_fields[(f.name, f.mutable)],
                        result.mapping[0][f.target],
                    )
            elif isinstance(node, FunctionNode):
                cn = result.graph[cj]
                self.assertEqual(
                    tuple(result.mapping[0][p] for p in node.params),
                    cn.params,
                )
                self.assertEqual(
                    result.mapping[0][node.result], cn.result
                )

    def test_single_graph_and_roots_override(self) -> None:
        g = TypeGraph([IntNode(), BoolNode()], root=0)
        r_default = canonicalize(g)
        self.assertEqual(r_default.roots, (0,))
        r_bool = canonicalize(g, roots=1)
        self.assertEqual(r_bool.graph.root, r_bool.roots[0])
        self.assertEqual(
            r_bool.mapping[0][1], r_bool.graph.root
        )

    def test_canonical_node_of_helper(self) -> None:
        g = TypeGraph([IntNode(), IntNode()], 0)
        result = canonicalize(g)
        self.assertEqual(
            canonical_node_of(result, 0, 1), result.mapping[0][1]
        )
        with self.assertRaises(IndexError):
            canonical_node_of(result, 0, 5)
        with self.assertRaises(IndexError):
            canonical_node_of(result, 1, 0)

    def test_invalid_arguments(self) -> None:
        g = TypeGraph([IntNode()], 0)
        with self.assertRaises(TypeError):
            canonicalize("not a graph")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            canonicalize(())
        with self.assertRaises(TypeError):
            canonicalize(g, budget=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            canonicalize(g, budget=0)
        with self.assertRaises(TypeError):
            canonicalize(g, roots=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            canonicalize((g, g), roots=(0,))

    def test_budget_exhausted_is_unknown(self) -> None:
        g = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                IntNode(),
                BoolNode(),
            ],
            0,
        )
        # 预算 1：第一轮尚未算完所有签名即耗尽 => 结果未知。
        with self.assertRaises(BudgetExceededError):
            canonicalize(g, budget=1)
        # 充足预算正常。
        canonicalize(g, budget=100)

    def test_result_is_canonicalization_object(self) -> None:
        result = canonicalize(TypeGraph([IntNode()], 0))
        self.assertIsInstance(result, Canonicalization)
        self.assertIn("CANONICAL", result.render())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
