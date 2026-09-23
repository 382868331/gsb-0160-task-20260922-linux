"""可定位的错误类型层级。

所有由本库主动抛出的错误都继承自 :class:`RecTypeError`，
且 ``str(exc)`` 以 ``"<location>: <reason>"`` 的形式给出可定位信息。
"""

from __future__ import annotations


class RecTypeError(Exception):
    """本库所有自定义错误的基类。"""


class TypeGraphError(RecTypeError):
    """类型图构造期非法输入。

    :param message: 具体原因。
    :param location: 可定位前缀，如 ``"node 3"``、``"root"``；为 ``None``
        时错误字符串仅包含原因。
    """

    def __init__(self, message: str, location: str | None = None) -> None:
        self.location = location
        if location:
            full = f"{location}: {message}"
        else:
            full = message
        super().__init__(full)


class InvalidNodeError(TypeGraphError):
    """节点/字段/slot 的 Python 类型或节点种类非法（含 bool、float 冒充整数）。"""


class ArityError(TypeGraphError):
    """节点元数与其构造子不符（如 Int 带边、Function 缺返回、Product 无字段）。"""


class DuplicateFieldError(TypeGraphError):
    """同一个 Product/Sum 节点内出现重复字段名。"""


class DanglingEdgeError(TypeGraphError):
    """边指向不存在的节点编号。"""


class InvalidRootError(TypeGraphError):
    """根节点编号非法（非严格 int、越界、bool）。"""


class GraphSizeError(TypeGraphError):
    """节点数不在 1..MAX_NODES 范围内。"""


class UnguardedRecursionError(TypeGraphError):
    """存在**无保护递归**环：环上只有裸 :class:`AliasNode`（别名透传），
    没有经过任何 Product/Sum/Function 构造子（即 μX.X 一类方程）。

    这样的方程没有唯一的无穷展开树，等价与子类型均无从定义，构造期即拒绝。
    异常消息给出环上的节点编号序列，便于定位。
    """


class BudgetExceededError(RecTypeError):
    """协同检查的搜索预算在得出结论前耗尽。

    这与“证明两类型不等价”（:class:`Divergence`）严格区分：
    抛出本异常表示**未知**，返回分歧路径表示**已证伪**。
    """

    def __init__(self, budget: int, checked_pairs: int) -> None:
        self.budget = budget
        self.checked_pairs = checked_pairs
        super().__init__(
            f"pair-check budget exhausted: budget={budget}, "
            f"pairs checked before stop={checked_pairs}; result unknown"
        )
