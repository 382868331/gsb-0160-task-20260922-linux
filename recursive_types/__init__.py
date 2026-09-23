"""显式节点的递归类型：equi-recursive 等价检查与结构子类型判断。

公开接口::

    from recursive_types import (
        TypeGraph, Field,
        IntNode, BoolNode, ProductNode, SumNode, FunctionNode, AliasNode,
        check_equivalence, are_equivalent, verify_certificate,
        EquivalenceCertificate, Divergence,
        check_subtype, is_subtype, verify_subtype_certificate,
        SubtypeCertificate, SubtypeFailure,
        RecTypeError, TypeGraphError, ArityError, DanglingEdgeError,
        DuplicateFieldError, InvalidNodeError, InvalidRootError,
        GraphSizeError, BudgetExceededError, UnguardedRecursionError,
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
    resolve_alias,
)
from .subtyping import (
    DEFAULT_SUBTYPE_BUDGET,
    SubtypeCertificate,
    SubtypeFailure,
    SubtypeResult,
    check_subtype,
    is_subtype,
    verify_subtype_certificate,
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
    "resolve_alias",
    # 等价
    "check_equivalence",
    "are_equivalent",
    "verify_certificate",
    "EquivalenceCertificate",
    "Divergence",
    "Step",
    "Mismatch",
    "EquivalenceResult",
    "DEFAULT_BUDGET",
    # 子类型
    "check_subtype",
    "is_subtype",
    "verify_subtype_certificate",
    "SubtypeCertificate",
    "SubtypeFailure",
    "SubtypeResult",
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
    "BudgetExceededError",
    "UnguardedRecursionError",
]
