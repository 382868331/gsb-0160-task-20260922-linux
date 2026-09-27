"""共享表示（share_graph）的测试。

期望值来源：
* 无环图的“节点 i 与整理后 mapping[i] 等价”用独立参考 reference_unfold
  的展开树交叉验证（不调用被测判定算法）；
* 递归/环用例为手工固定构造并给出显式断言；
* 幂等性为结构级断言：二次整理的节点序列、根、mapping 逐一相同。
"""

from __future__ import annotations

import random
import unittest

from recursive_types import (
    BoolNode,
    Field,
    FunctionNode,
    IntNode,
    ProductNode,
    SharedForm,
    SumNode,
    TypeGraph,
    are_equivalent,
    share_graph,
)
from recursive_types.model import Node

from tests.reference_unfold import unfold
from tests.test_equivalence import random_dag


def mutable_of(node: Node, name: str) -> bool:
    for f in node.fields:  # type: ignore[attr-defined]
        if f.name == name:
            return f.mutable
    raise AssertionError(f"field {name!r} not found")


class TestShareAcyclic(unittest.TestCase):
    """无环随机图：与独立展开参考交叉验证语义保持。"""

    def test_random_dags_preserve_unfolding(self) -> None:
        rng = random.Random(20260927)
        for trial in range(24):
            n = rng.randint(1, 24)
            g = TypeGraph(random_dag(rng, n), n - 1)
            shared = share_graph(g)
            self.assertIsInstance(shared, SharedForm)
            self.assertEqual(len(shared.mapping), n)
            # 每个原节点与其映像的无限展开树相同（无环 => 有限展开即语义）
            for i in range(n):
                self.assertEqual(
                    unfold(g, i),
                    unfold(shared.graph, shared.mapping[i]),
                    f"trial {trial} node {i}",
                )
            # 根对应根
            self.assertEqual(shared.mapping[g.root], shared.graph.root)

    def test_duplicates_actually_merge(self) -> None:
        # 两个写法不同但同构的子树：复制两份 Int 与两份同形 Product。
        g = TypeGraph(
            [
                IntNode(),                                   # 0
                IntNode(),                                   # 1（0 的复制）
                ProductNode((Field("a", 0),)),               # 2
                ProductNode((Field("a", 1),)),               # 3（2 的复制）
                ProductNode((Field("x", 2), Field("y", 3))),  # 4 根
            ],
            root=4,
        )
        shared = share_graph(g)
        self.assertEqual(len(shared.graph), 3)  # Int / P{a:Int} / 根
        self.assertEqual(shared.mapping[0], shared.mapping[1])
        self.assertEqual(shared.mapping[2], shared.mapping[3])
        self.assertEqual(shared.merged_count, 2)


class TestShareCyclic(unittest.TestCase):
    """循环类型：不靠无限展开，环上等价节点必须合并。"""

    def test_self_loop_duplicates_merge(self) -> None:
        # muX. X -> Int 的两个布局：自环 vs 双节点互指。
        g = TypeGraph(
            [
                FunctionNode((0,), 2),   # 0: 自环 muX. X->Int
                FunctionNode((3,), 2),   # 1
                IntNode(),               # 2
                FunctionNode((1,), 2),   # 3: 与 1 互指，展开同为 muX. X->Int
                ProductNode((Field("f", 0), Field("g", 1))),  # 4 根
            ],
            root=4,
        )
        shared = share_graph(g)
        # 0/1/3 全部同义，应合并为一类；加上 Int 与根，共 3 类。
        self.assertEqual(len(shared.graph), 3)
        self.assertEqual(
            shared.mapping[0], shared.mapping[1],
        )
        self.assertEqual(shared.mapping[1], shared.mapping[3])
        # 整理后自环类仍是 Function 且参数指回自身。
        cls = shared.mapping[0]
        node = shared.graph[cls]
        self.assertIsInstance(node, FunctionNode)
        self.assertEqual(node.params[0], cls)

    def test_wrapped_cycle_merges(self) -> None:
        # muX. P{a:X} 与 muX. P{a:P{a:X}} 同义（等价检查里的经典用例）。
        g = TypeGraph(
            [
                ProductNode((Field("a", 0),)),  # 0: muX. P{a:X}
                ProductNode((Field("a", 2),)),  # 1
                ProductNode((Field("a", 1),)),  # 2: 1<->2 绕两拍
                SumNode((Field("t", 0), Field("u", 1))),  # 3 根
            ],
            root=3,
        )
        shared = share_graph(g)
        self.assertEqual(len(shared.graph), 2)  # 环类 + 根 Sum
        self.assertEqual(shared.mapping[0], shared.mapping[1])
        self.assertEqual(shared.mapping[1], shared.mapping[2])

    def test_distinct_cycles_stay_distinct(self) -> None:
        # muX. P{a:X} 与 muX. P{b:X} 字段名不同，不得合并。
        g = TypeGraph(
            [
                ProductNode((Field("a", 0),)),
                ProductNode((Field("b", 1),)),
                ProductNode((Field("x", 0), Field("y", 1))),
            ],
            root=2,
        )
        shared = share_graph(g)
        self.assertEqual(len(shared.graph), 3)
        self.assertNotEqual(shared.mapping[0], shared.mapping[1])


class TestSharePreservesNamesAndMutability(unittest.TestCase):
    """字段名与可变性是合并判据的一部分，整理后不得丢失。"""

    def test_mutability_blocks_merge(self) -> None:
        # 结构完全相同，仅同名同目标字段的 mutable 不同 => 不合并。
        g = TypeGraph(
            [
                IntNode(),
                ProductNode((Field("a", 0, True),)),   # 1: mut a
                ProductNode((Field("a", 0, False),)),  # 2: 不可变 a
                ProductNode((Field("x", 1), Field("y", 2))),  # 3 根
            ],
            root=3,
        )
        shared = share_graph(g)
        self.assertEqual(len(shared.graph), 4)  # 无任何合并
        self.assertNotEqual(shared.mapping[1], shared.mapping[2])
        # 整理后图中可变性原样保留。
        n1 = shared.graph[shared.mapping[1]]
        n2 = shared.graph[shared.mapping[2]]
        self.assertTrue(mutable_of(n1, "a"))
        self.assertFalse(mutable_of(n2, "a"))

    def test_mutability_preserved_when_merged(self) -> None:
        g = TypeGraph(
            [
                IntNode(),
                ProductNode((Field("a", 0, True),)),
                ProductNode((Field("a", 0, True),)),   # 与 1 完全同形
                ProductNode((Field("x", 1), Field("y", 2))),
            ],
            root=3,
        )
        shared = share_graph(g)
        self.assertEqual(shared.mapping[1], shared.mapping[2])
        node = shared.graph[shared.mapping[1]]
        self.assertTrue(mutable_of(node, "a"))

    def test_field_names_preserved(self) -> None:
        g = TypeGraph(
            [
                IntNode(),
                BoolNode(),
                ProductNode((Field("beta", 1), Field("alpha", 0), Field("g", 0),)),
            ],
            root=2,
        )
        shared = share_graph(g)
        root_node = shared.graph[shared.graph.root]
        names = sorted(f.name for f in root_node.fields)
        self.assertEqual(names, ["alpha", "beta", "g"])


class TestShareIdempotent(unittest.TestCase):
    """重新整理同一结果不得产生新的结构变化。"""

    def assert_fixed_point(self, g: TypeGraph) -> None:
        once = share_graph(g)
        twice = share_graph(once.graph)
        self.assertEqual(once.graph.nodes, twice.graph.nodes)
        self.assertEqual(once.graph.root, twice.graph.root)
        # 二次整理的 mapping 是恒等映射：不再有任何合并。
        self.assertEqual(twice.mapping, tuple(range(len(once.graph))))
        self.assertEqual(twice.merged_count, 0)

    def test_idempotent_random_dags(self) -> None:
        rng = random.Random(777)
        for _ in range(20):
            n = rng.randint(1, 30)
            self.assert_fixed_point(TypeGraph(random_dag(rng, n), n - 1))

    def test_idempotent_cyclic(self) -> None:
        g = TypeGraph(
            [
                FunctionNode((0,), 1),
                IntNode(),
                FunctionNode((3,), 1),
                FunctionNode((2,), 1),
                ProductNode((Field("f", 0), Field("h", 2))),
            ],
            root=4,
        )
        self.assert_fixed_point(g)

    def test_idempotent_with_unreachable(self) -> None:
        g = TypeGraph(
            [
                IntNode(),                    # 0: 根
                ProductNode((Field("z", 2),)),  # 1: 不可达
                IntNode(),                    # 2: 不可达，与 0 同义
            ],
            root=0,
        )
        once = share_graph(g)
        # 不可达节点也出现在 mapping 中；同义的 0/2 合并。
        self.assertEqual(once.mapping[0], once.mapping[2])
        self.assertEqual(len(once.graph), 2)
        self.assert_fixed_point(g)


class TestShareEquivalenceRelation(unittest.TestCase):
    """整理前后的图整体等价（用已有判定算法复核）。"""

    def test_shared_graph_equivalent_to_original(self) -> None:
        g = TypeGraph(
            [
                FunctionNode((0,), 2),
                FunctionNode((3,), 2),
                IntNode(),
                FunctionNode((1,), 2),
                ProductNode((Field("f", 0), Field("g", 1), Field("h", 3))),
            ],
            root=4,
        )
        shared = share_graph(g)
        self.assertTrue(are_equivalent(g, shared.graph))

    def test_rejects_non_graph(self) -> None:
        with self.assertRaises(TypeError):
            share_graph("not a graph")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
