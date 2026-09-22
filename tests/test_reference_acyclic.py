"""无环图：被测核心 vs 独立有限树展开参考的差分测试。

所有图都用确定性伪随机代码生成（固定种子，无外部数据）。参考实现
（``tests/reference.py``）不导入 checker；本文件只比对双方结论。
"""

import random
import unittest

from rectypes import TypeGraph, check_equivalence

from reference import reference_equal, shortest_divergence_depth


def gen_acyclic(rng: random.Random, max_depth: int) -> dict:
    """生成一棵随机类型“树”（以 dict 图承载，允许内部共享子节点）。

    先以拓扑顺序造节点，边只指向更早的节点，因此无环且全部可达。
    返回 ``(nodes, root)``。
    """
    nodes: dict[str, dict] = {}
    counter = 0

    def fresh() -> str:
        nonlocal counter
        name = f"n{counter}"
        counter += 1
        return name

    def build(depth: int) -> str:
        nonlocal counter
        if depth <= 0:
            kind = rng.choice(["Int", "Bool"])
            name = fresh()
            nodes[name] = {"kind": kind}
            return name
        kind = rng.choice(["Int", "Bool", "Product", "Sum", "Function"])
        if kind in ("Int", "Bool"):
            name = fresh()
            nodes[name] = {"kind": kind}
            return name
        name = fresh()
        if kind in ("Product", "Sum"):
            count = rng.randint(1, 2)
            fields = []
            for i in range(count):
                child = build(depth - 1)
                fields.append((f"f{i}", child))
            # 小概率打乱字段顺序（按名对应，顺序无意义）
            if rng.random() < 0.5:
                rng.shuffle(fields)
            nodes[name] = {"kind": kind, "fields": fields}
        else:
            count = rng.randint(1, 2)
            params = [build(depth - 1) for _ in range(count)]
            result = build(depth - 1)
            nodes[name] = {"kind": kind, "params": params, "result": result}
        return name

    root = build(max_depth)
    return nodes, root


class AcyclicDifferentialTests(unittest.TestCase):
    def test_many_pairs_against_tree_reference(self):
        rng = random.Random(20260922)
        trials = 400
        mismatches = 0
        for t in range(trials):
            depth = rng.randint(0, 4)
            n1, r1 = gen_acyclic(rng, depth)
            n2, r2 = gen_acyclic(rng, depth)
            g1 = TypeGraph(n1, root=r1)
            g2 = TypeGraph(n2, root=r2)
            result = check_equivalence(g1, g2)
            ref = reference_equal(g1, g2)
            self.assertEqual(
                result.equivalent,
                ref,
                msg=f"trial {t}: checker={result.equivalent} reference={ref}",
            )
            if not ref:
                # 最短分歧深度也必须与参考的独立 BFS 一致。
                ref_depth = shortest_divergence_depth(g1, g2)
                self.assertEqual(
                    result.divergence.depth,
                    ref_depth,
                    msg=(
                        f"trial {t}: depth checker={result.divergence.depth} "
                        f"reference={ref_depth}"
                    ),
                )
                mismatches += 1
        # 400 对随机图中应当确实出现过不等价用例，避免测试退化成恒真。
        self.assertGreater(mismatches, 50)

    def test_identical_structure_different_ids_and_order(self):
        rng = random.Random(42)
        for _ in range(50):
            n1, r1 = gen_acyclic(rng, 4)
            # 深拷贝后给所有节点重命名（结构完全一致）。
            import copy

            n2 = copy.deepcopy(n1)
            renaming = {old: f"copy_{old}" for old in n2}
            rebuilt = {}
            for old, node in n2.items():
                new_node = copy.deepcopy(node)
                kind = node["kind"]
                if kind in ("Product", "Sum"):
                    new_node["fields"] = [
                        (name, renaming[t]) for name, t in node["fields"]
                    ]
                elif kind == "Function":
                    new_node["params"] = [renaming[p] for p in node["params"]]
                    new_node["result"] = renaming[node["result"]]
                rebuilt[renaming[old]] = new_node
            g1 = TypeGraph(n1, root=r1)
            g2 = TypeGraph(rebuilt, root=renaming[r1])
            self.assertTrue(check_equivalence(g1, g2).equivalent)
            self.assertTrue(reference_equal(g1, g2))

    def test_dag_sharing_vs_unrolled_copy(self):
        # DAG（共享）与逐边复制展开（更大的树）参考与算法都必须判等价。
        rng = random.Random(7)
        for _ in range(30):
            n1, r1 = gen_acyclic(rng, 3)
            g1 = TypeGraph(n1, root=r1)

            # 独立地把图展开成纯树（每个出现位置一个新节点）。
            tree_nodes: dict[str, dict] = {}
            serial = 0

            def unroll(ident: str) -> str:
                nonlocal serial
                new_name = f"u{serial}"
                serial += 1
                node = n1[ident]
                kind = node["kind"]
                if kind in ("Int", "Bool"):
                    tree_nodes[new_name] = {"kind": kind}
                elif kind in ("Product", "Sum"):
                    tree_nodes[new_name] = {
                        "kind": kind,
                        "fields": [
                            (name, unroll(t)) for name, t in node["fields"]
                        ],
                    }
                else:
                    tree_nodes[new_name] = {
                        "kind": kind,
                        "params": [unroll(p) for p in node["params"]],
                        "result": unroll(node["result"]),
                    }
                return new_name

            new_root = unroll(r1)
            g2 = TypeGraph(tree_nodes, root=new_root)
            self.assertTrue(reference_equal(g1, g2))
            self.assertTrue(check_equivalence(g1, g2).equivalent)


if __name__ == "__main__":
    unittest.main()
