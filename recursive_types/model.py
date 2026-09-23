"""公开数据结构：类型节点与有根类型图。

节点种类（判别式见各节点的 ``kind`` 常量）：

* ``Int`` / ``Bool``：叶子，元数 0；
* ``Product`` / ``Sum``：带**唯一**字段名的命名字段集合，字段按名（而非按位置）
  对应；元数 >= 1；
* ``Function``：有序参数列表（>= 1）与单个返回类型；
* ``Alias``：**透明**节点（递归变量引用 / μ 变量使用点），恰好 1 条出边，
  语义上等同于其目标；它不产生结构层，因此也不计入受保护性。

节点编号仅用于在*单张图内*表达边（共享与递归回边），从不参与语义比较：
两张图中编号相同但展开树不同的节点不等价，反之共享子图与复制子图不被区分。

受保护递归（contractive / guarded recursion）
---------------------------------------------
一个从根可达的环若**只经过 Alias 边**（如 ``μX. X``），展开后不产生任何有限层
结构，这样的递归类型无合法的无限树，构造期由
:class:`~recursive_types.errors.UnguardedRecursionError` 拒绝，错误消息给出
无保护环上的节点序列。环上只要含一个结构构造子（Product/Sum/Function）即为
受保护（``μX. X -> Int``、``μX. Product{a: X}`` 合法）。不可达节点上的无保护环
不影响根类型的树定义，允许存在。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .errors import (
    ArityError,
    DanglingEdgeError,
    DuplicateFieldError,
    GraphSizeError,
    InvalidNodeError,
    InvalidRootError,
    UnguardedRecursionError,
)

INT = "Int"
BOOL = "Bool"
PRODUCT = "Product"
SUM = "Sum"
FUNCTION = "Function"
ALIAS = "Alias"

#: 单张类型图允许的节点数上限（接口边界）。
MAX_NODES = 300
#: 单张类型图允许的节点数下限。
MIN_NODES = 1


def _is_strict_int(value: object) -> bool:
    """整数参数拒绝 bool（``True`` 不是合法编号）。"""
    return type(value) is int


def _as_int(value: object, location: str, what: str) -> int:
    if not _is_strict_int(value):
        kind = type(value).__name__
        if isinstance(value, bool):
            kind = "bool"
        raise InvalidNodeError(
            f"{what} must be a strict int (got {kind}: {value!r})", location
        )
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class Field:
    """Product/Sum 的一个命名字段：``name -> target``。"""

    name: str
    target: int


@dataclass(frozen=True)
class IntNode:
    kind: str = INT


@dataclass(frozen=True)
class BoolNode:
    kind: str = BOOL


@dataclass(frozen=True)
class ProductNode:
    fields: tuple[Field, ...] = ()
    kind: str = PRODUCT


@dataclass(frozen=True)
class SumNode:
    fields: tuple[Field, ...] = ()
    kind: str = SUM


@dataclass(frozen=True)
class FunctionNode:
    params: tuple[int, ...] = ()
    result: int = 0
    kind: str = FUNCTION


@dataclass(frozen=True)
class AliasNode:
    """透明节点（递归变量使用点）：语义上等同于 ``target``。

    它不构成结构层——等价/子类型比较前被透明跳过，受保护性分析中也不充当
    守卫（guard）；仅用于显式表达 μ 变量引用，使无保护递归可被定位。
    """

    target: int = 0
    kind: str = ALIAS


Node = Union[IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode]

_LEAF_KINDS = (INT, BOOL)
_LABELLED_KINDS = (PRODUCT, SUM)


class TypeGraph:
    """经完整校验、不可变的有根类型图。

    :param nodes: 节点列表（编号即下标）。接受 ``list``/``tuple``；
        构造后内部复制为元组，外部再修改入参不会影响已构造的图。
    :param root: 根节点编号（严格 ``int``，非 bool）。
    :raises TypeGraphError: 任何结构/元数/悬空边/越界/类型非法问题，
        异常消息带 ``"node <i>"`` / ``"root"`` 等可定位前缀。
    """

    __slots__ = ("_nodes", "_root", "_resolve")

    def __init__(self, nodes: list[Node] | tuple[Node, ...], root: int) -> None:
        if not isinstance(nodes, (list, tuple)):
            raise InvalidNodeError(
                f"nodes must be a list or tuple (got {type(nodes).__name__})",
                "nodes",
            )
        n = len(nodes)
        if n < MIN_NODES or n > MAX_NODES:
            raise GraphSizeError(
                f"node count must be in [{MIN_NODES}, {MAX_NODES}] (got {n})",
                "nodes",
            )
        if type(root) is not int:
            kind = "bool" if isinstance(root, bool) else type(root).__name__
            raise InvalidRootError(
                f"root index must be a strict int (got {kind}: {root!r})",
                "root",
            )
        root_idx = root
        if not 0 <= root_idx < n:
            raise InvalidRootError(
                f"root index {root_idx} out of range for {n} node(s)", "root"
            )

        prepared: list[Node] = []
        for i, node in enumerate(nodes):
            prepared.append(self._validate_node(node, i, n))
        final_nodes: tuple[Node, ...] = tuple(prepared)
        self._check_guarded(final_nodes, root_idx)
        self._nodes = final_nodes
        self._root = root_idx
        self._resolve: dict[int, int] = {}

    @staticmethod
    def _validate_node(node: object, index: int, n: int) -> Node:
        loc = f"node {index}"
        if not isinstance(
            node,
            (IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode),
        ):
            raise InvalidNodeError(
                f"expected a Node (Int/Bool/Product/Sum/Function/Alias), "
                f"got {type(node).__name__}: {node!r}",
                loc,
            )
        kind = node.kind
        if kind in _LEAF_KINDS:
            return node  # frozen dataclass, 无携带边
        if kind in _LABELLED_KINDS:
            return TypeGraph._validate_labelled(node, loc, n)
        if kind == FUNCTION:
            return TypeGraph._validate_function(node, loc, n)
        if kind == ALIAS:
            return TypeGraph._validate_alias(node, loc, n)
        raise InvalidNodeError(f"unknown node kind {kind!r}", loc)  # pragma: no cover

    @staticmethod
    def _validate_alias(node: AliasNode, loc: str, n: int) -> AliasNode:
        target = _as_int(node.target, loc, "Alias target")
        if not 0 <= target < n:
            raise DanglingEdgeError(
                f"Alias target points to {target}, "
                f"valid range is [0, {n - 1}]",
                loc,
            )
        return AliasNode(target)

    @staticmethod
    def _validate_labelled(
        node: ProductNode | SumNode, loc: str, n: int
    ) -> ProductNode | SumNode:
        raw_fields = node.fields
        if not isinstance(raw_fields, (list, tuple)):
            raise InvalidNodeError(
                f"{node.kind} fields must be a list/tuple "
                f"(got {type(raw_fields).__name__})",
                loc,
            )
        if len(raw_fields) < 1:
            raise ArityError(
                f"{node.kind} must have at least 1 field (got 0)", loc
            )
        seen: set[str] = set()
        fields: list[Field] = []
        for j, field in enumerate(raw_fields):
            floc = f"{loc}, field {j}"
            if not isinstance(field, Field):
                raise InvalidNodeError(
                    f"field entry must be a Field (got {type(field).__name__})",
                    floc,
                )
            name = field.name
            if type(name) is not str or len(name) == 0:
                raise InvalidNodeError(
                    f"field name must be a non-empty str "
                    f"(got {type(name).__name__}: {name!r})",
                    floc,
                )
            if name in seen:
                raise DuplicateFieldError(
                    f"duplicate field name {name!r} in {node.kind}", loc
                )
            seen.add(name)
            target = _as_int(field.target, floc, "field target")
            if not 0 <= target < n:
                raise DanglingEdgeError(
                    f"{node.kind} field {name!r} points to {target}, "
                    f"valid range is [0, {n - 1}]",
                    loc,
                )
            fields.append(Field(name, target))
        if isinstance(node, ProductNode):
            return ProductNode(tuple(fields))
        return SumNode(tuple(fields))

    @staticmethod
    def _validate_function(node: FunctionNode, loc: str, n: int) -> FunctionNode:
        raw_params = node.params
        if not isinstance(raw_params, (list, tuple)):
            raise InvalidNodeError(
                f"Function params must be a list/tuple "
                f"(got {type(raw_params).__name__})",
                loc,
            )
        if len(raw_params) < 1:
            raise ArityError(
                "Function must have at least 1 ordered parameter (got 0)", loc
            )
        params: list[int] = []
        for j, p in enumerate(raw_params):
            target = _as_int(p, f"{loc}, param {j}", "parameter target")
            if not 0 <= target < n:
                raise DanglingEdgeError(
                    f"Function param {j} points to {target}, "
                    f"valid range is [0, {n - 1}]",
                    loc,
                )
            params.append(target)
        result = _as_int(node.result, loc, "Function result target")
        if not 0 <= result < n:
            raise DanglingEdgeError(
                f"Function result points to {result}, "
                f"valid range is [0, {n - 1}]",
                loc,
            )
        return FunctionNode(tuple(params), result)

    @staticmethod
    def _check_guarded(nodes: tuple[Node, ...], root_idx: int) -> None:
        """拒绝从根可达的、只经过 Alias 边的环（无保护递归）。

        先沿**全部**出边求根可达集，再在可达子图上对“Alias 边图”做三色 DFS：
        遇到指向在途（gray）节点的 Alias 边，即找到无保护环，错误消息给出
        环上节点序列。不可达部分的环不参与根类型的树，允许存在。
        """
        n = len(nodes)

        # 1) 根可达性（沿所有边，Alias 与结构边都算）。
        reachable = {root_idx}
        queue = [root_idx]
        head = 0
        while head < len(queue):
            i = queue[head]
            head += 1
            node = nodes[i]
            if node.kind == ALIAS:
                outs = (node.target,)
            elif node.kind in _LABELLED_KINDS:
                outs = tuple(f.target for f in node.fields)  # type: ignore[union-attr]
            elif node.kind == FUNCTION:
                outs = tuple(node.params) + (node.result,)  # type: ignore[union-attr]
            else:
                outs = ()
            for t in outs:
                if t not in reachable:
                    reachable.add(t)
                    queue.append(t)

        # 2) 仅在可达子图上的 Alias 边图中寻找环。
        # 每个 Alias 节点恰有一条出边，故从每个未访问别名节点沿链游走即可：
        # 游走中撞回本路径上的节点即无保护环，环序列给出定位。
        WHITE, GRAY, BLACK = 0, 1, 2
        mark: list[int] = [WHITE] * n
        for start in range(n):
            if start not in reachable or mark[start] != WHITE:
                continue
            path: list[int] = []
            v = start
            while True:
                if mark[v] == BLACK or nodes[v].kind != ALIAS:
                    # 已确认无环，或别名链在结构节点处终止。
                    for u in path:
                        mark[u] = BLACK
                    mark[v] = BLACK
                    break
                if mark[v] == GRAY:
                    assert v in path  # GRAY 只可能属于当前游走
                    i = path.index(v)
                    cycle_nodes = path[i:] + [v]
                    chain = " -> ".join(f"node {u}" for u in cycle_nodes)
                    raise UnguardedRecursionError(
                        "unguarded recursive type: alias-only cycle "
                        f"{chain}; a recursive reference must be guarded by a "
                        "Product/Sum/Function constructor (μX.X is rejected, "
                        "μX.Product{a: X} and μX. X -> Int are accepted)"
                    )
                mark[v] = GRAY
                path.append(v)
                v = nodes[v].target  # type: ignore[union-attr]

    @property
    def root(self) -> int:
        return self._root

    @property
    def nodes(self) -> tuple[Node, ...]:
        return self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def __getitem__(self, index: int) -> Node:
        return self._nodes[index]

    def resolve_alias(self, index: int) -> int:
        """跳过透明的 Alias 链，返回第一个结构节点（Int/Bool/Product/Sum/
        Function）的编号。

        图经构造期受保护性校验，从根可达部分不存在纯 Alias 环，故此过程必然
        终止；结果按图缓存。等价/子类型比较用它把“位置”归一到结构层，
        Alias 本身不计入结构深度。
        """
        cache = self._resolve
        if index in cache:
            return cache[index]
        path: list[int] = []
        cur = index
        seen_local: set[int] = set()
        while self._nodes[cur].kind == ALIAS:
            if cur in seen_local:  # 防御：不可达部分的无保护环不应走到这里
                raise UnguardedRecursionError(
                    "alias-only cycle encountered while resolving aliases "
                    f"(at node {cur})",
                    f"node {cur}",
                )
            seen_local.add(cur)
            path.append(cur)
            cur = self._nodes[cur].target  # type: ignore[union-attr]
        for v in path:
            cache[v] = cur
        cache[cur] = cur
        return cur

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"TypeGraph(n={len(self._nodes)}, root={self._root})"
