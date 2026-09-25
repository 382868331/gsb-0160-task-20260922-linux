"""规范化（canonicalize）测试：双模拟合并、确定编号、置换不变性。

独立复核策略（不依赖被测实现自证）：
* 每个合并类内节点的标签与后继类由测试逐对独立检查；
* 原根与商图根交给既有 ``check_equivalence``/``verify_certificate`` 判定；
* 输入编号任意置换后比较 ``to_bytes()`` 字节序列；
* 无环图与 ``tests.reference_unfold`` 的展开树参考交叉核对。
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
    canonicalize,
    check_equivalence,
    verify_certificate,
)
from recursive_types.canonicalize import CanonicalForm
from recursive_types.model import Node

from tests.reference_unfold import reference_equivalent
from tests.test_equivalence import random_dag


def permute_graph(
    nodes: list[Node], root: int, perm: list[int]
) -> tuple[list[Node], int]:
    """按 ``perm``（新下标 = perm[旧下标]）重排节点并重映射所有边。"""
    n = len(nodes)
    out: list[Node | None] = [None] * n
    for i, node in enumerate(nodes):
        j = perm[i]
        if isinstance(node, (ProductNode, SumNode)):
            out[j] = type(node)(
                tuple(Field(f.name, perm[f.target]) for f in node.fields)
            )
        elif isinstance(node, FunctionNode):
            out[j] = FunctionNode(
                tuple(perm[p] for p in node.params), perm[node.result]
            )
        else:
            out[j] = node
    return out, perm[root]  # type: ignore[return-value]


class CanonicalizeStructureTests(unittest.TestCase):
    def test_self_loop_vs_two_node_cycle_same_form(self) -> None:
        # T = T -> Int：单自环 vs 双节点互指环，展开树相同。
        g1 = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        g2 = TypeGraph(
            [
                FunctionNode((2,), 1),
                IntNode(),
                FunctionNode((0,), 1),
            ],
            0,
        )
        c1, c2 = canonicalize(g1), canonicalize(g2)
        self.assertEqual(c1.to_bytes(), c2.to_bytes())
        self.assertEqual(len(c1.graph), 2)  # 合并到 Function 类 + Int 类
        self.assertEqual(c2.mapping, (0, 1, 0))  # 两个 Function 旧节点同类

    def test_mutually_recursive_records_collapse(self) -> None:
        # T = P{a: U, b: Int}; U = S{x: T, y: Bool}
        # 右图把 T/U 各复制一份交叉互指（4 节点互递归记录），展开相同。
        g1 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                BoolNode(),
            ],
            0,
        )
        # T1->U1->T2->U2->T1 交叉互指，展开与 g1 的 2-环相同。
        g2 = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),   # T1
                SumNode((Field("x", 3), Field("y", 5))),       # U1
                IntNode(),
                ProductNode((Field("b", 2), Field("a", 4))),   # T2（字段乱序）
                SumNode((Field("y", 5), Field("x", 0))),       # U2
                BoolNode(),
            ],
            3,
        )
        c1, c2 = canonicalize(g1), canonicalize(g2)
        self.assertEqual(c1.to_bytes(), c2.to_bytes())
        self.assertEqual(len(c1.graph), 4)  # T、U、Int、Bool 四类
        # 两个 T 副本与两个 U 副本必须各自同类。
        self.assertEqual(c2.mapping[0], c2.mapping[3])
        self.assertEqual(c2.mapping[1], c2.mapping[4])

    def test_function_param_swap_not_merged(self) -> None:
        # 参数按次序对应：交换参数位置的类型不同，字节序列必须不同。
        g1 = TypeGraph([IntNode(), BoolNode(), FunctionNode((0, 1), 0)], 2)
        g2 = TypeGraph([IntNode(), BoolNode(), FunctionNode((1, 0), 0)], 2)
        self.assertNotEqual(
            canonicalize(g1).to_bytes(), canonicalize(g2).to_bytes()
        )

    def test_same_local_label_not_merged_when_unfolding_differs(self) -> None:
        # 节点 0 与 1 局部标签完全相同（都是 P{a: ...}），
        # 但 0 = P{a: P{a: Int}}、1 = P{a: Int} 展开不同，不得合并。
        g = TypeGraph(
            [
                ProductNode((Field("a", 1),)),
                ProductNode((Field("a", 2),)),
                IntNode(),
            ],
            0,
        )
        form = canonicalize(g)
        self.assertEqual(len(form.graph), 3)
        self.assertNotEqual(form.mapping[0], form.mapping[1])

    def test_unreachable_garbage_dropped(self) -> None:
        base = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        dirty = TypeGraph(
            [
                FunctionNode((0,), 1),
                IntNode(),
                BoolNode(),                            # 不可达
                SumNode((Field("z", 2),)),             # 不可达，且自指成环
                ProductNode((Field("g", 3),)),         # 不可达
            ],
            0,
        )
        c_base, c_dirty = canonicalize(base), canonicalize(dirty)
        self.assertEqual(c_base.to_bytes(), c_dirty.to_bytes())
        self.assertEqual(c_dirty.mapping, (0, 1, None, None, None))
        self.assertEqual(len(c_dirty.graph), 2)

    def test_sharing_vs_duplication_same_form(self) -> None:
        shared = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        duplicated = TypeGraph(
            [
                IntNode(),
                IntNode(),
                ProductNode((Field("a", 0), Field("b", 1))),
            ],
            2,
        )
        self.assertEqual(
            canonicalize(shared).to_bytes(),
            canonicalize(duplicated).to_bytes(),
        )

    def test_cycle_length_difference_same_form(self) -> None:
        # μX. P{a: X}：环长 1 / 2 / 3 展开相同。
        g1 = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g2 = TypeGraph(
            [ProductNode((Field("a", 1),)), ProductNode((Field("a", 0),))], 0
        )
        g3 = TypeGraph(
            [
                ProductNode((Field("a", 1),)),
                ProductNode((Field("a", 2),)),
                ProductNode((Field("a", 0),)),
            ],
            0,
        )
        b = canonicalize(g1).to_bytes()
        self.assertEqual(canonicalize(g2).to_bytes(), b)
        self.assertEqual(canonicalize(g3).to_bytes(), b)
        self.assertEqual(len(canonicalize(g1).graph), 1)

    def test_invalid_input_rejected(self) -> None:
        with self.assertRaises(TypeError):
            canonicalize([IntNode()])  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            canonicalize(None)  # type: ignore[arg-type]


class CanonicalizeIndependentCheckTests(unittest.TestCase):
    """不依赖被测实现自证的独立复核。"""

    def assert_classes_consistent(
        self, g: TypeGraph, form: CanonicalForm
    ) -> None:
        """逐类独立检查：类内节点标签一致、后继类一致。"""
        for members in form.classes:
            self.assertGreater(len(members), 0)
            for i in members:
                for j in members:
                    ni, nj = g[i], g[j]
                    self.assertEqual(ni.kind, nj.kind)
                    if isinstance(ni, (ProductNode, SumNode)):
                        assert isinstance(nj, type(ni))
                        succ_i = {
                            f.name: form.mapping[f.target] for f in ni.fields
                        }
                        succ_j = {
                            f.name: form.mapping[f.target] for f in nj.fields
                        }
                        self.assertEqual(succ_i, succ_j)
                    elif isinstance(ni, FunctionNode):
                        assert isinstance(nj, FunctionNode)
                        self.assertEqual(len(ni.params), len(nj.params))
                        self.assertEqual(
                            [form.mapping[p] for p in ni.params],
                            [form.mapping[p] for p in nj.params],
                        )
                        self.assertEqual(
                            form.mapping[ni.result], form.mapping[nj.result]
                        )

    def assert_root_equivalent_to_quotient(
        self, g: TypeGraph, form: CanonicalForm
    ) -> None:
        """原根与商图根交给既有等价检查独立判定。"""
        result = check_equivalence(g, form.graph, root1=g.root, root2=0)
        self.assertIsInstance(result, EquivalenceCertificate)
        assert isinstance(result, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g, form.graph, result))

    def assert_mapping_shape(self, g: TypeGraph, form: CanonicalForm) -> None:
        self.assertEqual(len(form.mapping), len(g))
        self.assertEqual(form.mapping[g.root], 0)  # 根恒为 0
        self.assertEqual(form.graph.root, 0)
        for i, m in enumerate(form.mapping):
            if m is not None:
                self.assertIn(i, form.classes[m])
        # classes 覆盖全部可达旧节点，且与 mapping 互逆。
        flattened = sorted(i for cls in form.classes for i in cls)
        self.assertEqual(
            flattened, sorted(i for i, m in enumerate(form.mapping)
                              if m is not None)
        )

    def check_graph(self, g: TypeGraph) -> CanonicalForm:
        form = canonicalize(g)
        self.assert_mapping_shape(g, form)
        self.assert_classes_consistent(g, form)
        self.assert_root_equivalent_to_quotient(g, form)
        return form

    def test_handbuilt_recursive_graphs(self) -> None:
        graphs = [
            TypeGraph([FunctionNode((0,), 1), IntNode()], 0),
            TypeGraph([ProductNode((Field("a", 0),))], 0),
            TypeGraph(
                [
                    ProductNode((Field("a", 1), Field("b", 2))),
                    SumNode((Field("x", 0), Field("y", 3))),
                    IntNode(),
                    BoolNode(),
                ],
                0,
            ),
            TypeGraph(
                [
                    FunctionNode((0, 2), 1),
                    IntNode(),
                    FunctionNode((2, 0), 3),
                    BoolNode(),
                ],
                0,
            ),
        ]
        for g in graphs:
            with self.subTest(g=repr(g)):
                self.check_graph(g)

    def test_random_dags_independent_checks(self) -> None:
        rng = random.Random(916)
        for _ in range(20):
            n = rng.randint(1, 14)
            g = TypeGraph(random_dag(rng, n), n - 1)
            self.check_graph(g)

    def test_random_dags_cross_checked_with_unfold_reference(self) -> None:
        # 无环图：字节序列相同 iff 独立展开参考判等价。
        rng = random.Random(20260922)
        graphs: list[TypeGraph] = []
        for _ in range(16):
            n = rng.randint(1, 10)
            graphs.append(TypeGraph(random_dag(rng, n), n - 1))
        keys = [canonicalize(g).to_bytes() for g in graphs]
        positive = negative = 0
        for i, g1 in enumerate(graphs):
            for j, g2 in enumerate(graphs):
                expected = reference_equivalent(g1, g1.root, g2, g2.root)
                self.assertEqual(
                    keys[i] == keys[j],
                    expected,
                    msg=f"DAG pair {i},{j}: canonical bytes disagree "
                    f"with unfold reference",
                )
                if expected:
                    positive += 1
                else:
                    negative += 1
        self.assertGreater(positive, 0)
        self.assertGreater(negative, 0)


class CanonicalizePermutationTests(unittest.TestCase):
    """输入编号任意置换后，输出字节序列必须相同。"""

    BASE_GRAPHS: list[tuple[list[Node], int]] = [
        # 自环函数
        ([FunctionNode((0,), 1), IntNode()], 0),
        # 互递归记录 + 不可达垃圾
        (
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                BoolNode(),
                SumNode((Field("junk", 4),)),
            ],
            0,
        ),
        # 双节点环 + 共享叶子
        (
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                ProductNode((Field("a", 0), Field("b", 2))),
                IntNode(),
            ],
            0,
        ),
        # 函数嵌套（参数次序敏感）
        (
            [
                FunctionNode((1, 2), 3),
                IntNode(),
                FunctionNode((1,), 2),
                BoolNode(),
            ],
            0,
        ),
    ]

    def test_permutation_invariance(self) -> None:
        rng = random.Random(4242)
        for nodes, root in self.BASE_GRAPHS:
            base = canonicalize(TypeGraph(nodes, root)).to_bytes()
            for _ in range(8):
                perm = list(range(len(nodes)))
                rng.shuffle(perm)
                pnodes, proot = permute_graph(nodes, root, perm)
                got = canonicalize(TypeGraph(pnodes, proot)).to_bytes()
                self.assertEqual(got, base, msg=f"perm={perm}")

    def test_permuted_mapping_still_consistent(self) -> None:
        # 置换改变 mapping/classes（它们含旧编号），但商图字节不变；
        # 且置换后的 mapping 仍通过独立一致性检查。
        nodes, root = self.BASE_GRAPHS[1]
        perm = [3, 0, 4, 2, 1]
        pnodes, proot = permute_graph(nodes, root, perm)
        g = TypeGraph(pnodes, proot)
        form = canonicalize(g)
        self.assertEqual(
            form.to_bytes(), canonicalize(TypeGraph(nodes, root)).to_bytes()
        )
        CanonicalizeIndependentCheckTests.assert_mapping_shape(
            self, g, form
        )
        CanonicalizeIndependentCheckTests.assert_classes_consistent(
            self, g, form
        )
        CanonicalizeIndependentCheckTests.assert_root_equivalent_to_quotient(
            self, g, form
        )


class CanonicalizeScaleTests(unittest.TestCase):
    def test_300_node_big_cycle_collapses(self) -> None:
        # 299 个 Function 节点组成大环 + Int：与单自环同表示。
        small = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        big: list[Node] = []
        for i in range(299):
            nxt = i + 1 if i < 298 else 0
            big.append(FunctionNode((nxt,), 299))
        big.append(IntNode())
        g_big = TypeGraph(big, 0)
        form = canonicalize(g_big)
        self.assertEqual(len(form.graph), 2)
        self.assertEqual(form.to_bytes(), canonicalize(small).to_bytes())

    def test_300_node_chain_stays_distinct(self) -> None:
        # 300 层有限链：每层展开深度不同，任何两层都不得合并。
        nodes: list[Node] = [IntNode()]
        for i in range(1, 300):
            nodes.append(ProductNode((Field("a", i - 1),)))
        g = TypeGraph(nodes, 299)
        form = canonicalize(g)
        self.assertEqual(len(form.graph), 300)
        # 编号约定：从根 BFS，链上第 k 层（离根距离 k）编号恰为 k。
        self.assertEqual(form.mapping[299], 0)
        self.assertEqual(form.mapping[0], 299)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
