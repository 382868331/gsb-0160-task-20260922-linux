"""rectypes：显式节点递归类型图的 equi-recursive 等价检查库。

最小用法::

    from rectypes import TypeGraph, check_equivalence

    g1 = TypeGraph({"r": {"kind": "Int"}}, root="r")
    g2 = TypeGraph({"s": {"kind": "Int"}}, root="s")
    result = check_equivalence(g1, g2)
    assert result.equivalent and result.certificate is not None

公开接口见各模块文档；最常用的名称在此统一导出。
"""

from __future__ import annotations

from .certificate import Certificate, verify_certificate
from .checker import (
    Divergence,
    EquivalenceResult,
    Step,
    are_equivalent,
    check_equivalence,
)
from .errors import (
    ArityError,
    BudgetExhaustedError,
    CertificateInvalid,
    DanglingEdgeError,
    DuplicateFieldError,
    GraphTooLargeError,
    GraphValidationError,
    InvalidNodeError,
    RecTypeError,
    UnreachableNodeError,
)
from .model import MAX_NODES, TypeGraph

__all__ = [
    "MAX_NODES",
    "TypeGraph",
    "check_equivalence",
    "are_equivalent",
    "EquivalenceResult",
    "Divergence",
    "Step",
    "Certificate",
    "verify_certificate",
    "RecTypeError",
    "GraphValidationError",
    "InvalidNodeError",
    "DuplicateFieldError",
    "ArityError",
    "DanglingEdgeError",
    "UnreachableNodeError",
    "GraphTooLargeError",
    "BudgetExhaustedError",
    "CertificateInvalid",
]
