"""结构子类型判断与无保护递归拒绝的测试。

期望值来源：
* 无环图一律与独立参考 ``tests.reference_subtype``（自行展开有限树、按题面
  规则递归）交叉验证，该参考不 import 被测判定算法；
* 含环（受保护递归）用例为手工固定构造并给出显式断言；
* 另含一个小规模类型宇宙的**全枚举**两两核对（约 1400 对，确定性）。
"""

from __future__ import annotations

import itertools
import random
import unittest

from recursive_types import (
    AliasNode,
    BoolNode,
    BudgetExceededError,
    DanglingEdgeError,
    Divergence,
    EquivalenceCertificate,
    Field,
    FunctionNode,
    IntNode,
    InvalidNodeError,
    ProductNode,
    SubtypeCertificate,
    SubtypeFailure,
    SumNode,
    TypeGraph,
    UnguardedRecursionError,
    are_equivalent,
    check_equivalence,
    check_subtype,
    is_subtype,
    verify_certificate,
    verify_subtype_certificate,
)
from recursive_types.model import Node

from tests.reference_subtype import expand, reference_equivalent, reference_subtype

FIELD_POOL = ("a", "b", "c", "d")
SUM_POOL = ("x", "y", "z")


def random_dag(rng: random.Random, n: int) -> list[Node]:
    """确定性 n 节点无环图：边只指向更小下标；含 Alias 与 ro/rw 字段。"""
    nodes: list[Node] = [IntNode() if rng.random() < 0.5 else BoolNode()]
    for i in range(1, n):
        choice = rng.random()
        if choice < 0.15:
            nodes.append(AliasNode(rng.randrange(i)))
        elif choice < 0.5:
            count = rng.randint(1, min(3, len(FIELD_POOL)))
            names = rng.sample(FIELD_POOL, count)
            fields = tuple(
                Field(name, rng.randrange(i), readonly=rng.random() < 0.7)
                for name in names
            )
            nodes.append(ProductNode(fields))
        elif choice < 0.72:
            count = rng.randint(1, min(2, len(SUM_POOL)))
            names = rng.sample(SUM_POOL, count)
            fields = tuple(Field(name, rng.randrange(i)) for name in names)
            nodes.append(SumNode(fields))
        else:
            argc = rng.randint(1, 2)
            params = tuple(rng.randrange(i) for _ in range(argc))
            nodes.append(FunctionNode(params, rng.randrange(i)))
    return nodes


def to_graph(nodes: list[Node], root: int | None = None) -> TypeGraph:
    return TypeGraph(nodes, len(nodes) - 1 if root is None else root)


class DAGReferenceCrossTests(unittest.TestCase):
    def test_random_dags_against_independent_reference(self) -> None:
        rng = random.Random(20260924)
        graphs: list[TypeGraph] = []
        for _ in range(30):
            n = rng.randint(1, 10)
            graphs.append(to_graph(random_dag(rng, n)))
        compared = 0
        pos = neg = 0
        for g1 in graphs:
            for g2 in graphs:
                t1 = expand(g1, g1.root)
                t2 = expand(g2, g2.root)
                expected = reference_subtype(t1, t2)
                result = check_subtype(g1, g2)
                self.assertEqual(
                    isinstance(result, SubtypeCertificate),
                    expected,
                    msg=(
                        f"subtype disagreement: g1 root {g1.root} {t1!r} "
                        f"vs g2 root {g2.root} {t2!r}; got {result.render()}"
                    ),
                )
                if expected:
                    self.assertTrue(verify_subtype_certificate(g1, g2, result))
                    pos += 1
                else:
                    neg += 1
                compared += 1
        self.assertGreater(compared, 500)
        self.assertGreater(pos, 0)
        self.assertGreater(neg, 0)

    def test_equivalence_agrees_with_reference_equality(self) -> None:
        rng = random.Random(777)
        graphs = [to_graph(random_dag(rng, rng.randint(1, 9))) for _ in range(20)]
        for g1 in graphs:
            for g2 in graphs:
                expected = reference_equivalent(expand(g1, g1.root), expand(g2, g2.root))
                self.assertEqual(are_equivalent(g1, g2), expected)
                # 结构相等 => 双向子类型，反之在本宇宙中不必成立。
                if expected:
                    self.assertTrue(is_subtype(g1, g2))
                    self.assertTrue(is_subtype(g2, g1))


class SmallUniverseEnumerationTests(unittest.TestCase):
    """深度 <=2 的有限类型宇宙：全枚举两两核对独立参考。"""

    def setUp(self) -> None:
        # 共享叶子节点：0=Int, 1=Bool
        nodes: list[Node] = [IntNode(), BoolNode()]
        values: list[tuple[int, tuple]] = []  # (节点号, 参考展开值)
        leaf_vals = [(0, ("Int",)), (1, ("Bool",))]

        def add(node: Node, value: tuple) -> None:
            nodes.append(node)
            values.append((len(nodes) - 1, value))

        names = ("a", "b")
        # Product：字段名集合为 {a},{b},{a,b}；叶子负载；ro/rw
        for chosen in (("a",), ("b",), ("a", "b")):
            for combo in itertools.product(
                itertools.product((0, 1), (True, False)), repeat=len(chosen)
            ):
                fields = tuple(
                    Field(nm, target, readonly=ro)
                    for nm, (target, ro) in zip(chosen, combo)
                )
                value = (
                    "Product",
                    frozenset(
                        (nm, ro, ("Int",) if t == 0 else ("Bool",))
                        for nm, (t, ro) in zip(chosen, combo)
                    ),
                )
                add(ProductNode(fields), value)
        # Sum：标签集合同上；负载恒只读
        for chosen in (("x",), ("y",), ("x", "y")):
            for combo in itertools.product((0, 1), repeat=len(chosen)):
                fields = tuple(Field(nm, t) for nm, t in zip(chosen, combo))
                value = (
                    "Sum",
                    frozenset(
                        (nm, True, ("Int",) if t == 0 else ("Bool",))
                        for nm, t in zip(chosen, combo)
                    ),
                )
                add(SumNode(fields), value)
        # Function：1 个参数、结果，均取叶子
        for p in (0, 1):
            for r in (0, 1):
                add(
                    FunctionNode((p,), r),
                    ("Function", (("Int",) if p == 0 else ("Bool",),),
                     ("Int",) if r == 0 else ("Bool",)),
                )
        self.graph = TypeGraph(nodes, 0)
        self.universe: list[tuple[int, tuple]] = leaf_vals + values

    def test_all_pairs_match_reference(self) -> None:
        g = self.graph
        total = pos = 0
        for i1, (n1, v1) in enumerate(self.universe):
            for i2, (n2, v2) in enumerate(self.universe):
                expected = reference_subtype(v1, v2)
                result = check_subtype(g, g, root1=n1, root2=n2)
                self.assertIs(
                    isinstance(result, SubtypeCertificate),
                    expected,
                    msg=f"pair ({i1},{i2}) {v1!r} <: {v2!r}: "
                    f"expected {expected}, got {result.render()}",
                )
                total += 1
                pos += int(expected)
        self.assertGreater(total, 1000)
        self.assertGreater(pos, 5)  # 至少存在若干严格子类型对（宽度/协变）


class HandComputedRuleTests(unittest.TestCase):
    """每条规则的手算固定用例。"""

    def test_leaves_only_subtype_same_kind(self) -> None:
        gi = TypeGraph([IntNode()], 0)
        gb = TypeGraph([BoolNode()], 0)
        self.assertTrue(is_subtype(gi, gi))
        r = check_subtype(gi, gb)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertEqual(r.depth, 0)
        self.assertIn("kind differs", r.mismatch.reason)

    def test_product_width_subtype_both_directions(self) -> None:
        g_wide = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        g_narrow = TypeGraph([IntNode(), ProductNode((Field("a", 0),))], 1)
        r = check_subtype(g_wide, g_narrow)
        self.assertIsInstance(r, SubtypeCertificate)
        self.assertTrue(verify_subtype_certificate(g_wide, g_narrow, r))
        # 反向：超类型要求字段 b，子类型没有。
        r2 = check_subtype(g_narrow, g_wide)
        self.assertIsInstance(r2, SubtypeFailure)
        self.assertEqual(r2.depth, 0)
        self.assertIn("width", r2.mismatch.reason)
        self.assertIn("'b'", r2.render())

    def test_readonly_field_covariant(self) -> None:
        # 子字段 {x:Int, extra:Bool} <: 超字段 {x:Int}
        g_sub = TypeGraph(
            [IntNode(), BoolNode(), ProductNode((Field("x", 0), Field("extra", 1)))],
            2,
        )
        g_sup = TypeGraph([IntNode(), ProductNode((Field("x", 0),))], 1)
        g_outer_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("x", 0), Field("extra", 1))),
             ProductNode((Field("a", 2),))],
            3,
        )
        g_outer_sup = TypeGraph(
            [IntNode(), ProductNode((Field("x", 0),)),
             ProductNode((Field("a", 1),))],
            2,
        )
        r = check_subtype(g_outer_sub, g_outer_sup)
        self.assertIsInstance(r, SubtypeCertificate, r.render())
        # 负载反方向不成立（Int 不是宽记录的子类型）。
        self.assertIsInstance(check_subtype(g_sup, g_sub), SubtypeFailure)

    def test_writable_field_invariant(self) -> None:
        # 超: {a: rw Int}；子: {a: rw Bool, x: ro Int}（更宽但字段类型不同）
        g_sup = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0, readonly=False),))], 1
        )
        g_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 1, readonly=False), Field("x", 0)))],
            2,
        )
        r = check_subtype(g_sub, g_sup)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertEqual(r.depth, 1)
        self.assertEqual(r.path[0].render(), "field(a)")
        self.assertIn("invariant", r.mismatch.reason)
        # 同类型可写字段：成立。
        g_same = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0, readonly=False), Field("x", 1)))],
            2,
        )
        self.assertTrue(is_subtype(g_same, g_sup))

    def test_readonly_cannot_satisfy_writable_but_writable_satisfies_readonly(
        self,
    ) -> None:
        g_sup_w = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0, readonly=False),))], 1
        )
        g_sub_ro = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )
        r = check_subtype(g_sub_ro, g_sup_w)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertIn("writable", r.mismatch.reason)
        # 反向：超类型只读、子类型可写 => 安全（可写槽用于只读位置）。
        self.assertTrue(is_subtype(g_sup_w, g_sub_ro))

    def test_function_param_contravariance_result_covariance(self) -> None:
        # A = (Int) -> {x:Int, e:Bool}；B = ({x:Int, e:Bool}) -> {x:Int}
        # A <: B：B 的参数 {x,e} <: A 的参数 Int？否——重排：
        # 令 A 参数为 {x}（窄），B 参数为 {x,e}（宽），结果 A 宽、B 窄。
        gA = TypeGraph(
            [IntNode(), BoolNode(), ProductNode((Field("x", 0),)),
             ProductNode((Field("x", 0), Field("e", 1))),
             FunctionNode((2,), 3)],
            4,
        )
        gB = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("x", 0), Field("e", 1))),
             ProductNode((Field("x", 0),)),
             FunctionNode((2,), 3)],
            4,
        )
        r = check_subtype(gA, gB)
        self.assertIsInstance(r, SubtypeCertificate, r.render())
        self.assertTrue(verify_subtype_certificate(gA, gB, r))
        # 证书中必须出现逆变产生的 sup 义务。
        self.assertTrue(
            any(rel == "sup" for rel, _a, _b in r.entries)
        )
        # 反向不成立，且失败定位在 param(0)。
        r2 = check_subtype(gB, gA)
        self.assertIsInstance(r2, SubtypeFailure)
        self.assertEqual(r2.depth, 1)
        self.assertEqual(r2.path[0].render(), "param(0)")

    def test_function_arity_must_match(self) -> None:
        g1 = TypeGraph([IntNode(), FunctionNode((0,), 0)], 1)
        g2 = TypeGraph([IntNode(), FunctionNode((0, 0), 0)], 1)
        r = check_subtype(g1, g2)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertEqual(r.depth, 0)
        self.assertIn("arity", r.mismatch.reason)

    def test_sum_has_no_width_but_payload_covariant(self) -> None:
        g_sub = TypeGraph(
            [IntNode(), BoolNode(), SumNode((Field("x", 0), Field("y", 1)))], 2
        )
        g_sup = TypeGraph([IntNode(), SumNode((Field("x", 0),))], 1)
        r = check_subtype(g_sub, g_sup)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertIn("Sum", r.mismatch.reason)
        # 同标签、负载协变：x:{a,b} <: x:{a}
        g_p_sub = TypeGraph(
            [IntNode(), BoolNode(),
             ProductNode((Field("a", 0), Field("b", 1))),
             SumNode((Field("x", 2),))],
            3,
        )
        g_p_sup = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),)),
             SumNode((Field("x", 1),))],
            2,
        )
        self.assertTrue(is_subtype(g_p_sub, g_p_sup))


class RecursiveSubtypeTests(unittest.TestCase):
    def test_self_recursive_width(self) -> None:
        # 子 μX.{a:X, b:Int} <: 超 μX.{a:X}
        g_sub = TypeGraph(
            [IntNode(), ProductNode((Field("a", 1), Field("b", 0)))], 1
        )
        g_sup = TypeGraph([ProductNode((Field("a", 0),))], 0)
        r = check_subtype(g_sub, g_sup)
        self.assertIsInstance(r, SubtypeCertificate, r.render())
        self.assertTrue(verify_subtype_certificate(g_sub, g_sup, r))
        # 反向不成立（宽度）。
        self.assertIsInstance(check_subtype(g_sup, g_sub), SubtypeFailure)

    def test_mutual_recursion_subtype(self) -> None:
        # T  = {a:U, b:Int}；U = {x:T, y:Bool}
        # T' = {a:U', b:Int, extra:Bool}；U' = {x:T', y:Bool}
        # 手算：T' <: T（宽度）；其 a 字段要求 U' <: U；U' 与 U 标签一致，
        # x 负载要求 T' <: T —— 回到起始假设，协同递归封闭 => 成立。
        sub = TypeGraph(
            [
                SumNode((Field("x", 1), Field("y", 3))),
                ProductNode((Field("a", 0), Field("b", 2), Field("extra", 3))),
                IntNode(),
                BoolNode(),
            ],
            1,
        )
        sup = TypeGraph(
            [
                ProductNode((Field("a", 1), Field("b", 2))),
                SumNode((Field("x", 0), Field("y", 3))),
                IntNode(),
                BoolNode(),
            ],
            0,
        )
        r = check_subtype(sub, sup)
        self.assertIsInstance(r, SubtypeCertificate, r.render())
        self.assertTrue(verify_subtype_certificate(sub, sup, r))

    def test_recursive_divergence_is_locatable(self) -> None:
        # 子 μX.{a:X} 与超 μX.{a:X} 在 a 下完全一致 => 成立；
        # 改超类型为 μX.{a:μY.{a:Y, b:Int}} 的等价形状无意义，改为：
        # 子 μX.{a:X, tag:Int} <: 超 μX.{a:X}（宽度）成立，
        # 但超 μX.{a:X} <: 子 在根即宽度失败。
        g_loop = TypeGraph([ProductNode((Field("a", 0),))], 0)
        g_tag = TypeGraph(
            [IntNode(), ProductNode((Field("a", 1), Field("tag", 0)))], 1
        )
        self.assertTrue(is_subtype(g_tag, g_loop))
        r = check_subtype(g_loop, g_tag)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertIn("width", r.mismatch.reason)

    def test_recursive_writable_invariant_rejects_covariance(self) -> None:
        # μX.{v: rw X} 与 μY.{v: rw Y}：同构 => 不变义务下成立。
        g1 = TypeGraph([ProductNode((Field("v", 0, readonly=False),))], 0)
        g2 = TypeGraph(
            [ProductNode((Field("v", 1, readonly=False),)),
             ProductNode((Field("v", 0, readonly=False),))],
            0,
        )
        r = check_subtype(g1, g2)
        self.assertIsInstance(r, SubtypeCertificate, r.render())
        # 超 rw、子 ro：即使递归也必须在某层拒绝（首层即可定位）。
        g3 = TypeGraph([ProductNode((Field("v", 0),))], 0)
        r2 = check_subtype(g3, g1)
        self.assertIsInstance(r2, SubtypeFailure)
        self.assertIn("writable", r2.mismatch.reason)

    def test_alias_is_transparent_in_subtype_and_equivalence(self) -> None:
        # Alias 指向受保护节点：A -> P{a:A, b:Int} 与 μX.P{a:X,b:Int} 等价且互子类型。
        g_alias = TypeGraph(
            [IntNode(),
             ProductNode((Field("a", 2), Field("b", 0))),
             AliasNode(1)],
            2,
        )
        g_direct = TypeGraph(
            [IntNode(), ProductNode((Field("a", 1), Field("b", 0)))], 1
        )
        self.assertTrue(is_subtype(g_alias, g_direct))
        self.assertTrue(is_subtype(g_direct, g_alias))
        eq = check_equivalence(g_alias, g_direct)
        self.assertIsInstance(eq, EquivalenceCertificate)
        self.assertTrue(verify_certificate(g_alias, g_direct, eq))


class UnguardedRecursionTests(unittest.TestCase):
    def test_self_alias_cycle_rejected(self) -> None:
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph([AliasNode(0)], 0)
        self.assertIn("node 0", str(cm.exception))
        self.assertIn("0 -> 0", str(cm.exception))

    def test_two_node_alias_cycle_rejected(self) -> None:
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph([AliasNode(1), AliasNode(0)], 0)
        msg = str(cm.exception)
        self.assertTrue("0 -> 1 -> 0" in msg or "1 -> 0 -> 1" in msg, msg)

    def test_long_alias_cycle_rejected_with_path(self) -> None:
        with self.assertRaises(UnguardedRecursionError) as cm:
            TypeGraph(
                [IntNode(), AliasNode(2), AliasNode(3), AliasNode(1)], 1
            )
        self.assertIn("1 -> 2 -> 3 -> 1", str(cm.exception))

    def test_alias_chain_into_constructor_is_guarded(self) -> None:
        # 0=Int, 1=Alias->2, 2=Alias->1: 1->2->1 全是 Alias 会被拒；
        # 改为 1=Alias->2, 2=Product{a:1}，环经过 Product，受保护。
        g = TypeGraph(
            [IntNode(), AliasNode(2), ProductNode((Field("a", 1), Field("b", 0)))],
            1,
        )
        self.assertEqual(len(g), 3)

    def test_alias_cycle_reachable_from_root_still_rejected(self) -> None:
        # 环在不可达分支也要拒（全图校验，不留下半构造状态）。
        with self.assertRaises(UnguardedRecursionError):
            TypeGraph(
                [IntNode(), AliasNode(2), AliasNode(1)], 0
            )

    def test_function_guards_its_recursion(self) -> None:
        # μX. X -> Int：回边经过 Function 构造子，受保护（不需要 Alias）。
        g = TypeGraph([FunctionNode((0,), 1), IntNode()], 0)
        self.assertTrue(is_subtype(g, g))


class FailurePathTests(unittest.TestCase):
    def test_path_through_nested_fields(self) -> None:
        # 外层 field a -> field x：叶子种类不符，depth 2。
        def outer(inner_idx: int) -> list[Node]:
            return [
                IntNode(),
                BoolNode(),
                ProductNode((Field("x", inner_idx),)),
                ProductNode((Field("a", 2),)),
            ]

        g1 = TypeGraph(outer(0), 3)  # x:Int
        g2 = TypeGraph(outer(1), 3)  # x:Bool
        r = check_subtype(g1, g2)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertEqual(r.depth, 2)
        self.assertEqual([s.render() for s in r.path], ["field(a)", "field(x)"])

    def test_path_through_function_result(self) -> None:
        # ()-> 由 1 参函数承载：(Int)->Int  vs  (Int)->Bool，失败在 result。
        g1 = TypeGraph([IntNode(), FunctionNode((0,), 0)], 1)
        g2 = TypeGraph([IntNode(), BoolNode(), FunctionNode((0,), 1)], 2)
        r = check_subtype(g1, g2)
        self.assertIsInstance(r, SubtypeFailure)
        self.assertEqual(r.depth, 1)
        self.assertEqual(r.path[0].render(), "result")

    def test_failure_render_is_human_readable(self) -> None:
        g1 = TypeGraph([IntNode()], 0)
        g2 = TypeGraph([BoolNode()], 0)
        r = check_subtype(g1, g2)
        self.assertIsInstance(r, SubtypeFailure)
        text = r.render()
        self.assertIn("NOT SUBTYPE", text)
        self.assertIn("depth 0", text)


class CertificateTests(unittest.TestCase):
    def setUp(self) -> None:
        # 无环宽记录 {a:Int,b:Int} <: {a:Int}：证书含根条目与 sub(0,0) 两条。
        self.g_wide = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        self.g_narrow = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )
        # 递归用例：子 μX.{a:X,b:Int} <: 超 μX.{a:X}（证书单条自封闭）。
        self.g_sub = TypeGraph(
            [IntNode(), ProductNode((Field("a", 1), Field("b", 0)))], 1
        )
        self.g_sup = TypeGraph([ProductNode((Field("a", 0),))], 0)

    def test_tampered_certificate_rejected(self) -> None:
        cert = check_subtype(self.g_wide, self.g_narrow)
        self.assertIsInstance(cert, SubtypeCertificate)
        self.assertTrue(verify_subtype_certificate(self.g_wide, self.g_narrow, cert))
        self.assertGreaterEqual(len(cert.entries), 2)
        # 删掉叶子条目：根义务的子义务 sub(0,0) 不再封闭。
        entries = [e for e in cert.entries if e != ("sub", 0, 0)]
        shrunk = SubtypeCertificate(cert.root_pair, frozenset(entries))
        self.assertFalse(
            verify_subtype_certificate(self.g_wide, self.g_narrow, shrunk)
        )
        # 递归证书：根义务缺失。
        rcert = check_subtype(self.g_sub, self.g_sup)
        no_root = SubtypeCertificate(
            rcert.root_pair,
            frozenset(e for e in rcert.entries if e != ("sub", 1, 0)),
        )
        self.assertFalse(verify_subtype_certificate(self.g_sub, self.g_sup, no_root))
        # 节点越界。
        bad = SubtypeCertificate(cert.root_pair, frozenset({("sub", 9, 9)}))
        self.assertFalse(verify_subtype_certificate(self.g_wide, self.g_narrow, bad))
        # 非法关系标记。
        bad_rel = SubtypeCertificate(
            cert.root_pair, frozenset({("weird", 1, 1)})
        )
        self.assertFalse(
            verify_subtype_certificate(self.g_wide, self.g_narrow, bad_rel)
        )

    def test_wrong_certificate_type_rejected(self) -> None:
        cert = check_subtype(self.g_sub, self.g_sup)
        with self.assertRaises(TypeError):
            verify_subtype_certificate(self.g_sub, self.g_sup, object())  # type: ignore[arg-type]


class SubtypeBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.g_wide = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0), Field("b", 0)))], 1
        )
        self.g_narrow = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )

    def test_proven_failure_within_tiny_budget_is_reported(self) -> None:
        # 根对即种类不符：budget=1 也必须给出失败，而不是预算异常。
        gi = TypeGraph([IntNode()], 0)
        gb = TypeGraph([BoolNode()], 0)
        r = check_subtype(gi, gb, budget=1)
        self.assertIsInstance(r, SubtypeFailure)

    def test_budget_exhaustion_is_unknown_not_failure(self) -> None:
        # 根义务 + 至少 2 个新义务才封闭；budget=1 => 未知，不得给 Failure。
        with self.assertRaises(BudgetExceededError) as cm:
            check_subtype(self.g_wide, self.g_narrow, budget=1)
        self.assertEqual(cm.exception.budget, 1)

    def test_default_budget_covers_300_node_case(self) -> None:
        # 300 节点宽记录链 vs 窄记录链：受默认预算覆盖，确定给结论。
        def chain(extra: bool) -> list[Node]:
            nodes: list[Node] = [IntNode()]
            for i in range(1, 300):
                fields = (Field("a", i - 1),)
                if extra:
                    fields = (Field("a", i - 1), Field("b", 0))
                nodes.append(ProductNode(fields))
            return nodes

        g_sub = TypeGraph(chain(True), 299)
        g_sup = TypeGraph(chain(False), 299)
        r = check_subtype(g_sub, g_sup)
        self.assertIsInstance(r, SubtypeCertificate)
        self.assertTrue(verify_subtype_certificate(g_sub, g_sup, r))

    def test_invalid_budget_and_roots_rejected_upfront(self) -> None:
        for bad in (0, -3, True, 1.0, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    check_subtype(self.g_wide, self.g_narrow, budget=bad)
        with self.assertRaises(ValueError):
            check_subtype(self.g_wide, self.g_narrow, root1=99)
        with self.assertRaises(TypeError):
            check_subtype(self.g_wide, self.g_narrow, root2=False)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            check_subtype([IntNode()], self.g_narrow)  # type: ignore[arg-type]


class NewModelValidationTests(unittest.TestCase):
    def test_alias_dangling_edge(self) -> None:
        with self.assertRaises(DanglingEdgeError) as cm:
            TypeGraph([AliasNode(7)], 0)
        self.assertIn("node 0", str(cm.exception))

    def test_alias_target_must_be_strict_int(self) -> None:
        with self.assertRaises(Exception):
            TypeGraph([AliasNode(True)], 0)  # type: ignore[arg-type]

    def test_field_readonly_must_be_strict_bool(self) -> None:
        with self.assertRaises(InvalidNodeError) as cm:
            TypeGraph(
                [IntNode(), ProductNode((Field("a", 0, readonly=1),))], 1
            )
        self.assertIn("readonly", str(cm.exception))
        self.assertIn("node 1, field 0", str(cm.exception))

    def test_writable_sum_payload_rejected(self) -> None:
        with self.assertRaises(InvalidNodeError) as cm:
            TypeGraph(
                [IntNode(), SumNode((Field("x", 0, readonly=False),))], 1
            )
        self.assertIn("Sum", str(cm.exception))
        self.assertIn("node 1", str(cm.exception))

    def test_field_default_is_readonly(self) -> None:
        f = Field("a", 0)
        self.assertTrue(f.readonly)

    def test_equivalence_distinguishes_mutability(self) -> None:
        g_ro = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0),))], 1
        )
        g_rw = TypeGraph(
            [IntNode(), ProductNode((Field("a", 0, readonly=False),))], 1
        )
        r = check_equivalence(g_ro, g_rw)
        self.assertIsInstance(r, Divergence)
        self.assertEqual(r.depth, 0)
        self.assertIn("mutability", r.mismatch.reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
