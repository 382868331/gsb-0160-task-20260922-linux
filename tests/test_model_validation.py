"""数据结构与错误语义测试。"""

from __future__ import annotations

import unittest

from recursive_types import (
    ArityError,
    DanglingEdgeError,
    DuplicateFieldError,
    Field,
    FunctionNode,
    GraphSizeError,
    IntNode,
    InvalidNodeError,
    InvalidRootError,
    MAX_NODES,
    ProductNode,
    SumNode,
    TypeGraph,
)


def loc_of(exc: Exception) -> str:
    return str(exc).split(":")[0]


class ValidationTests(unittest.TestCase):
    def test_minimal_valid_graphs(self) -> None:
        g = TypeGraph([IntNode()], 0)
        self.assertEqual(len(g), 1)
        self.assertEqual(g.root, 0)

    def test_bool_rejected_as_index(self) -> None:
        with self.assertRaises(InvalidNodeError) as cm:
            TypeGraph([IntNode(), IntNode(), ProductNode((Field("a", True),))], 2)
        self.assertIn("node 2", str(cm.exception))
        self.assertIn("bool", str(cm.exception))

    def test_float_rejected_as_index_nan_inf_style(self) -> None:
        # 数值参数只接受严格 int；float（含 NaN/Inf 这类）在类型层面即被拒绝。
        for bad in (1.0, float("nan"), float("inf"), -0.0):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidNodeError):
                    TypeGraph(
                        [IntNode(), ProductNode((Field("a", bad),))], 1
                    )

    def test_bool_rejected_as_root(self) -> None:
        with self.assertRaises(InvalidRootError):
            TypeGraph([IntNode()], True)  # type: ignore[arg-type]

    def test_dangling_field_edge(self) -> None:
        with self.assertRaises(DanglingEdgeError) as cm:
            TypeGraph([ProductNode((Field("a", 5),))], 0)
        self.assertIn("node 0", str(cm.exception))
        self.assertIn("points to 5", str(cm.exception))

    def test_dangling_function_result(self) -> None:
        with self.assertRaises(DanglingEdgeError):
            TypeGraph([IntNode(), FunctionNode((0,), 7)], 1)

    def test_dangling_function_param(self) -> None:
        with self.assertRaises(DanglingEdgeError) as cm:
            TypeGraph([IntNode(), FunctionNode((3,), 0)], 1)
        self.assertIn("param 0", str(cm.exception))

    def test_negative_index_is_dangling(self) -> None:
        with self.assertRaises(DanglingEdgeError):
            TypeGraph([ProductNode((Field("a", -1),))], 0)

    def test_arity_leaf_with_carry_is_not_even_constructible(self) -> None:
        # 叶子节点结构上没有边字段；构造参数错误属于 Python 层 TypeError。
        with self.assertRaises(TypeError):
            IntNode(fields=())  # type: ignore[call-arg]

    def test_arity_empty_product(self) -> None:
        with self.assertRaises(ArityError) as cm:
            TypeGraph([ProductNode(())], 0)
        self.assertIn("at least 1 field", str(cm.exception))

    def test_arity_empty_sum(self) -> None:
        with self.assertRaises(ArityError):
            TypeGraph([SumNode(())], 0)

    def test_arity_function_no_params(self) -> None:
        with self.assertRaises(ArityError) as cm:
            TypeGraph([IntNode(), FunctionNode((), 0)], 1)
        self.assertIn("at least 1 ordered parameter", str(cm.exception))

    def test_duplicate_field_name(self) -> None:
        with self.assertRaises(DuplicateFieldError) as cm:
            TypeGraph(
                [
                    IntNode(),
                    ProductNode(
                        (Field("a", 0), Field("a", 0))
                    ),
                ],
                1,
            )
        self.assertIn("duplicate field name 'a'", str(cm.exception))

    def test_empty_field_name(self) -> None:
        with self.assertRaises(InvalidNodeError):
            TypeGraph([IntNode(), ProductNode((Field("", 0),))], 1)

    def test_root_out_of_range(self) -> None:
        with self.assertRaises(InvalidRootError):
            TypeGraph([IntNode()], 1)

    def test_size_bounds(self) -> None:
        with self.assertRaises(GraphSizeError):
            TypeGraph([], 0)
        # 300 合法（chain），301 在构造期拒绝。
        nodes_300 = [IntNode()]
        for _ in range(MAX_NODES - 1):
            nodes_300.append(ProductNode((Field("t", len(nodes_300) - 1),)))
        g = TypeGraph(nodes_300, MAX_NODES - 1)
        self.assertEqual(len(g), MAX_NODES)
        nodes_301 = nodes_300 + [
            ProductNode((Field("t", MAX_NODES - 1),))
        ]
        with self.assertRaises(GraphSizeError):
            TypeGraph(nodes_301, MAX_NODES)

    def test_wrong_python_type_nodes(self) -> None:
        with self.assertRaises(InvalidNodeError):
            TypeGraph([42], 0)  # type: ignore[list-item]
        with self.assertRaises(InvalidNodeError):
            TypeGraph([("Int",)], 0)  # type: ignore[list-item]

    def test_field_entry_wrong_type(self) -> None:
        with self.assertRaises(InvalidNodeError):
            TypeGraph(
                [IntNode(), ProductNode((("a", 0),))], 1  # type: ignore[arg-type]
            )

    def test_defensive_copy(self) -> None:
        nodes = [IntNode(), ProductNode((Field("a", 0),))]
        g = TypeGraph(nodes, 1)
        nodes.append(IntNode())  # 事后修改入参不影响已构造的图
        self.assertEqual(len(g), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
