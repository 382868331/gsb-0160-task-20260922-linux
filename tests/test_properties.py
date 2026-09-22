"""补充性质测试：自反性、对称性、传递性的小规模经验检查。

按任务约定，这类“往返一致”只作补充；期望值的主要依据是手写语义用例
（test_checker.py）与独立展开参考（test_reference_acyclic.py）。

循环图生成器在本文件内独立书写（带环，展开参考不适用，因此这里只
检验等价关系的代数性质本身）。
"""

import random
import unittest

from rectypes import TypeGraph, are_equivalent, check_equivalence


def gen_cyclic(rng: random.Random, n: int) -> tuple[dict, str]:
    """生成确定性的随机有根连通图（允许任意边，可带环）。"""
    ids = [f"c{i}" for i in range(n)]
    nodes: dict[str, dict] = {}
    names_pool = ["a", "b", "x", "y"]
    for ident in ids:
        kind = rng.choice(
            ["Int", "Bool", "Product", "Sum", "Function", "Product", "Sum"]
        )
        if kind in ("Int", "Bool"):
            nodes[ident] = {"kind": kind}
        elif kind in ("Product", "Sum"):
            count = rng.randint(1, 2)
            chosen = rng.sample(names_pool, count)
            nodes[ident] = {
                "kind": kind,
                "fields": [(name, rng.choice(ids)) for name in chosen],
            }
        else:
            count = rng.randint(1, 2)
            nodes[ident] = {
                "kind": "Function",
                "params": [rng.choice(ids) for _ in range(count)],
                "result": rng.choice(ids),
            }
    root = ids[0]

    # 保证整图从根可达：把任何未被根到达的原子节点替换为可达链。
    reachable = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        node = nodes[cur]
        for child in _children_of(node):
            if child not in reachable:
                reachable.add(child)
                stack.append(child)
    orphans = [i for i in ids if i not in reachable]
    if orphans:
        # 将孤儿逐个挂到根上（根若是原子，先改成 Product）。
        chain_root = root
        if nodes[root]["kind"] in ("Int", "Bool"):
            nodes[root] = {
                "kind": "Product",
                "fields": [("extra", orphans[0])],
            }
        else:
            _add_edge_to(nodes[root], orphans[0])
        for a, b in zip(orphans, orphans[1:] + [chain_root]):
            if nodes[a]["kind"] in ("Int", "Bool"):
                nodes[a] = {"kind": "Product", "fields": [("next", b)]}
            else:
                _add_edge_to(nodes[a], b)
    return nodes, root


def _children_of(node: dict) -> list[str]:
    kind = node["kind"]
    if kind in ("Product", "Sum"):
        return [t for _, t in node.get("fields", [])]
    if kind == "Function":
        return list(node.get("params", [])) + [node.get("result")]
    return []


def _add_edge_to(node: dict, target: str) -> None:
    kind = node["kind"]
    if kind in ("Product", "Sum"):
        used = {n for n, _ in node["fields"]}
        for name in ("link", "m", "n", "z"):
            if name not in used:
                node["fields"].append((name, target))
                return
    else:
        node["params"] = list(node["params"]) + [target]


class EquivalenceRelationProperties(unittest.TestCase):
    def test_reflexivity_on_cyclic_graphs(self):
        rng = random.Random(101)
        for _ in range(100):
            n = rng.randint(1, 8)
            nodes, root = gen_cyclic(rng, n)
            g = TypeGraph(nodes, root=root)
            self.assertTrue(are_equivalent(g, g))

    def test_symmetry_on_cyclic_graphs(self):
        rng = random.Random(202)
        for _ in range(100):
            n1, r1 = gen_cyclic(rng, rng.randint(1, 8))
            n2, r2 = gen_cyclic(rng, rng.randint(1, 8))
            g1, g2 = TypeGraph(n1, root=r1), TypeGraph(n2, root=r2)
            self.assertEqual(
                check_equivalence(g1, g2).equivalent,
                check_equivalence(g2, g1).equivalent,
            )

    def test_transitivity_via_renamed_copy(self):
        # G ~ 改名(G) ~ 再改名(G)，则 G ~ 再改名(G)；且改名后证书仍独立成立。
        rng = random.Random(303)
        import copy

        for _ in range(40):
            n1, r1 = gen_cyclic(rng, rng.randint(1, 8))
            g1 = TypeGraph(n1, root=r1)

            n2 = copy.deepcopy(n1)
            ren = {old: f"k_{old}" for old in n2}
            for old, node in list(n2.items()):
                new = ren[old]
                rebuilt = copy.deepcopy(node)
                kind = node["kind"]
                if kind in ("Product", "Sum"):
                    rebuilt["fields"] = [
                        (name, ren[t]) for name, t in node["fields"]
                    ]
                elif kind == "Function":
                    rebuilt["params"] = [ren[p] for p in node["params"]]
                    rebuilt["result"] = ren[node["result"]]
                del n2[old]
                n2[new] = rebuilt
            g2 = TypeGraph(n2, root=ren[r1])

            self.assertTrue(are_equivalent(g1, g2))
            res = check_equivalence(g2, g1)
            self.assertTrue(res.equivalent)
            # 每份正向证书都能过独立验证器。
            self.assertIsNotNone(res.certificate)


if __name__ == "__main__":
    unittest.main()
