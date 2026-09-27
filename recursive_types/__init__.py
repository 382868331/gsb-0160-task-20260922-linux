"""显式节点的递归类型等价检查（equi-recursive type equivalence）。

公开接口::

    from recursive_types import (
        TypeGraph, Field,
        IntNode, BoolNode, ProductNode, SumNode, FunctionNode,
        check_equivalence, are_equivalent, verify_certificate,
        canonicalize, canonical_node_of, Canonicalization,
        EquivalenceCertificate, Divergence, Step, Mismatch,
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
from .canonicalization import (
    DEFAULT_CANONICAL_BUDGET,
    Canonicalization,
    canonical_node_of,
    canonicalize,
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
    "canonicalize",
    "canonical_node_of",
    "Canonicalization",
    "DEFAULT_CANONICAL_BUDGET",
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
