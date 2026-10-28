"""Judge/human agreement (Cohen's kappa), pre-registered threshold 0.7."""

from __future__ import annotations


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    labels = sorted({x for p in pairs for x in p})
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == lab for a, _ in pairs) / n) * (sum(b == lab for _, b in pairs) / n)
             for lab in labels)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0
