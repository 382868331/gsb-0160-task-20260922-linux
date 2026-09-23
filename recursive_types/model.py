"""公开数据结构：类型节点与有根类型图。

节点种类（判别式见各节点的 ``kind`` 常量）：

* ``Int`` / ``Bool``：叶子，元数 0；
* ``Product`` / ``Sum``：带**唯一**字段名的命名字段集合，字段按名（而非按位置）
  对应；元数 >= 1。``Product`` 的字段带可变性标记（默认只读）：只读字段协变、
  可写字段不变；``Sum`` 的负载都是只读的（求和变体不存在可写槽）。
* ``Function``：有序参数列表（>= 1）与单个返回类型。
* ``Alias``：**透明**别名，只有一条裸边，本身不是类型构造子，在等价/子类型
  检查中被直接穿透。它的唯一用途是表达“方程体直接等于递归变量”的写法
  （μX. X）；若一张图里出现只经过 Alias 的环，则为**无保护递归**，构造期拒绝。

节点编号仅用于在*单张图内*表达边（共享与递归回边），从不参与语义比较：
两张图中编号相同但展开树不同的节点不等价，反之共享子图与复制子图不被区分。
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
    """Product/Sum 的一个命名字段：``name -> target``。

    :param readonly: 仅对 Product 有意义。``True``（默认）为只读字段，
        子类型规则中协变；``False`` 为可写字段，要求不变（双侧类型等价）。
        只接受严格 ``bool``（``1``/``0`` 这类非 bool 值在构图时拒绝）。
        Sum 的负载恒为只读；此处传 ``False`` 会在构图时拒绝。
    """

    name: str
    target: int
    readonly: bool = True


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
    """透明别名：唯一一条裸边 ``target``，不是类型构造子。

    等价/子类型检查中直接穿透到 ``target``。它只用于表达递归方程里
    “无构造子包裹”的位置；只由 Alias 构成的环即无保护递归，构图时拒绝。
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

    __slots__ = ("_nodes", "_root", "_resolved")

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
        # 所有边已确认合法后，再做全图无保护递归检测（沿裸 Alias 边找环）。
        self._reject_unguarded_cycles(prepared)
        self._nodes: tuple[Node, ...] = tuple(prepared)
        self._root = root_idx
        # 无环 Alias 图：一次性把每个 Alias 解析到最终构造子节点，O(n)。
        self._resolved: tuple[int, ...] = tuple(
            self._resolve_aliases(self._nodes)
        )

    @staticmethod
    def _resolve_aliases(nodes: tuple[Node, ...]) -> list[int]:
        resolved: list[int] = list(range(len(nodes)))
        for i, node in enumerate(nodes):
            if node.kind != ALIAS:
                continue
            path: list[int] = []
            x = i
            while nodes[x].kind == ALIAS:
                if resolved[x] != x:
                    target = resolved[x]
                    break
                path.append(x)
                x = nodes[x].target  # type: ignore[attr-defined]
            else:
                target = x
            for v in path:
                resolved[v] = target
        return resolved

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
            readonly = field.readonly
            if type(readonly) is not bool:
                raise InvalidNodeError(
                    f"field {name!r} readonly must be a strict bool "
                    f"(got {type(readonly).__name__}: {readonly!r})",
                    floc,
                )
            if isinstance(node, SumNode) and not readonly:
                raise InvalidNodeError(
                    f"Sum field {name!r} payload cannot be writable: "
                    f"sum-variant payloads are read-only",
                    loc,
                )
            fields.append(Field(name, target, readonly))
        if isinstance(node, ProductNode):
            return ProductNode(tuple(fields))
        return SumNode(tuple(fields))

    @staticmethod
    def _validate_alias(node: AliasNode, loc: str, n: int) -> AliasNode:
        target = _as_int(node.target, loc, "Alias target")
        if not 0 <= target < n:
            raise DanglingEdgeError(
                f"Alias points to {target}, valid range is [0, {n - 1}]",
                loc,
            )
        return AliasNode(target)

    @staticmethod
    def _reject_unguarded_cycles(nodes: tuple[Node, ...] | list[Node]) -> None:
        """沿裸 Alias 边检测无保护递归环。

        Alias 是唯一不带构造子的边；只经过 Alias 的环对应 μX.X 型方程，
        没有受保护（contractive）的唯一解，构图期直接拒绝。
        任何经过 Product/Sum/Function 的环都是受保护递归，这里不追踪。
        Alias 图中每节点出度恰为 0（非 Alias）或 1（Alias），沿链探查即可。
        """
        n = len(nodes)
        # 0=未处理, 1=当前链上, 2=已确认安全；非 Alias 节点永不被标记。
        color = [0] * n
        for start in range(n):
            if color[start] != 0 or nodes[start].kind != ALIAS:
                continue
            path: list[int] = []
            x = start
            while True:
                nx = nodes[x]
                if nx.kind != ALIAS or color[x] == 2:
                    for v in path:
                        color[v] = 2
                    break
                if color[x] == 1:
                    # gray 节点必在当前链上（前一链结束时其节点全部转黑）。
                    idx = path.index(x)
                    cycle = path[idx:] + [x]
                    raise UnguardedRecursionError(
                        "unguarded recursion: a cycle through bare Alias edges "
                        "has no guarding constructor (Product/Sum/Function): "
                        f"{' -> '.join(str(v) for v in cycle)}",
                        f"node {x}",
                    )
                color[x] = 1
                path.append(x)
                x = nx.target  # type: ignore[assignment]

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

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"TypeGraph(n={len(self._nodes)}, root={self._root})"


def resolve_alias(g: TypeGraph, index: int) -> int:
    """穿透透明 :class:`AliasNode` 链，返回第一个真正构造子节点的编号。

    构图期已排除只经过 Alias 的环（无保护递归），且结果已在构图时预算好，
    故这里为 O(1)；``index`` 本身就是构造子时原样返回。
    """
    return g._resolved[index]
