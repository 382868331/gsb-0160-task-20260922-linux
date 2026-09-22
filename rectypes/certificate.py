"""等价关系证书及其**独立**验证器。

证书是一个以根对为成员的节点对关系 ``R``，并满足局部一致性：
对 R 中每一对 ``(u, v)``，

* 两端节点 kind 相同；
* 原子节点要求同为 Int 或同为 Bool；
* Product/Sum 要求字段/标签名集合相同，且每个同名子节点对也在 R 中；
* Function 要求参数个数相同、按位置每个参数对在 R 中、返回对在 R 中。

满足以上条件的 R 是一个互模拟（双拟）关系，因而根对等价。该验证器在本文件中
独立重新实现一致性判定，不导入也不调用 :mod:`rectypes.checker`，
因此可用于独立检验算法给出的证书。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import CertificateInvalid
from .model import TypeGraph


@dataclass(frozen=True)
class Certificate:
    """等价关系证书：纯数据，可序列化检查。

    :param roots: 根对 ``(root1, root2)``。
    :param pairs: 关系中的全部节点对（含根对），按确定性顺序排列。
    """

    roots: tuple[object, object]
    pairs: tuple[tuple[object, object], ...]
    # 记录参与比较的两个图的规模，便于打印与排查；不参与验证。
    graph_sizes: tuple[int, int] = field(default=(0, 0))

    def __str__(self) -> str:
        lines = [
            f"equivalence certificate: {len(self.pairs)} related pair(s)",
            f"  roots: {self.roots[0]!r} ~ {self.roots[1]!r}",
        ]
        for u, v in self.pairs:
            lines.append(f"  {u!r} ~ {v!r}")
        return "\n".join(lines)


def _node(graph: TypeGraph, ident: object) -> Mapping[str, Any]:
    try:
        return graph.nodes[ident]
    except KeyError:
        raise CertificateInvalid(
            f"pair references unknown node {ident!r}", pair=(ident, ident)
        ) from None


def verify_certificate(cert: Certificate, g1: TypeGraph, g2: TypeGraph) -> bool:
    """独立验证证书。合法返回 ``True``；发现任何问题抛
    :class:`~rectypes.errors.CertificateInvalid`。

    验证内容：根对存在于关系中；关系无重复；每一对的局部一致性，
    包括所有同名字段对、按位参数对、返回对均在关系内。
    """
    pairs: set[tuple[object, object]] = set()
    for pair in cert.pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise CertificateInvalid(f"ill-formed pair {pair!r}")
        if pair in pairs:
            raise CertificateInvalid(f"duplicate pair {pair!r}", pair=pair)
        pairs.add(pair)

    if cert.roots != (g1.root, g2.root):
        raise CertificateInvalid(
            f"certificate roots {cert.roots!r} do not match graph roots "
            f"({g1.root!r}, {g2.root!r})"
        )
    if cert.roots not in pairs:
        raise CertificateInvalid("root pair is not a member of the relation")

    for u, v in sorted(pairs, key=_pair_sort_key):
        n1 = _node(g1, u)
        n2 = _node(g2, v)
        k1, k2 = n1["kind"], n2["kind"]
        if k1 != k2:
            raise CertificateInvalid(
                f"kind mismatch in related pair: {k1!r} vs {k2!r}", pair=(u, v)
            )

        if k1 in ("Int", "Bool"):
            continue

        if k1 in ("Product", "Sum"):
            f1 = dict(n1["fields"])
            f2 = dict(n2["fields"])
            s1, s2 = set(f1), set(f2)
            if s1 != s2:
                raise CertificateInvalid(
                    f"{k1} field-name sets differ: only-left={sorted(s1 - s2)!r}, "
                    f"only-right={sorted(s2 - s1)!r}",
                    pair=(u, v),
                )
            for name in sorted(s1):
                child = (f1[name], f2[name])
                if child not in pairs:
                    raise CertificateInvalid(
                        f"{k1} field {name!r} child pair {child!r} "
                        "is missing from the relation",
                        pair=(u, v),
                    )
        else:  # Function
            p1, p2 = n1["params"], n2["params"]
            if len(p1) != len(p2):
                raise CertificateInvalid(
                    f"parameter count differs: {len(p1)} vs {len(p2)}", pair=(u, v)
                )
            for i, (a, b) in enumerate(zip(p1, p2)):
                child = (a, b)
                if child not in pairs:
                    raise CertificateInvalid(
                        f"param #{i} child pair {child!r} is missing from the relation",
                        pair=(u, v),
                    )
            child = (n1["result"], n2["result"])
            if child not in pairs:
                raise CertificateInvalid(
                    f"result child pair {child!r} is missing from the relation",
                    pair=(u, v),
                )

    return True


def _pair_sort_key(pair: tuple[object, object]) -> tuple[str, str, str, str]:
    return (
        str(type(pair[0])),
        str(pair[0]),
        str(type(pair[1])),
        str(pair[1]),
    )
