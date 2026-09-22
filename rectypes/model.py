"""类型图数据结构与构造期校验。

公开数据结构
------------

节点是 ``dict``， ``"kind"`` 为以下五者之一（字符串字面量，不用整数编码）：

``{"kind": "Int"}``
    整数原子类型。
``{"kind": "Bool"}``
    布尔原子类型。
``{"kind": "Product", "fields": [(名称, 目标), ...]}``
    记录式积类型；字段名在节点内唯一，按名对应，与书写顺序无关。
``{"kind": "Sum", "fields": [(名称, 目标), ...]}``
    带标签和类型；标签名在节点内唯一，按名对应，与书写顺序无关。
``{"kind": "Function", "params": [目标, ...], "result": 目标}``
    函数类型；参数**有序**（按位置对应）且必须至少一个，返回值恰一个。

边的目标是节点标识。标识可以是任意 ``str`` 或任何非 ``bool`` 的 ``int``；
节点编号只用于定位图结构，绝不参与语义比较。

类型图 :class:`TypeGraph` 由 ``{标识: 节点}`` 映射和一个根标识构成。
构造时执行全部结构校验（悬空边、元数、重复字段、不可达节点、节点数上限）；
校验失败抛 :class:`~rectypes.errors.GraphValidationError`，且对象不会被创建。
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from .errors import (
    ArityError,
    DanglingEdgeError,
    DuplicateFieldError,
    GraphTooLargeError,
    InvalidNodeError,
    UnreachableNodeError,
)

MAX_NODES = 300
"""单张类型图允许的最大节点数（接口边界）。"""

ATOMIC_KINDS = ("Int", "Bool")
COMPOSITE_KINDS = ("Product", "Sum", "Function")
ALL_KINDS = ATOMIC_KINDS + COMPOSITE_KINDS


def _reject_nonfinite_numbers(value: Any, where: str) -> None:
    """递归扫描节点值，拒绝 NaN / Infinity / -Infinity。

    节点结构里正常情况下不会出现浮点数；该检查保证任何数值输入都不会
    悄悄带入非有限值（例如把字段名误写成 ``float("nan")`` 会在别处报类型错，
    这里是数值约束的统一防线）。
    """
    if isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidNodeError(
                f"non-finite number {value!r} is not allowed", location=where
            )
    elif isinstance(value, dict):
        for k, v in value.items():
            _reject_nonfinite_numbers(k, where)
            _reject_nonfinite_numbers(v, where)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_nonfinite_numbers(item, where)


def _validate_identifier(ident: Any, where: str) -> object:
    """节点/字段标识约束：str 任意，int 须非 bool 且有限；其余拒绝。"""
    if isinstance(ident, bool) or not isinstance(ident, (str, int)):
        raise InvalidNodeError(
            f"identifier must be str or int (bool rejected), got {type(ident).__name__}",
            location=where,
        )
    return ident


def _validate_field_name(name: Any, where: str) -> str:
    if not isinstance(name, str):
        raise InvalidNodeError(
            f"field name must be str, got {type(name).__name__}", location=where
        )
    return name


def _targets_of(node: Mapping[str, Any]) -> list[object]:
    """取出节点全部出边（不做校验，校验在 :class:`TypeGraph` 构造时完成）。"""
    kind = node["kind"]
    if kind in ("Product", "Sum"):
        return [target for _, target in node["fields"]]
    if kind == "Function":
        return list(node["params"]) + [node["result"]]
    return []


def validate_nodes(nodes: Any, *, where: str = "type graph") -> dict[object, dict]:
    """对原始 ``{id: node}`` 映射做完整结构校验，返回规范化后的新映射。

    纯函数：不修改输入。校验项：
      * 映射本身类型、键类型；
      * 节点数上限 :data:`MAX_NODES`；
      * 节点为 dict、kind 合法；
      * Product/Sum：``fields`` 为非空 ``(名称, 目标)`` 列表、名称唯一；
      * Function：``params`` 为非空列表、``result`` 恰好一个；
      * 原子节点无载荷；
      * 所有边目标都存在于映射中（无悬空边）。

    可达性检查需要根节点，在 :class:`TypeGraph` 构造时单独完成。
    """
    if not isinstance(nodes, Mapping):
        raise InvalidNodeError(
            f"nodes must be a mapping id -> node, got {type(nodes).__name__}",
            location=where,
        )
    if len(nodes) > MAX_NODES:
        raise GraphTooLargeError(
            f"graph has {len(nodes)} nodes, limit is {MAX_NODES}", location=where
        )

    normalized: dict[object, dict] = {}
    seen_ids: set[object] = set()
    for raw_id, node in nodes.items():
        ident = _validate_identifier(raw_id, where=where)
        if ident in seen_ids:  # 理论上 Mapping 不会有重复键，防线而已
            raise InvalidNodeError(f"duplicate node id {ident!r}", location=where)
        seen_ids.add(ident)

        loc = f"{where}, node {ident!r}"
        _reject_nonfinite_numbers(node, where=loc)
        if not isinstance(node, Mapping):
            raise InvalidNodeError(
                f"node must be a dict, got {type(node).__name__}", location=loc
            )
        kind = node.get("kind")
        if kind not in ALL_KINDS:
            raise InvalidNodeError(
                f"kind must be one of {ALL_KINDS}, got {kind!r}", location=loc
            )
        unexpected = set(node) - {"kind", "fields", "params", "result"}
        if unexpected:
            raise InvalidNodeError(
                f"unexpected keys {sorted(unexpected)!r} for kind {kind!r}",
                location=loc,
            )

        if kind in ("Product", "Sum"):
            fields = node.get("fields")
            if not isinstance(fields, list) or not fields:
                raise ArityError(
                    f"{kind} requires a non-empty 'fields' list", location=loc
                )
            norm_fields: list[tuple[str, object]] = []
            names: set[str] = set()
            for index, entry in enumerate(fields):
                floc = f"{loc}, field #{index}"
                if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                    raise InvalidNodeError(
                        f"{kind} field must be a (name, target) pair", location=floc
                    )
                name = _validate_field_name(entry[0], where=floc)
                target = _validate_identifier(
                    entry[1], where=f"{floc} target"
                )
                if name in names:
                    raise DuplicateFieldError(name, location=loc)
                names.add(name)
                norm_fields.append((name, target))
            normalized[ident] = {"kind": kind, "fields": norm_fields}

        elif kind == "Function":
            if "result" not in node:
                raise ArityError(
                    "Function requires exactly one 'result'", location=loc
                )
            params = node.get("params")
            if not isinstance(params, list) or not params:
                raise ArityError(
                    "Function requires a non-empty 'params' list", location=loc
                )
            norm_params: list[object] = [
                _validate_identifier(p, where=f"{loc}, param #{i}")
                for i, p in enumerate(params)
            ]
            result = _validate_identifier(
                node["result"], where=f"{loc}, result"
            )
            normalized[ident] = {
                "kind": "Function",
                "params": norm_params,
                "result": result,
            }
        else:
            unexpected_payload = set(node) - {"kind"}
            if unexpected_payload:
                raise InvalidNodeError(
                    f"atomic {kind} node carries keys {sorted(unexpected_payload)!r}",
                    location=loc,
                )
            normalized[ident] = {"kind": kind}

    # 悬空边检查（所有节点规范化后统一做，错误信息可定位来源）
    for ident, node in normalized.items():
        for target in _targets_of(node):
            if target not in seen_ids:
                raise DanglingEdgeError(
                    target, location=f"node {ident!r}"
                )

    return normalized


class TypeGraph:
    """有根类型图。

    :param nodes: ``{标识: 节点}`` 映射；构造时完整校验，不保留对传入对象的依赖
        （内部使用校验后的规范化副本）。
    :param root: 根节点标识，必须存在。
    :raises GraphValidationError: 任一结构约束被违反，或存在根不可达节点。
    """

    __slots__ = ("nodes", "root", "_reachable")

    def __init__(self, nodes: Mapping[object, Mapping[str, Any]], root: object) -> None:
        norm = validate_nodes(nodes, where="type graph")
        root_id = _validate_identifier(root, where="root")
        if root_id not in norm:
            raise DanglingEdgeError(root_id, location="root")

        reachable = self._collect_reachable(norm, root_id)
        unreachable = [i for i in norm if i not in reachable]
        if unreachable:
            raise UnreachableNodeError(
                sorted(unreachable, key=lambda x: (str(type(x)), str(x)))
            )

        self.nodes: dict[object, dict] = norm
        self.root: object = root_id
        self._reachable: frozenset[object] = frozenset(reachable)

    @staticmethod
    def _collect_reachable(
        nodes: Mapping[object, Mapping[str, Any]], root: object
    ) -> set[object]:
        seen: set[object] = {root}
        stack = [root]
        while stack:
            ident = stack.pop()
            for target in _targets_of(nodes[ident]):
                if target not in seen:
                    seen.add(target)
                    stack.append(target)
        return seen

    @property
    def reachable(self) -> frozenset[object]:
        """从根可达的节点集合（校验后恒等于全部节点）。"""
        return self._reachable

    def kind(self, ident: object) -> str:
        return self.nodes[ident]["kind"]

    def children(self, ident: object) -> list[object]:
        """节点的全部子节点（顺序为内部存储顺序，仅用于遍历）。"""
        return _targets_of(self.nodes[ident])

    def __len__(self) -> int:
        return len(self.nodes)

    def __repr__(self) -> str:
        return f"TypeGraph(root={self.root!r}, nodes={len(self.nodes)})"
