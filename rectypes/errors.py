"""递归类型等价检查库的错误类型。

所有本库抛出的错误都继承自 :class:`RecTypeError`，便于调用方一次性捕获。
校验类错误带有 ``location`` 字段，尽量定位到具体节点与边。
"""

from __future__ import annotations


class RecTypeError(Exception):
    """本库所有自定义异常的基类。"""


class GraphValidationError(RecTypeError):
    """类型图在构造期未通过结构校验。

    :param message: 人类可读的错误说明。
    :param location: 可定位的位置描述，例如 ``"node 'x' 的字段 'a'"``。
    """

    def __init__(self, message: str, *, location: str | None = None) -> None:
        if location is not None:
            message = f"{message} (at {location})"
        super().__init__(message)
        self.location = location


class InvalidNodeError(GraphValidationError):
    """节点值/字段名/参数本身的类型不合法，或使用了被拒绝的取值。"""


class DuplicateFieldError(GraphValidationError):
    """Product/Sum 内部出现重复字段名。"""

    def __init__(self, field_name: str, location: str | None = None) -> None:
        super().__init__(f"duplicate field name {field_name!r}", location=location)
        self.field_name = field_name


class ArityError(GraphValidationError):
    """节点元数不正确（空 Product/Sum、无参数 Function 等）。"""


class DanglingEdgeError(GraphValidationError):
    """边指向了图中不存在的节点。"""

    def __init__(self, target: object, location: str | None = None) -> None:
        super().__init__(
            f"dangling edge to undefined node {target!r}", location=location
        )
        self.target = target


class UnreachableNodeError(GraphValidationError):
    """存在从根节点不可达的节点；有根图不允许携带语义不明的冗余节点。"""

    def __init__(self, unreachable: list[object]) -> None:
        self.unreachable = unreachable
        super().__init__(
            f"{len(unreachable)} node(s) are unreachable from the root: "
            f"{unreachable!r}"
        )


class GraphTooLargeError(GraphValidationError):
    """节点数超过接口上限 300。"""


class BudgetExhaustedError(RecTypeError):
    """搜索预算耗尽。

    该异常与“已证明不等价”严格区分：它只说明在给定预算内算法没有算完，
    不代表两个类型等价或不等价。
    """

    def __init__(self, used: int, budget: int) -> None:
        super().__init__(
            f"search budget exhausted: {used} work unit(s) used, budget={budget}"
        )
        self.work_units_used = used
        self.budget = budget


class CertificateInvalid(RecTypeError):
    """证书独立校验未通过（关系表不封闭、头部不一致或根对缺失等）。"""

    def __init__(self, message: str, *, pair: tuple[object, object] | None = None):
        if pair is not None:
            message = f"{message} (pair {pair[0]!r} ~ {pair[1]!r})"
        super().__init__(message)
        self.pair = pair
