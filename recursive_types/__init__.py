"""显式节点的递归类型等价检查（equi-recursive type equivalence）。

公开接口::

    from recursive_types import (
        TypeGraph, Field,
        IntNode, BoolNode, ProductNode, SumNode, FunctionNode,
        check_equivalence, are_equivalent, verify_certificate,
    EquivalenceCertificate, Divergence, Step, Mismatch,
    share_graph, SharedForm,
        RecTypeError, TypeGraphError, ArityError, DanglingEdgeError,
        DuplicateFieldError, InvalidNodeError, InvalidRootError,
        GraphSizeError, BudgetExceededError,
        MAX_NODES, DEFAULT_BUDGET,
    )
"""

from __future__ import annotations

from .errors import (
    ArityError,
    BudgetExceededError,
    DanglingEdgeError,
    DuplicateFieldError,
    GraphSizeError,
    InvalidNodeError,
    InvalidRootError,
    RecTypeError,
    TypeGraphError,
)
from .equivalence import (
    DEFAULT_BUDGET,
    Divergence,
    EquivalenceCertificate,
    EquivalenceResult,
    Mismatch,
    Step,
    are_equivalent,
    check_equivalence,
    verify_certificate,
)
from .model import (
    BOOL,
    FUNCTION,
    INT,
    PRODUCT,
    SUM,
    MAX_NODES,
    BoolNode,
    Field,
    FunctionNode,
    IntNode,
    Node,
    ProductNode,
    SumNode,
    TypeGraph,
)
from .sharing import SharedForm, share_graph

__all__ = [
    # 模型
    "TypeGraph",
    "Field",
    "Node",
    "IntNode",
    "BoolNode",
    "ProductNode",
    "SumNode",
    "FunctionNode",
    "INT",
    "BOOL",
    "PRODUCT",
    "SUM",
    "FUNCTION",
    "MAX_NODES",
    # 算法
    "check_equivalence",
    "are_equivalent",
    "verify_certificate",
    "EquivalenceCertificate",
    "Divergence",
    "Step",
    "Mismatch",
    "EquivalenceResult",
    "DEFAULT_BUDGET",
    # 共享表示
    "share_graph",
    "SharedForm",
    # 错误
    "RecTypeError",
    "TypeGraphError",
    "InvalidNodeError",
    "ArityError",
    "DuplicateFieldError",
    "DanglingEdgeError",
    "InvalidRootError",
    "GraphSizeError",
    "BudgetExceededError",
]
