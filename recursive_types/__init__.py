"""显式节点的递归类型判定：equi-recursive 等价与结构子类型。

公开接口::

    from recursive_types import (
        TypeGraph, Field,
        IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode,
        # 等价
        check_equivalence, are_equivalent, verify_certificate,
        EquivalenceCertificate, Divergence,
        # 结构子类型
        check_subtype, is_subtype, verify_subtype_certificate,
        SubtypingCertificate, SubtypeFailure,
        Step, Mismatch,
        RecTypeError, TypeGraphError, ArityError, DanglingEdgeError,
        DuplicateFieldError, InvalidNodeError, InvalidRootError,
        GraphSizeError, UnguardedRecursionError, BudgetExceededError,
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
    UnguardedRecursionError,
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
from .subtyping import (
    DEFAULT_SUBTYPE_BUDGET,
    SubtypeFailure,
    SubtypingCertificate,
    SubtypingResult,
    check_subtype,
    is_subtype,
    verify_subtype_certificate,
)
from .model import (
    ALIAS,
    BOOL,
    FUNCTION,
    INT,
    PRODUCT,
    SUM,
    MAX_NODES,
    AliasNode,
    BoolNode,
    Field,
    FunctionNode,
    IntNode,
    Node,
    ProductNode,
    SumNode,
    TypeGraph,
)

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
    "AliasNode",
    "INT",
    "BOOL",
    "PRODUCT",
    "SUM",
    "FUNCTION",
    "ALIAS",
    "MAX_NODES",
    # 等价算法
    "check_equivalence",
    "are_equivalent",
    "verify_certificate",
    "EquivalenceCertificate",
    "Divergence",
    # 子类型算法
    "check_subtype",
    "is_subtype",
    "verify_subtype_certificate",
    "SubtypingCertificate",
    "SubtypeFailure",
    "Step",
    "Mismatch",
    "EquivalenceResult",
    "SubtypingResult",
    "DEFAULT_BUDGET",
    "DEFAULT_SUBTYPE_BUDGET",
    # 错误
    "RecTypeError",
    "TypeGraphError",
    "InvalidNodeError",
    "ArityError",
    "DuplicateFieldError",
    "DanglingEdgeError",
    "InvalidRootError",
    "GraphSizeError",
    "UnguardedRecursionError",
    "BudgetExceededError",
]
