"""equi-recursive 等价判定的手写用例测试。

这些用例直接按无限展开树语义构造（包括自递归、双节点递归、函数参数
顺序、深处标签差异），不依赖任何参考实现来得到期望值。
"""

import unittest

from rectypes import (
    BudgetExhaustedError,
    CertificateInvalid,
    TypeGraph,
    are_equivalent,
    check_equivalence,
    verify_certificate,
)


def g_int(root="i"):
    return TypeGraph({root: {"kind": "Int"}}, root=root)


class BasicEquivalenceTests(unittest.TestCase):
    def test_atoms(self):
        self.assertTrue(are_equivalent(g_int("i"), g_int("j")))
        self.assertFalse(
            are_equivalent(
                TypeGraph({"b": {"kind": "Bool"}}, root="b"), g_int()
            )
        )

    def test_certificate_verifies_independently(self):
        r = check_equivalence(g_int("i"), g_int("j"))
        self.assertTrue(r.equivalent)
        self.assertIsNotNone(r.certificate)
        self.assertTrue(verify_certificate(r.certificate, g_int("i"), g_int("j")))

    def test_node_ids_are_not_semantics(self):
        # 完全不同的节点编号/字符串，结构相同即等价。
        g1 = TypeGraph(
            {
                0: {"kind": "Product", "fields": [("a", 10), ("b", 11)]},
                10: {"kind": "Int"},
                11: {"kind": "Bool"},
            },
            root=0,
        )
        g2 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "z"), ("b", "q")]},
                "z": {"kind": "Int"},
                "q": {"kind": "Bool"},
            },
            root="r",
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_field_order_insensitive(self):
        g1 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "i"), ("b", "j")]},
                "i": {"kind": "Int"},
                "j": {"kind": "Bool"},
            },
            root="r",
        )
        g2 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("b", "j"), ("a", "i")]},
                "i": {"kind": "Int"},
                "j": {"kind": "Bool"},
            },
            root="r",
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_sum_label_mismatch_at_root(self):
        g1 = TypeGraph(
            {"r": {"kind": "Sum", "fields": [("a", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        g2 = TypeGraph(
            {"r": {"kind": "Sum", "fields": [("b", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 0)
        self.assertIn("labels", r.divergence.reason)

    def test_field_type_mismatch(self):
        g1 = TypeGraph(
            {"r": {"kind": "Product", "fields": [("a", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        g2 = TypeGraph(
            {"r": {"kind": "Product", "fields": [("a", "b")]}, "b": {"kind": "Bool"}},
            root="r",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 1)
        self.assertEqual(r.divergence.steps[1].access, ("field", "a"))

    def test_product_vs_sum_head_clash(self):
        g1 = TypeGraph(
            {"r": {"kind": "Product", "fields": [("a", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        g2 = TypeGraph(
            {"r": {"kind": "Sum", "fields": [("a", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 0)


class FunctionTests(unittest.TestCase):
    def test_param_order_significant(self):
        # (Int, Bool) -> Int  vs  (Bool, Int) -> Int：参数有序，不等价。
        def make(swap):
            fields = [("p0", "i"), ("p1", "b")]
            if swap:
                fields = [("p0", "b"), ("p1", "i")]
            nodes = {
                "r": {
                    "kind": "Function",
                    "params": [t for _, t in fields],
                    "result": "i",
                },
                "i": {"kind": "Int"},
                "b": {"kind": "Bool"},
            }
            return TypeGraph(nodes, root="r")

        r = check_equivalence(make(False), make(True))
        self.assertFalse(r.equivalent)
        # 最短分歧在参数 0（深度 1），而不是参数 1。
        self.assertEqual(r.divergence.depth, 1)
        self.assertEqual(r.divergence.steps[1].access, ("param", 0))

    def test_param_count_mismatch(self):
        g1 = TypeGraph(
            {
                "r": {"kind": "Function", "params": ["i"], "result": "i"},
                "i": {"kind": "Int"},
            },
            root="r",
        )
        g2 = TypeGraph(
            {
                "r": {"kind": "Function", "params": ["i", "b"], "result": "i"},
                "i": {"kind": "Int"},
                "b": {"kind": "Bool"},
            },
            root="r",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 0)
        self.assertIn("parameter counts", r.divergence.reason)

    def test_result_position_compared(self):
        # 这是结构相等（不是子类型，不谈变型）：参数同为 Int，
        # 返回 Int vs Bool 在 result 访问子处分歧。
        g1 = TypeGraph(
            {"r": {"kind": "Function", "params": ["i"], "result": "i"},
             "i": {"kind": "Int"}},
            root="r",
        )
        g2 = TypeGraph(
            {"r": {"kind": "Function", "params": ["i"], "result": "b"},
             "i": {"kind": "Int"}, "b": {"kind": "Bool"}},
            root="r",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.steps[-1].access, ("result",))


class RecursionTests(unittest.TestCase):
    def test_self_recursion_equivalent(self):
        # T = Product{next: T, val: Int}，两图仅编号不同。
        def make(root, val_id):
            return TypeGraph(
                {
                    root: {
                        "kind": "Product",
                        "fields": [("next", root), ("val", val_id)],
                    },
                    val_id: {"kind": "Int"},
                },
                root=root,
            )

        g1, g2 = make("t", "i"), make("u", "j")
        r = check_equivalence(g1, g2)
        self.assertTrue(r.equivalent)
        # 根对自环闭合：关系只有 2 对（根对 + Int 对）。
        self.assertEqual(len(r.certificate.pairs), 2)
        self.assertTrue(verify_certificate(r.certificate, g1, g2))

    def test_self_recursion_different_payload(self):
        # T = {next: T, val: Int}  vs U = {next: U, val: Bool}
        g1 = TypeGraph(
            {"t": {"kind": "Product", "fields": [("next", "t"), ("val", "i")]},
             "i": {"kind": "Int"}},
            root="t",
        )
        g2 = TypeGraph(
            {"u": {"kind": "Product", "fields": [("next", "u"), ("val", "b")]},
             "b": {"kind": "Bool"}},
            root="u",
        )
        r = check_equivalence(g1, g2)
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 1)
        self.assertEqual(r.divergence.steps[1].access, ("field", "val"))

    def test_two_node_mutual_recursion_equivalent(self):
        # A = Function(B, A); B = Product(A) 与用不同编号、不同展开形状书写
        # 的等价图（g2 额外共享/复制不影响）。
        g1 = TypeGraph(
            {
                "a": {"kind": "Function", "params": ["b"], "result": "a"},
                "b": {"kind": "Product", "fields": [("x", "a")]},
            },
            root="a",
        )
        # g2：把 b 里的 a 引用改写成一个“语义相同”的新函数节点会改变图，
        # 这里保持互指但重命名并交换字段书写顺序之外的等价结构。
        g2 = TypeGraph(
            {
                "p": {"kind": "Product", "fields": [("x", "q")]},
                "q": {"kind": "Function", "params": ["p"], "result": "q"},
            },
            root="q",
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_two_node_recursion_vs_unrolled_shape_equivalent(self):
        # 双节点互递归 A={h:B}, B={t:A} 与自递归 T={h:{t:T}} 的无限树：
        # 展开分别为 {h:{t:{h:{t:...}}}} 与 {h:{t:{h:{t:...}}}} —— 等价。
        g1 = TypeGraph(
            {
                "a": {"kind": "Product", "fields": [("h", "b")]},
                "b": {"kind": "Product", "fields": [("t", "a")]},
            },
            root="a",
        )
        g2 = TypeGraph(
            {
                "t": {"kind": "Product", "fields": [("h", "m")]},
                "m": {"kind": "Product", "fields": [("t", "t")]},
            },
            root="t",
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_deep_label_difference_shortest_path(self):
        # r -r-> s -r-> w(Sum)：标签 Some/Other 差异发生在深度 2，
        # BFS 必须报告这一最短路径（该图每个节点对只有一条父链）。
        def make(label):
            return TypeGraph(
                {
                    "r": {"kind": "Product", "fields": [("r", "s")]},
                    "s": {"kind": "Product", "fields": [("r", "w")]},
                    "w": {"kind": "Sum", "fields": [(label, "i")]},
                    "i": {"kind": "Int"},
                },
                root="r",
            )

        r = check_equivalence(make("Some"), make("Other"))
        self.assertFalse(r.equivalent)
        self.assertEqual(r.divergence.depth, 2)
        accesses = [st.access for st in r.divergence.steps]
        self.assertEqual(accesses[0], "root")
        self.assertEqual(accesses[1], ("field", "r"))
        self.assertEqual(accesses[2], ("field", "r"))
        self.assertEqual(r.divergence.clashing_pair, ("w", "w"))
        self.assertIn("Some", r.divergence.reason)
        self.assertIn("Other", r.divergence.reason)

    def test_sharing_versus_duplication_indistinguishable(self):
        # g1：两个字段共享同一个 Int 节点；g2：两个字段指向各自的 Int 副本。
        g1 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "i"), ("b", "i")]},
                "i": {"kind": "Int"},
            },
            root="r",
        )
        g2 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "i1"), ("b", "i2")]},
                "i1": {"kind": "Int"},
                "i2": {"kind": "Int"},
            },
            root="r",
        )
        self.assertTrue(are_equivalent(g1, g2))

    def test_infinite_lists_equivalent(self):
        # L = Sum{Nil: Int, Cons: {head: Int, tail: L}} 的自递归 Sum；
        # 字段名是变体标签，两图标签一致即等价（载荷结构两图相同）。
        def make():
            return TypeGraph(
                {
                    "l": {
                        "kind": "Sum",
                        "fields": [
                            ("Nil", "u"),
                            ("Cons", "c"),
                        ],
                    },
                    "u": {"kind": "Int"},
                    "c": {
                        "kind": "Product",
                        "fields": [("head", "i"), ("tail", "l")],
                    },
                    "i": {"kind": "Int"},
                },
                root="l",
            )

        self.assertTrue(are_equivalent(make(), make()))


class BudgetTests(unittest.TestCase):
    def test_budget_exhaustion_is_distinct_from_failure(self):
        g1 = g_int("i")
        g2 = g_int("j")
        with self.assertRaises(BudgetExhaustedError) as cm:
            check_equivalence(g1, g2, budget=0)
        self.assertEqual(cm.exception.budget, 0)

    def test_budget_exhausted_says_nothing_about_equivalence(self):
        # 预算 1 够处理根对（Int~Int 立即等价），预算 0 必耗尽；
        # 再用一个需要多级展开的图验证中途耗尽。
        g1 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "i"), ("b", "j")]},
                "i": {"kind": "Int"},
                "j": {"kind": "Bool"},
            },
            root="r",
        )
        g2 = TypeGraph(
            {
                "r": {"kind": "Product", "fields": [("a", "i"), ("b", "j")]},
                "i": {"kind": "Int"},
                "j": {"kind": "Bool"},
            },
            root="r",
        )
        # 根对 + 2 个子对共需 3 个工作单元；给 1 必须耗尽而不是报不等价。
        with self.assertRaises(BudgetExhaustedError):
            check_equivalence(g1, g2, budget=1)
        # 同图给足预算，正常等价。
        self.assertTrue(are_equivalent(g1, g2))

    def test_budget_argument_validation(self):
        with self.assertRaises(Exception):
            check_equivalence(g_int(), g_int(), budget=-1)
        with self.assertRaises(Exception):
            check_equivalence(g_int(), g_int(), budget=True)
        with self.assertRaises(Exception):
            check_equivalence(g_int(), g_int(), budget=1.5)


class SizeBoundTests(unittest.TestCase):
    """接口上限 300 处的单次边界验证（不做压力测试）。"""

    def test_near_quadratic_reachable_pairs_within_default_budget(self):
        # 乘积图可达对接近 n1*n2：默认预算必须足够，证书必须独立成立。
        n = 300
        g1 = TypeGraph(
            {
                i: {
                    "kind": "Product",
                    "fields": [("a", (i + 1) % n), ("b", (i + 1) % n)],
                }
                for i in range(n)
            },
            root=0,
        )
        g2 = TypeGraph(
            {
                j: {
                    "kind": "Product",
                    "fields": [("a", (j + 1) % n), ("b", j)],
                }
                for j in range(n)
            },
            root=0,
        )
        r = check_equivalence(g1, g2)
        self.assertTrue(r.equivalent)
        self.assertEqual(len(r.certificate.pairs), n * n)
        self.assertEqual(r.work_units, n * n)
        self.assertTrue(verify_certificate(r.certificate, g1, g2))


class CertificateTamperTests(unittest.TestCase):
    def test_missing_child_pair_rejected(self):
        g1 = TypeGraph(
            {"r": {"kind": "Product", "fields": [("a", "i")]}, "i": {"kind": "Int"}},
            root="r",
        )
        g2 = TypeGraph(
            {"r": {"kind": "Product", "fields": [("a", "j")]}, "j": {"kind": "Int"}},
            root="r",
        )
        from rectypes import Certificate

        bad = Certificate(
            roots=("r", "r"),
            pairs=(("r", "r"),),  # 缺 (i, j)
        )
        with self.assertRaises(CertificateInvalid):
            verify_certificate(bad, g1, g2)

    def test_wrong_kind_pair_rejected(self):
        g1 = TypeGraph({"r": {"kind": "Int"}}, root="r")
        g2 = TypeGraph({"r": {"kind": "Bool"}}, root="r")
        from rectypes import Certificate

        bad = Certificate(roots=("r", "r"), pairs=(("r", "r"),))
        with self.assertRaises(CertificateInvalid):
            verify_certificate(bad, g1, g2)


if __name__ == "__main__":
    unittest.main()
