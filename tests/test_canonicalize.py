"""规范化（商图压缩）测试。

独立检查策略（不依赖被测实现内部）：
* 每个合并类内节点的一层标签与“后继类序列”逐条一致（测试内独立重算）；
* 原根与商图根交给原等价检查 ``check_equivalence``/``verify_certificate`` 复核；
* 输入编号任意置换后，规范化字节表示逐字节相同。
"""

from __future__ import annotations

import random
import unittest

from recursive_types import (
    BoolNode,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SumNode,
    TypeGraph,
    are_equivalent,
    canonicalize,
    check_equivalence,
    verify_certificate,
)
from recursive_types.model import Node


# --------------------------------------------------------------------------- #
# 测试内独立辅助
# --------------------------------------------------------------------------- #


def local_label(node: Node) -> tuple:
    """独立重算的一层标签（种类 + 局部结构）。"""
    k = node.kind
    if k in ("Int", "Bool"):
        return (k,)
    if k in ("Product", "Sum"):
        return (k, tuple(sorted(f.name for f in node.fields)))
    return (k, len(node.params))


def ordered_successors(node: Node) -> tuple[int, ...]:
    """独立重算的约定顺序后继：字段按名；参数按次序，返回最后。"""
    k = node.kind
    if k in ("Int", "Bool"):
        return ()
    if k in ("Product", "Sum"):
        return tuple(f.target for f in sorted(node.fields, key=lambda f: f.name))
    return (*node.params, node.result)


def assert_classes_consistent(
    test: unittest.TestCase, g: TypeGraph, old_to_new: tuple[int, ...]
) -> None:
    """独立检查：每个合并类内节点的标签和后继类一致。"""
    classes: dict[int, list[int]] = {}
    for i, c in enumerate(old_to_new):
        if c >= 0:
            classes.setdefault(c, []).append(i)
    for c, members in classes.items():
        first = members[0]
        label = local_label(g[first])
        succ_classes = tuple(
            old_to_new[s] for s in ordered_successors(g[first])
        )
        for m in members[1:]:
            test.assertEqual(
                local_label(g[m]), label, f"class {c}: label of node {m}"
            )
            test.assertEqual(
                tuple(old_to_new[s] for s in ordered_successors(g[m])),
                succ_classes,
                f"class {c}: successor classes of node {m}",
            )


def permute_graph(g: TypeGraph, perm: list[int]) -> TypeGraph:
    """按 ``perm``（旧编号 -> 新编号）重排图，语义不变。"""
    n = len(g)
    new_nodes: list[Node] = [IntNode()] * n
    for old in range(n):
        node = g[old]
        k = node.kind
        if k == "Int":
            new_nodes[perm[old]] = IntNode()
        elif k == "Bool":
            new_nodes[perm[old]] = BoolNode()
        elif k in ("Product", "Sum"):
            fields = tuple(
                Field(f.name, perm[f.target]) for f in node.fields
            )
            if k == "Product":
                new_nodes[perm[old]] = ProductNode(fields)
            else:
                new_nodes[perm[old]] = SumNode(fields)
        else:
            new_nodes[perm[old]] = FunctionNode(
                tuple(perm[p] for p in node.params), perm[node.result]
            )
    return TypeGraph(new_nodes, perm[g.root])


# --------------------------------------------------------------------------- #
# 固定图样
# --------------------------------------------------------------------------- #


def self_loop_graph() -> TypeGraph:
    """μX. X -> Int：单节点自环。"""
    return TypeGraph([FunctionNode((0,), 1), IntNode()], root=0)


def two_node_cycle_graph() -> TypeGraph:
    """μX. X -> Int：双节点互指环（展开与自环相同）。"""
    return TypeGraph(
        [FunctionNode((1,), 2), FunctionNode((0,), 2), IntNode()], root=0
    )


def mutual_record_graph() -> TypeGraph:
    """互递归记录：A = {next: B, v: Int}, B = {next: A, v: Int}。"""
    return TypeGraph(
        [
            ProductNode((Field("next", 1), Field("v", 2))),  # 0: A（根）
            ProductNode((Field("next", 0), Field("v", 2))),  # 1: B
            IntNode(),                                       # 2
        ],
        root=0,
    )


def mutual_record_copied_graph() -> TypeGraph:
    """同一互递归记录：子图复制成 4 节点环 + 两个 Int 副本，字段顺序打乱。"""
    return TypeGraph(
        [
            IntNode(),                                                     # 0
            ProductNode((Field("v", 0), Field("next", 2))),                # 1
            ProductNode((Field("next", 3), Field("v", 4))),                # 2
            ProductNode((Field("v", 4), Field("next", 1))),                # 3
            IntNode(),                                                     # 4
            ProductNode((Field("next", 1), Field("v", 0))),                # 5: 根
        ],
        root=5,
    )


class CanonicalizeBasicTests(unittest.TestCase):
    def test_self_loop_vs_two_node_cycle_same_form(self) -> None:
        c1 = canonicalize(self_loop_graph())
        c2 = canonicalize(two_node_cycle_graph())
        self.assertEqual(c1.to_bytes(), c2.to_bytes())
        # 商图即单节点自环：F(0)->1 + Int。
        self.assertEqual(len(c1.graph), 2)
        self.assertEqual(c1.root, 0)
        self.assertEqual(c1.graph.root, 0)
        node0 = c1.graph[0]
        assert isinstance(node0, FunctionNode)
        self.assertEqual(node0.params, (0,))
        self.assertEqual(node0.result, 1)

    def test_mutual_record_vs_copied_same_form(self) -> None:
        c1 = canonicalize(mutual_record_graph())
        c2 = canonicalize(mutual_record_copied_graph())
        self.assertEqual(c1.to_bytes(), c2.to_bytes())
        # 互递归两节点展开相同，应合并为一个类。
        self.assertEqual(len(c1.graph), 2)
        self.assertEqual(c2.old_to_new[1], c2.old_to_new[2])
        self.assertEqual(c2.old_to_new[1], c2.old_to_new[3])
        self.assertEqual(c2.old_to_new[1], c2.old_to_new[5])
        self.assertEqual(c2.old_to_new[0], c2.old_to_new[4])

    def test_cycle_length_three_same_unfolding(self) -> None:
        """3 环 P{a:} 与自环展开相同，应得到同一表示。"""
        loop = TypeGraph([ProductNode((Field("a", 0),))], root=0)
        cycle3 = TypeGraph(
            [
                ProductNode((Field("a", 1),)),
                ProductNode((Field("a", 2),)),
                ProductNode((Field("a", 0),)),
            ],
            root=0,
        )
        self.assertEqual(
            canonicalize(loop).to_bytes(), canonicalize(cycle3).to_bytes()
        )
        self.assertEqual(len(canonicalize(cycle3).graph), 1)

    def test_shared_vs_copied_subgraph_same_form(self) -> None:
        """共享一个子节点与复制同构子节点不区分。"""
        shared = TypeGraph(
            [
                ProductNode((Field("x", 1), Field("y", 1))),  # 0: 根，共享 1
                FunctionNode((2,), 2),                        # 1
                IntNode(),                                    # 2
            ],
            root=0,
        )
        copied = TypeGraph(
            [
                IntNode(),                                    # 0
                FunctionNode((0,), 0),                        # 1: 副本 a
                FunctionNode((0,), 0),                        # 2: 副本 b
                ProductNode((Field("y", 2), Field("x", 1))),  # 3: 根
            ],
            root=3,
        )
        self.assertEqual(
            canonicalize(shared).to_bytes(), canonicalize(copied).to_bytes()
        )

    def test_function_param_swap_not_merged(self) -> None:
        """函数参数按次序对应：交换参数位置必须得到不同表示。"""
        g1 = TypeGraph(
            [FunctionNode((1, 2), 1), IntNode(), BoolNode()], root=0
        )
        g2 = TypeGraph(
            [FunctionNode((2, 1), 1), IntNode(), BoolNode()], root=0
        )
        self.assertFalse(are_equivalent(g1, g2))
        self.assertNotEqual(
            canonicalize(g1).to_bytes(), canonicalize(g2).to_bytes()
        )

    def test_same_local_label_but_not_equivalent_not_merged(self) -> None:
        """局部标签相同但展开不同，不得合并。

        A = P{a: A, b: Int}（b 是有限 Int）；
        B = P{a: B, b: B}（b 无限深入）。两者一层标签都是 (Product, {a,b})。
        """
        ga = TypeGraph(
            [ProductNode((Field("a", 0), Field("b", 1))), IntNode()], root=0
        )
        gb = TypeGraph(
            [ProductNode((Field("a", 0), Field("b", 0)))], root=0
        )
        self.assertFalse(are_equivalent(ga, gb))
        ca, cb = canonicalize(ga), canonicalize(gb)
        self.assertNotEqual(ca.to_bytes(), cb.to_bytes())
        self.assertEqual(len(ca.graph), 2)
        self.assertEqual(len(cb.graph), 1)

    def test_unreachable_garbage_ignored(self) -> None:
        """不可达垃圾不影响表示；映射中标记为 -1。"""
        clean = mutual_record_graph()
        dirty = TypeGraph(
            [
                ProductNode((Field("next", 1), Field("v", 2))),  # 0: A（根）
                ProductNode((Field("next", 0), Field("v", 2))),  # 1: B
                IntNode(),                                       # 2
                SumNode((Field("junk", 3),)),                    # 3: 垃圾
                FunctionNode((4,), 4),                           # 4: 垃圾自环
            ],
            root=0,
        )
        c_clean = canonicalize(clean)
        c_dirty = canonicalize(dirty)
        self.assertEqual(c_clean.to_bytes(), c_dirty.to_bytes())
        self.assertEqual(c_dirty.old_to_new[3], -1)
        self.assertEqual(c_dirty.old_to_new[4], -1)
        self.assertEqual(c_dirty.old_to_new[:3], c_clean.old_to_new)

    def test_old_to_new_mapping_and_root(self) -> None:
        """映射语义：可达旧节点 i 与商图中 old_to_new[i] 等价（原检查复核）。"""
        g = mutual_record_copied_graph()
        c = canonicalize(g)
        self.assertEqual(c.old_to_new[g.root], c.root)
        for i, target in enumerate(c.old_to_new):
            if target < 0:
                continue
            result = check_equivalence(g, c.graph, root1=i, root2=target)
            self.assertIsInstance(result, EquivalenceCertificate, f"node {i}")

    def test_quotient_root_equivalent_to_original_root(self) -> None:
        """原根与商图根交给原等价检查，证书可被独立复核。"""
        for build in (
            self_loop_graph,
            two_node_cycle_graph,
            mutual_record_graph,
            mutual_record_copied_graph,
        ):
            g = build()
            c = canonicalize(g)
            result = check_equivalence(g, c.graph, root2=c.root)
            self.assertIsInstance(result, EquivalenceCertificate)
            assert isinstance(result, EquivalenceCertificate)
            self.assertTrue(verify_certificate(g, c.graph, result))

    def test_class_consistency_independent(self) -> None:
        for build in (
            self_loop_graph,
            two_node_cycle_graph,
            mutual_record_graph,
            mutual_record_copied_graph,
        ):
            g = build()
            c = canonicalize(g)
            assert_classes_consistent(self, g, c.old_to_new)

    def test_permutation_invariant_bytes(self) -> None:
        """输入编号任意置换后字节序列相同。"""
        rng = random.Random(20260922)
        for build in (
            two_node_cycle_graph,
            mutual_record_copied_graph,
        ):
            g = build()
            expected = canonicalize(g).to_bytes()
            for _ in range(20):
                perm = list(range(len(g)))
                rng.shuffle(perm)
                shuffled = permute_graph(g, perm)
                self.assertEqual(canonicalize(shuffled).to_bytes(), expected)

    def test_root_override(self) -> None:
        """root= 覆盖：同一图内不同起点给出各自的商图。"""
        g = mutual_record_graph()
        c0 = canonicalize(g, root=0)
        c1 = canonicalize(g, root=1)
        # A 与 B 展开相同，两个起点的商图应逐字节相同。
        self.assertEqual(c0.to_bytes(), c1.to_bytes())
        self.assertEqual(c1.old_to_new[1], c1.root)

    def test_acyclic_matches_reference_unfold_shape(self) -> None:
        """无环图：商图节点数 == 展开树中去重子树数（独立参考口径）。"""
        g = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),  # 0: 根
                FunctionNode((3,), 3),                        # 1
                FunctionNode((4,), 4),                        # 2: 与 1 同构
                IntNode(),                                    # 3
                IntNode(),                                    # 4: 与 3 同构
            ],
            root=0,
        )
        c = canonicalize(g)
        # 去重后：根、F、Int 共 3 类。
        self.assertEqual(len(c.graph), 3)
        self.assertEqual(c.old_to_new, (0, 1, 1, 2, 2))

    def test_invalid_arguments_rejected(self) -> None:
        g = self_loop_graph()
        with self.assertRaises(TypeError):
            canonicalize("not a graph")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            canonicalize(g, root=True)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            canonicalize(g, root=0.0)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            canonicalize(g, root=7)
        with self.assertRaises(ValueError):
            canonicalize(g, root=-1)


if __name__ == "__main__":
    unittest.main()
