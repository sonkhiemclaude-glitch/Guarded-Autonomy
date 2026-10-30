"""Statistics used in the paper: 95% t-intervals over seeds (Sec. 6.1) and the exact paired
Wilcoxon signed-rank test (Sec. 6.2). Pure Python + math; no SciPy dependency.
"""
from __future__ import annotations

import logging
import math
from itertools import product
from typing import Sequence, Tuple

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- Student t
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta function (Lentz's method)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    if df <= 0:
        raise ValueError("df must be positive")
    x = df / (df + t * t)
    tail = 0.5 * regularized_incomplete_beta(df / 2.0, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


def t_ppf(q: float, df: float) -> float:
    """Quantile of Student's t by bisection on the CDF (|error| < 1e-10)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if q == 0.5:
        return 0.0
    lo, hi = -1e3, 1e3
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return 0.5 * (lo + hi)


def t_interval(values: Sequence[float], conf: float = 0.95) -> Tuple[float, float]:
    """Mean and half-width t_{(1+conf)/2, n-1} * s / sqrt(n) (Sec. 6.1).

    n = 0 raises; n = 1 returns NaN half-width (no variance estimate) and logs a warning.
    """
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        raise ValueError("t_interval of an empty sample")
    mean = sum(vals) / n
    if n == 1:
        log.warning("t_interval with n=1: half-width undefined (NaN)")
        return mean, float("nan")
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return mean, t_ppf(0.5 + conf / 2.0, n - 1) * math.sqrt(var) / math.sqrt(n)


# ----------------------------------------------------------------------------- Wilcoxon
def _ranks_abs(d: Sequence[float]) -> list[float]:
    order = sorted(range(len(d)), key=lambda i: abs(d[i]))
    ranks = [0.0] * len(d)
    i = 0
    while i < len(d):
        j = i
        while j + 1 < len(d) and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) < 1e-12:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def wilcoxon_signed_rank(x: Sequence[float], y: Sequence[float], exact_max_n: int = 20) -> Tuple[float, float, int]:
    """Two-sided paired Wilcoxon signed-rank test of y - x.

    Returns (W+, p, n_nonzero). Zero differences are dropped (Wilcoxon's convention); ties get
    average ranks. Exact enumeration for n_nonzero <= ``exact_max_n``; otherwise a normal
    approximation with tie and continuity correction.
    """
    if len(x) != len(y):
        raise ValueError("paired samples must have equal length")
    d = [b - a for a, b in zip(x, y) if abs(b - a) > 1e-12]
    n = len(d)
    if n == 0:
        return 0.0, 1.0, 0
    ranks = _ranks_abs(d)
    w_plus = sum(r for r, v in zip(ranks, d) if v > 0)
    total = sum(ranks)
    if n <= exact_max_n:
        obs = min(w_plus, total - w_plus)
        count = 0
        for signs in product((0, 1), repeat=n):
            w = sum(r for r, s in zip(ranks, signs) if s)
            if min(w, total - w) <= obs + 1e-9:
                count += 1
        return w_plus, count / 2 ** n, n
    mean = n * (n + 1) / 4.0
    # tie correction
    from collections import Counter
    ties = Counter(ranks).values()
    var = n * (n + 1) * (2 * n + 1) / 24.0 - sum(t ** 3 - t for t in ties) / 48.0
    z = (abs(w_plus - mean) - 0.5) / math.sqrt(var)
    p = math.erfc(z / math.sqrt(2.0))
    return w_plus, min(1.0, p), n
