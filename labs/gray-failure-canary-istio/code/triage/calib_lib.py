"""Biblioteca da etapa de calibração (plano de 29/10).

Só biblioteca padrão, como o resto de `triage/`. Reúne:
- estatística exata sem scipy: Clopper-Pearson e limite superior de Poisson;
- `learn_threshold`: limite derivado do ruído saudável de uma feature;
- `RelativeRule` e `RuleDetector`: a regra B com limiar, delta e piso parametrizáveis,
  com a mesma máquina de estados do `SubsetDetector` (3 janelas, n >= 30).

`RelativeRule(ratio=1.15, delta_ms=500, floor_ms=1000)` é exatamente a regra B atual
(coberto por test_calibration.py). Com `delta_ms=0` o delta vira relativo: o limiar
é só a razão sobre a baseline.
"""
import math
from dataclasses import dataclass
from statistics import NormalDist, fmean, stdev
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from detector import (
    ERROR_RATE_LIMIT_PCT,
    MIN_SAMPLE,
    WINDOWS_TO_DEGRADE,
    WINDOWS_TO_RECOVER,
    Window,
)


# ---------------------------------------------------------------- estatística exata

def _logpmf(i: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if i == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if i == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p))


def _binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k), X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(math.exp(_logpmf(i, n, p)) for i in range(k + 1)))


def _bisect(f, lo: float, hi: float, iters: int = 80) -> float:
    """Raiz de f em [lo, hi] para f crescente com f(lo) < 0 < f(hi)."""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clopper_pearson(k: int, n: int, conf: float = 0.95, two_sided: bool = True) -> Tuple[float, float]:
    """Intervalo exato para uma proporção k/n.

    two_sided=True (padrão): intervalo bicaudal de nível `conf` (10/10 -> [0,692; 1]).
    two_sided=False: limites unicaudais de nível `conf` (10/10 -> limite inferior 0,741,
    o "cerca de 74%" do post). Em ambos, k=0 dá inferior 0 e k=n dá superior 1.
    """
    if n <= 0:
        return (0.0, 1.0)
    a = (1.0 - conf) / 2.0 if two_sided else (1.0 - conf)
    lo = 0.0 if k <= 0 else _bisect(lambda p: (1.0 - _binom_cdf(k - 1, n, p)) - a, 0.0, 1.0)
    hi = 1.0 if k >= n else _bisect(lambda p: a - _binom_cdf(k, n, p), 0.0, 1.0)
    return (lo, hi)


def _poisson_cdf(k: int, m: float) -> float:
    if m <= 0:
        return 1.0
    term = math.exp(-m)
    total = term
    for i in range(1, k + 1):
        term *= m / i
        total += term
    return min(1.0, total)


def poisson_upper(events: int, exposure: float, conf: float = 0.95) -> float:
    """Limite superior unicaudal de nível `conf` para a taxa (eventos por unidade de
    exposição). 0 eventos em 8 h -> 0,374 por hora (o "0,37" do post)."""
    if exposure <= 0:
        return math.inf
    alpha = 1.0 - conf
    hi = 10.0 + 10.0 * events
    m = _bisect(lambda x: alpha - _poisson_cdf(events, x), 0.0, hi)
    return m / exposure


# ------------------------------------------------------------------ limite aprendido

def quantile(xs: Sequence[float], q: float) -> float:
    """Quantil com interpolação linear (tipo 7)."""
    s = sorted(xs)
    if not s:
        raise ValueError("amostra vazia")
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def learn_threshold(ratios: Iterable[float], alpha: float = 1e-3, min_exceed: int = 10,
                    margin: float = 0.0, min_ratio: float = 1.05) -> Dict[str, float]:
    """Limite de razão (v2/v1 do p95 na mesma janela) a partir de janelas saudáveis.

    Regra escrita: limite = quantil (1 - alpha) da razão saudável, vezes (1 + margin),
    nunca abaixo de `min_ratio` (resolução do próprio p95 por buckets).

    O quantil 99,9% só é estimável pela amostra quando ela tem pelo menos `min_exceed`
    janelas além dele (n * alpha >= min_exceed, ou seja, 10 000 janelas para 99,9%).
    Com menos, o quantil empírico é só o máximo observado e subestima a cauda; então
    usa o maior entre o empírico e o de um ajuste lognormal da razão.
    """
    xs = [r for r in ratios if r and r > 0 and math.isfinite(r)]
    n = len(xs)
    if n < 2:
        raise ValueError("amostra saudável pequena demais")
    emp = quantile(xs, 1.0 - alpha)
    logs = [math.log(x) for x in xs]
    mu, sd = fmean(logs), stdev(logs)
    fit = math.exp(mu + NormalDist().inv_cdf(1.0 - alpha) * sd)
    estimable = n * alpha >= min_exceed
    base = emp if estimable else max(emp, fit)
    thr = max(base * (1.0 + margin), min_ratio)
    return {"threshold": thr, "n": n, "alpha": alpha, "empirical_q": emp, "lognormal_q": fit,
            "max": max(xs), "p50": quantile(xs, 0.5), "p99": quantile(xs, 0.99),
            "estimable_by_sample": estimable, "binding_min_ratio": thr == min_ratio and base < min_ratio}


# -------------------------------------------------------------------- regra e máquina

@dataclass(frozen=True)
class RelativeRule:
    """Regra B parametrizável. degradado se erro > limite OU
    p95 > ratio * baseline E p95 > baseline + delta_ms E p95 > floor_ms."""
    ratio: float
    floor_ms: float = 1000.0
    delta_ms: float = 0.0
    err_limit_pct: float = ERROR_RATE_LIMIT_PCT

    def degraded(self, w: Window) -> bool:
        if w.err_pct > self.err_limit_pct:
            return True
        v, b = w.p95_ms, w.baseline_p95_ms
        return v > self.ratio * b and v > b + self.delta_ms and v > self.floor_ms


class RuleDetector:
    """Mesma máquina de estados do SubsetDetector, com a regra injetada."""

    def __init__(self, rule: RelativeRule):
        self.rule = rule
        self.state = "healthy"
        self.degraded_streak = 0
        self.recovered_streak = 0

    def observe(self, w: Window) -> Optional[str]:
        if w.n < MIN_SAMPLE:
            return None
        if self.rule.degraded(w):
            self.degraded_streak += 1
            self.recovered_streak = 0
            if self.state == "healthy" and self.degraded_streak >= WINDOWS_TO_DEGRADE:
                self.state = "degraded"
                return "detected"
            return None
        self.degraded_streak = 0
        self.recovered_streak += 1
        if self.state == "degraded" and self.recovered_streak >= WINDOWS_TO_RECOVER:
            self.state = "healthy"
            self.recovered_streak = 0
            return "recovered"
        return None


def run_detector(windows: Iterable[Window], rule: RelativeRule) -> List[Tuple[int, str]]:
    det = RuleDetector(rule)
    out = []
    for i, w in enumerate(windows):
        ev = det.observe(w)
        if ev:
            out.append((i, ev))
    return out
