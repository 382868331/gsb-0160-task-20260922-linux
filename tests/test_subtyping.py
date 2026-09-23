"""结构子类型检查的测试。

期望值来源：
* 无环图一律与独立参考 ``reference_subtype``（完整展开树上的独立子类型判据 +
  独立 BFS 最浅违反深度）交叉验证，该参考不 import 被测判定算法；
* 递归（含环）与受保护性用例为手工固定构造并给出显式断言（含手算路径）。
"""

from __future__ import annotations

import random
import unittest

from recursive_types import (
    AliasNode,
    BoolNode,
    BudgetExceededError,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SubtypeFailure,
    SubtypingCertificate,
    SumNode,
    TypeGraph,
    check_subtype,
    is_subtype,
    verify_subtype_certificate,
)
from recursive_types.model import Node

from tests.reference_subtype import (
    reference_subtype_on_graphs,
    shortest_failure_depth,
)

FIELD_POOL = ("a", "b", "c", "d")
SUM_POOL = ("x", "y", "z")


def random_dag(rng: random.Random, n: int) -> list[Node]:
    """确定性 n 节点无环图：所有边只指向更小下标（Product 偏多以产生宽度关系）。"""
    nodes: list[Node] = [IntNode() if rng.random() < 0.5 else BoolNode()]
    for i in range(1, n):
        choice = rng.random()
        if choice < 0.2:
            nodes.append(IntNode() if rng.random() < 0.5 else BoolNode())
        elif choice < 0.65:
            count = rng.randint(1, min(3, len(FIELD_POOL)))
            names = rng.sample(FIELD_POOL, count)
            nodes.append(
                ProductNode(tuple(Field(name, rng.randrange(i)) for name in names))
            )
        elif choice < 0.85:
            count = rng.randint(1, min(2, len(SUM_POOL)))
            names = rng.sample(SUM_POOL, count)
            nodes.append(
                SumNode(tuple(Field(name, rng.randrange(i)) for name in names))
            )
        else:
            argc = rng.randint(1, 2)
            nodes.append(
                FunctionNode(
                    tuple(rng.randrange(i) for _ in range(argc)), rng.randrange(i)
                )
            )
    return nodes


# --------------------------------------------------------------------------- #
# 手工构造的固定类型（手算期望）
# --------------------------------------------------------------------------- #


def wide_narrow_graphs() -> tuple[TypeGraph, TypeGraph, TypeGraph, TypeGraph]:
    """返回 (wide_record, narrow_record, wide_sum, narrow_sum)。"""
    # Rw = {a: Int, b: Bool}；Rn = {a: Int}
    g_rec_wide = TypeGraph(
        [IntNode(), BoolNode(),
         ProductNode((Field("a", 0), Field("b", 1)))], 2)
    g_rec_narrow = TypeGraph(
        [IntNode(), ProductNode((Field("a", 0),))], 1)
    # Sw = x:Int | y:Bool；Sn = x:Int
    g_sum_wide = TypeGraph(
        [IntNode(), BoolNode(),
         SumNode((Field("x", 0), Field("y", 1)))], 2)
    g_sum_narrow = TypeGraph(
        [IntNode(), SumNode((Field("x", 0),))], 1)
    return g_rec_wide, g_rec_narrow, g_sum_wide, g_sum_narrow


class DAGReferenceCrossTests(unittest.TestCase):
    def test_random_dags_against_tree_reference(self) -> None:
        rng = random.Random(20260924)
        graphs: list[TypeGraph] = []
        for _ in range(36):
            n = rng.randint(1, 10)
            g = TypeGraph(random_dag(rng, n), n - 1)
            graphs.append(g)

        compared = 0
        positives = 0
        negatives = 0
        for i, g1 in enumerate(graphs):
            for j, g2 in enumerate(graphs):
                result = check_subtype(g1, g2)
                expected = reference_subtype_on_graphs(
                    g1, g1.root, g2, g2.root
                )
                self.assertEqual(
                    isinstance(result, SubtypingCertificate),
                    expected,
                    msg=f"DAG pair {i},{j} disagrees with tree reference",
                )
                if expected:
                    self.assertTrue(
                        verify_subtype_certificate(g1, g2, result),
                        msg=f"DAG pair {i},{j} certificate not verifiable",
                    )
                    positives += 1
                else:
                    negatives += 1
                    self.assertIsInstance(result, SubtypeFailure)
                    ref_depth = shortest_failure_depth(
                        g1, g1.root, g2, g2.root
                    )
                    self.assertEqual(
                        result.depth,
                        ref_depth,
                        msg=(
                            f"DAG pair {i},{j} violation depth disagreement "
                            f"(got {result.depth}, ref {ref_depth})"
                        ),
                    )
                compared += 1
        self.assertGreater(compared, 100)
        self.assertGreater(positives, 0)  # 至少有自反/宽度成立用例
        self.assertGreater(negatives, 0)  # 也必须有反例，否则测试无区分力

    def test_reflexivity_on_random_dags(self) -> None:
        rng = random.Random(7)
        for _ in range(15):
            n = rng.randint(1, 12)
            g = TypeGraph(random_dag(rng, n), n - 1)
            result = check_subtype(g, g)
            self.assertIsInstance(result, SubtypingCertificate)
            self.assertTrue(verify_subtype_certificate(g, g, result))
            self.assertTrue(
                reference_subtype_on_graphs(g, g.root, g, g.root)
            )


class HandComputedRuleTests(unittest.TestCase):
    """逐条规则的手算用例（期望值人工推导，不用被测实现生成）。"""

    def test_base_types(self) -> None:
        gi = TypeGraph([IntNode()], 0)
        gb = TypeGraph([BoolNode()], 0)
        self.assertTrue(is_subtype(gi, gi))
        self.assertFalse(is_subtype(gi, gb))
        result = check_subtype(gi, gb)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)
        self.assertIn("kind differs", result.mismatch.reason)

    def test_product_width_subtyping(self) -> None:
        wide, narrow, _, _ = wide_narrow_graphs()
        # {a:Int,b:Bool} <: {a:Int}  成立；反向不成立（缺 b）。
        self.assertTrue(is_subtype(wide, narrow))
        result = check_subtype(narrow, wide)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)
        self.assertIn("missing", result.mismatch.left)
        self.assertIn("'b'", result.mismatch.left)

    def test_product_field_covariance(self) -> None:
        # {f: {a:Int,b:Bool}} <: {f: {a:Int}}：字段成分协变 + 宽度。
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),       # 2 Rw
             ProductNode((Field("f", 2),))],                    # 3 根
            3,
        )
        g_sup = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 0),)),                     # 1 Rn
             ProductNode((Field("f", 1),))],                    # 2 根
            2,
        )
        result = check_subtype(g_sub, g_sup)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(g_sub, g_sup, result))
        # 字段成分反例：{f: {a:Int}} </: {f: {a:Int,b:Bool}}，违反在 depth 1。
        rev = check_subtype(g_sup, g_sub)
        self.assertIsInstance(rev, SubtypeFailure)
        self.assertEqual(rev.depth, 1)
        self.assertEqual(rev.path[0].render(), "field(f)")

    def test_sum_width_goes_the_other_way(self) -> None:
        _, _, wide, narrow = wide_narrow_graphs()
        # x:Int <: x:Int|y:Bool 成立（子类型分支更少）；反向不成立。
        self.assertTrue(is_subtype(narrow, wide))
        result = check_subtype(wide, narrow)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)
        self.assertIn("extra", result.mismatch.left)
        self.assertIn("'y'", result.mismatch.left)

    def test_function_parameter_contravariance(self) -> None:
        # 逆变的正确方向：(Rn) -> Int <: (Rw) -> Int，因为 Rw <: Rn。
        # 直觉：调用方按 (Rw) 传参会给足 {a,b}，实际函数只用 {a}，安全。
        g_narrow_fn = TypeGraph(   # (Rn) -> Int
            [IntNode(),
             ProductNode((Field("a", 0),)),                 # 1 Rn
             FunctionNode((1,), 0)],                        # 2
            2,
        )
        g_wide_fn = TypeGraph(     # (Rw) -> Int
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),   # 2 Rw
             FunctionNode((2,), 0)],                        # 3
            3,
        )
        result = check_subtype(g_narrow_fn, g_wide_fn)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(
            verify_subtype_certificate(g_narrow_fn, g_wide_fn, result)
        )
        # 反向：(Rw)->Int </: (Rn)->Int；参数位需要 Rn <: Rw，缺 b，depth 1。
        rev = check_subtype(g_wide_fn, g_narrow_fn)
        self.assertIsInstance(rev, SubtypeFailure)
        self.assertEqual(rev.depth, 1)
        self.assertEqual(rev.path[0].render(), "param(0)")

    def test_function_result_covariance(self) -> None:
        # Int -> Rw <: Int -> Rn（返回值协变）。
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),
             FunctionNode((0,), 2)],
            3,
        )
        g_sup = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 0),)),
             FunctionNode((0,), 1)],
            2,
        )
        self.assertTrue(is_subtype(g_sub, g_sup))
        rev = check_subtype(g_sup, g_sub)
        self.assertIsInstance(rev, SubtypeFailure)
        self.assertEqual(rev.depth, 1)
        self.assertEqual(rev.path[0].render(), "result")

    def test_function_arity_invariant(self) -> None:
        g1 = TypeGraph(
            [IntNode(), FunctionNode((0, 0), 0)], 1)
        g2 = TypeGraph(
            [IntNode(), FunctionNode((0,), 0)], 1)
        result = check_subtype(g1, g2)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)
        self.assertIn("arity", result.mismatch.reason)

    def test_sum_constituent_covariance_deep(self) -> None:
        # x:{a,b} <: x:{a}，y:Int~Int：成分协变，depth 1 处字段宽度成立。
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),      # 2 Rw
             SumNode((Field("x", 2), Field("y", 0)))],         # 3 根
            3,
        )
        g_sup = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 0),)),                    # 1 Rn
             SumNode((Field("x", 1), Field("y", 0)))],         # 2 根
            2,
        )
        result = check_subtype(g_sub, g_sup)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(g_sub, g_sup, result))

    def test_nested_function_double_flip_is_covariant_again(self) -> None:
        # 二阶函数：( (Rw) -> Int ) -> Int  <:  ( (Rn) -> Int ) -> Int？
        # 外层参数逆变：需要 (Rn)->Int <: (Rw)->Int，这由一层逆变成立
        # （Fn <: Fw）。两次翻转=同向，整体成立。
        # g_sub: 0 Int,1 Bool,2 Rw,3 (Rw)->Int,4 根=(3)->Int
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),
             FunctionNode((2,), 0),
             FunctionNode((3,), 0)],
            4,
        )
        # g_sup: 0 Int,1 Rn,2 (Rn)->Int,3 根=(2)->Int
        g_sup = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 0),)),
             FunctionNode((1,), 0),
             FunctionNode((2,), 0)],
            3,
        )
        result = check_subtype(g_sub, g_sup)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(g_sub, g_sup, result))

    def test_violation_through_param_then_field_path(self) -> None:
        # g_sub: Int -> Int；g_sup: {a,b} -> Int。
        # 需要参数位 g_sup 参数 <: g_sub 参数，即 {a,b} <: Int，
        # 种类不同，depth 1，路径 param(0)。
        g_sub = TypeGraph(
            [IntNode(), FunctionNode((0,), 0)], 1)
        g_sup = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),
             FunctionNode((2,), 0)],
            3,
        )
        result = check_subtype(g_sub, g_sup)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 1)
        self.assertEqual(result.path[0].render(), "param(0)")
        self.assertEqual(shortest_failure_depth(g_sub, 1, g_sup, 3), 1)

    def test_contravariant_recursion_blocks_subtyping_hand_case(self) -> None:
        """手算经典反例：S = μX. X -> Rw，T = μY. Y -> Rn（Rw 宽、Rn 窄）。

        S <: T 在根处要求参数位 T <: S（逆变），其返回位又要求 Rn <: Rw，
        缺字段 b —— 递归两次后矛盾。最浅违反 depth 2：param(0) -> result。
        """
        # S 图: 0=Int, 1=Bool, 2=Rw, 3=Function(param=3 自指, result=2)
        g_s = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),
             FunctionNode((3,), 2)],
            3,
        )
        # T 图: 0=Int, 1=Rn, 2=Function(param=2 自指, result=1)
        g_t = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 0),)),
             FunctionNode((2,), 1)],
            2,
        )
        result = check_subtype(g_s, g_t)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 2)
        self.assertEqual(
            [s.render() for s in result.path], ["param(0)", "result"]
        )
        # 独立 BFS（自行处理环）给出同一深度。
        self.assertEqual(shortest_failure_depth(g_s, 3, g_t, 2), 2)


class RecursiveSubtypingTests(unittest.TestCase):
    def test_width_subtyping_through_guarded_recursion(self) -> None:
        # S = μX. {a: X, b: Int}；T = μY. {a: Y}。
        # S <: T：宽度（超类型不要 b）+ 字段 a 协变遇到协递归假设 -> 成立。
        g_s = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],  # 1 自指
            1,
        )
        g_t = TypeGraph(
            [ProductNode((Field("a", 0),))], 0
        )
        result = check_subtype(g_s, g_t)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(g_s, g_t, result))

    def test_recursive_width_reverse_fails(self) -> None:
        # T = μY.{a:Y} 不是 S = μX.{a:X,b:Int} 的子类型：根即缺字段 b。
        g_s = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        g_t = TypeGraph([ProductNode((Field("a", 0),))], 0)
        result = check_subtype(g_t, g_s)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)

    def test_recursive_payload_mismatch_shallowest_path(self) -> None:
        # S = μX.{a:X, b: Int} vs U = μZ.{a:Z, b: Bool}：
        # a 位是协递归假设，b 位 depth 1 处 Int/Bool 分歧。
        g_s = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        g_u = TypeGraph(
            [BoolNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        result = check_subtype(g_s, g_u)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 1)
        self.assertEqual(result.path[0].render(), "field(b)")
        self.assertEqual(shortest_failure_depth(g_s, 1, g_u, 1), 1)

    def test_recursive_equivalence_implies_both_directions(self) -> None:
        # μX.{a:X} 的两种布局（直连回边 vs 经显式 Alias）互为子类型。
        g_direct = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g_alias = TypeGraph(
            [ProductNode((Field("a", 1),)), AliasNode(0)], 0
        )
        for a, b in ((g_direct, g_alias), (g_alias, g_direct)):
            result = check_subtype(a, b)
            self.assertIsInstance(result, SubtypingCertificate)
            self.assertTrue(verify_subtype_certificate(a, b, result))


class AliasTransparencyTests(unittest.TestCase):
    def test_alias_chain_is_transparent_for_subtyping(self) -> None:
        # 左侧经两层 Alias 到达 {a:Int,b:Bool}，语义就是宽记录。
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),  # 2 Rw
             AliasNode(2), AliasNode(3)],                   # 3,4 别名链
            4,
        )
        g_sup = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )
        self.assertTrue(is_subtype(g_sub, g_sup))
        self.assertTrue(
            reference_subtype_on_graphs(g_sub, g_sub.root, g_sup, g_sup.root)
        )

    def test_root_pair_reported_at_structural_layer(self) -> None:
        g = TypeGraph(
            [IntNode(), AliasNode(0)], 1  # 根是 Alias
        )
        result = check_subtype(g, g)
        self.assertIsInstance(result, SubtypingCertificate)
        # 根对归一到结构节点 0，而不是别名节点 1。
        self.assertEqual(result.root_pair, (0, 0))


class CertificateTests(unittest.TestCase):
    def test_tampered_subtype_certificate_rejected(self) -> None:
        wide, narrow, _, _ = wide_narrow_graphs()
        cert = check_subtype(wide, narrow)
        self.assertIsInstance(cert, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(wide, narrow, cert))
        # 删去成员对：义务不再封闭。
        shrunk = SubtypingCertificate(
            cert.root_pair, frozenset(list(cert.related_pairs)[:1])
        )
        self.assertFalse(verify_subtype_certificate(wide, narrow, shrunk))
        # 根对换成关系外的对。
        bad_root = SubtypingCertificate((0, 1), cert.related_pairs)
        self.assertFalse(verify_subtype_certificate(wide, narrow, bad_root))

    def test_certificate_out_of_range_pair_rejected(self) -> None:
        g = TypeGraph([IntNode()], 0)
        cert = SubtypingCertificate((0, 0), frozenset({(0, 9, False)}))
        self.assertFalse(verify_subtype_certificate(g, g, cert))


class SubtypeBudgetTests(unittest.TestCase):
    def test_budget_exhaustion_is_separate_from_disproof(self) -> None:
        # 需展开 >=2 个不同义务对的递归子类型；budget=1 必须报“未知”，
        # 绝不能给出 SubtypeFailure（那意味着已证伪）。
        # S = μX.{a:X, b:Int}，T = μY.{a:Y, b:Int}：根对 + b 位的 (Int,Int)。
        g_s = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        g_t = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        with self.assertRaises(BudgetExceededError) as cm:
            check_subtype(g_s, g_t, budget=1)
        self.assertEqual(cm.exception.budget, 1)

    def test_shallow_success_with_tiny_budget(self) -> None:
        g1 = TypeGraph([IntNode()], 0)
        result = check_subtype(g1, g1, budget=1)
        self.assertIsInstance(result, SubtypingCertificate)

    def test_proven_violation_not_reported_as_budget(self) -> None:
        g1 = TypeGraph([IntNode()], 0)
        g2 = TypeGraph([BoolNode()], 0)
        result = check_subtype(g1, g2, budget=1)
        self.assertIsInstance(result, SubtypeFailure)
        self.assertEqual(result.depth, 0)

    def test_invalid_budget_rejected_upfront(self) -> None:
        g = TypeGraph([IntNode()], 0)
        for bad in (0, -3, False, 1.0, float("inf")):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    check_subtype(g, g, budget=bad)

    def test_invalid_root_override_rejected(self) -> None:
        g = TypeGraph([IntNode()], 0)
        with self.assertRaises(ValueError):
            check_subtype(g, g, root_sub=5)
        with self.assertRaises(TypeError):
            check_subtype(g, g, root_sub=True)  # type: ignore[arg-type]

    def test_wrong_graph_type_rejected(self) -> None:
        g = TypeGraph([IntNode()], 0)
        with self.assertRaises(TypeError):
            check_subtype(g, [IntNode()])  # type: ignore[arg-type]


class SubtypeScaleTests(unittest.TestCase):
    def test_300_node_chains_width_subtype(self) -> None:
        # 左侧 300 链每层都比右侧多一个字段 b:Int（每层独立叶子即可）。
        left: list[Node] = [IntNode()]
        right: list[Node] = [IntNode()]
        for i in range(1, 300):
            left.append(
                ProductNode((Field("a", i - 1), Field("b", 0)))
            )
            right.append(ProductNode((Field("a", i - 1),)))
        g_left = TypeGraph(left, 299)
        g_right = TypeGraph(right, 299)
        self.assertEqual(len(g_left), 300)
        result = check_subtype(g_left, g_right)
        self.assertIsInstance(result, SubtypingCertificate)
        self.assertTrue(verify_subtype_certificate(g_left, g_right, result))
        # 反向：根层即缺 b。
        rev = check_subtype(g_right, g_left)
        self.assertIsInstance(rev, SubtypeFailure)
        self.assertEqual(rev.depth, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
