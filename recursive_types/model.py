"""公开数据结构：类型节点与有根类型图。

节点种类（判别式见各节点的 ``kind`` 常量）：

* ``Int`` / ``Bool``：叶子，元数 0；
* ``Product`` / ``Sum``：带**唯一**字段名的命名字段集合，字段按名（而非按位置）
  对应；元数 >= 1；
* ``Function``：有序参数列表（>= 1）与单个返回类型。

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
)

INT = "Int"
BOOL = "Bool"
PRODUCT = "Product"
SUM = "Sum"
FUNCTION = "Function"

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
    """Product/Sum 的一个命名字段：``name -> target``，可带可变性标记。

    ``mutable`` 不参与 check_equivalence 的结构等价判定，
    但在整理共享表示（share_graph）时是合并判据的一部分：
    同名字段的可变性不同则对应节点不得合并，保证合并不丢失可变性。
    """

    name: str
    target: int
    mutable: bool = False


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


Node = Union[IntNode, BoolNode, ProductNode, SumNode, FunctionNode]

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

    __slots__ = ("_nodes", "_root")

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
        self._nodes: tuple[Node, ...] = tuple(prepared)
        self._root = root_idx

    @staticmethod
    def _validate_node(node: object, index: int, n: int) -> Node:
        loc = f"node {index}"
        if not isinstance(
            node, (IntNode, BoolNode, ProductNode, SumNode, FunctionNode)
        ):
            raise InvalidNodeError(
                f"expected a Node (Int/Bool/Product/Sum/Function), "
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
            if type(field.mutable) is not bool:
                raise InvalidNodeError(
                    f"field mutable flag must be a strict bool "
                    f"(got {type(field.mutable).__name__}: {field.mutable!r})",
                    floc,
                )
            target = _as_int(field.target, floc, "field target")
            if not 0 <= target < n:
                raise DanglingEdgeError(
                    f"{node.kind} field {name!r} points to {target}, "
                    f"valid range is [0, {n - 1}]",
                    loc,
                )
            fields.append(Field(name, target, field.mutable))
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
