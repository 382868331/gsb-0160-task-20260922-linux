"""结构校验与错误语义测试。"""

import math
import unittest

from rectypes import (
    ArityError,
    BudgetExhaustedError,
    DanglingEdgeError,
    DuplicateFieldError,
    GraphTooLargeError,
    InvalidNodeError,
    TypeGraph,
    UnreachableNodeError,
)
from rectypes.model import MAX_NODES


def int_node():
    return {"kind": "Int"}


class ValidationTests(unittest.TestCase):
    def test_atomic_graph_ok(self):
        g = TypeGraph({"r": int_node()}, root="r")
        self.assertEqual(g.root, "r")
        self.assertEqual(len(g), 1)

    def test_dangling_product_field(self):
        with self.assertRaises(DanglingEdgeError) as cm:
            TypeGraph(
                {"r": {"kind": "Product", "fields": [("a", "ghost")]}},
                root="r",
            )
        self.assertIn("ghost", str(cm.exception))
        self.assertEqual(cm.exception.target, "ghost")

    def test_dangling_function_param_and_result(self):
        with self.assertRaises(DanglingEdgeError):
            TypeGraph(
                {"r": {"kind": "Function", "params": ["x"], "result": "r"}},
                root="r",
            )
        with self.assertRaises(DanglingEdgeError):
            TypeGraph(
                {"r": {"kind": "Function", "params": ["r"], "result": "y"}},
                root="r",
            )

    def test_dangling_root(self):
        with self.assertRaises(DanglingEdgeError):
            TypeGraph({"r": int_node()}, root="nope")

    def test_arity_empty_product(self):
        with self.assertRaises(ArityError):
            TypeGraph({"r": {"kind": "Product", "fields": []}}, root="r")

    def test_arity_empty_sum(self):
        with self.assertRaises(ArityError):
            TypeGraph({"r": {"kind": "Sum", "fields": []}}, root="r")

    def test_arity_function_no_params(self):
        with self.assertRaises(ArityError):
            TypeGraph(
                {"r": {"kind": "Function", "params": [], "result": "r"}},
                root="r",
            )

    def test_arity_function_missing_result(self):
        with self.assertRaises(ArityError):
            TypeGraph(
                {"r": {"kind": "Function", "params": ["r"]}}, root="r"
            )

    def test_duplicate_field_names(self):
        with self.assertRaises(DuplicateFieldError) as cm:
            TypeGraph(
                {
                    "r": {
                        "kind": "Product",
                        "fields": [("a", "i"), ("a", "j")],
                    },
                    "i": int_node(),
                    "j": int_node(),
                },
                root="r",
            )
        self.assertEqual(cm.exception.field_name, "a")

    def test_unreachable_node_rejected(self):
        with self.assertRaises(UnreachableNodeError) as cm:
            TypeGraph(
                {"r": int_node(), "orphan": {"kind": "Bool"}}, root="r"
            )
        self.assertEqual(cm.exception.unreachable, ["orphan"])

    # 自环让整图只有一个节点且根可达，用于独立验证 Function 元数之外的合法性。
    def test_self_referential_function_ok(self):
        g = TypeGraph(
            {"r": {"kind": "Function", "params": ["r"], "result": "r"}},
            root="r",
        )
        self.assertEqual(len(g), 1)

    def test_unknown_kind(self):
        with self.assertRaises(InvalidNodeError):
            TypeGraph({"r": {"kind": "String"}}, root="r")

    def test_node_not_mapping(self):
        with self.assertRaises(InvalidNodeError):
            TypeGraph({"r": ("Int",)}, root="r")

    def test_field_pair_bad_shape(self):
        with self.assertRaises(InvalidNodeError):
            TypeGraph(
                {"r": {"kind": "Product", "fields": [("a",)]}}, root="r"
            )

    def test_bool_rejected_as_node_id(self):
        # bool 是 int 的子类型，必须显式拒绝，不得静默当作 1。
        with self.assertRaises(InvalidNodeError):
            TypeGraph({True: int_node()}, root=True)
        with self.assertRaises(InvalidNodeError):
            TypeGraph(
                {"r": {"kind": "Product", "fields": [("a", True)]}},
                root="r",
            )

    def test_int_ids_allowed(self):
        # 非 bool 的 int 标识合法；节点编号不参与语义（见 checker 测试）。
        g = TypeGraph(
            {
                0: {"kind": "Function", "params": [1], "result": 1},
                1: int_node(),
            },
            root=0,
        )
        self.assertEqual(g.root, 0)

    def test_float_id_rejected(self):
        with self.assertRaises(InvalidNodeError):
            TypeGraph({1.0: int_node()}, root=1.0)

    def test_non_finite_numbers_rejected(self):
        # 本领域数值入口只有节点标识与预算；浮点（含 NaN/Inf）一律拒绝，
        # 不会被当作 int 静默接受。
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(InvalidNodeError):
                TypeGraph({bad: {"kind": "Int"}}, root=bad)
            with self.assertRaises(InvalidNodeError):
                TypeGraph(
                    {"r": {"kind": "Product", "fields": [("a", bad)]},
                     "i": {"kind": "Int"}},
                    root="r",
                )

    def test_size_limit_boundary(self):
        nodes = {f"n{i}": int_node() for i in range(MAX_NODES)}
        # 300 个互相独立的原子节点不可达 -> 先改成链以测上限边界本身。
        nodes = {
            "n0": {"kind": "Product", "fields": [("a", "n1")]},
        }
        for i in range(1, MAX_NODES):
            nxt = f"n{i + 1}" if i + 1 < MAX_NODES else "n0"
            nodes[f"n{i}"] = {"kind": "Product", "fields": [("a", nxt)]}
        g = TypeGraph(nodes, root="n0")
        self.assertEqual(len(g), MAX_NODES)

        too_many = dict(nodes)
        too_many["extra"] = int_node()
        with self.assertRaises(GraphTooLargeError):
            TypeGraph(too_many, root="n0")

    def test_failed_construction_leaves_nothing(self):
        # 构造失败时调用方拿不到半成品对象。
        g = None
        with self.assertRaises(DanglingEdgeError):
            g = TypeGraph(
                {"r": {"kind": "Sum", "fields": [("z", "missing")]}},
                root="r",
            )
        self.assertIsNone(g)

        # 不可达节点也在对象创建前报错，不会得到带“部分节点”的图。
        g2 = object()
        with self.assertRaises(UnreachableNodeError):
            g2 = TypeGraph(
                {"r": int_node(), "orphan": {"kind": "Bool"}}, root="r"
            )
        self.assertNotIsInstance(g2, TypeGraph)

    def test_input_mapping_not_mutated(self):
        raw = {
            "r": {"kind": "Product", "fields": [("a", "i")]},
            "i": int_node(),
        }
        import copy

        snapshot = copy.deepcopy(raw)
        TypeGraph(raw, root="r")
        self.assertEqual(raw, snapshot)


if __name__ == "__main__":
    unittest.main()
