"""Detecção de degradação por subset (seções 2 e 2.3 da spec revisada).

Módulo puro: não depende de Kubernetes nem de Prometheus. Recebe janelas
de 60 s já agregadas e devolve eventos de transição.
"""

import math
from dataclasses import dataclass
from typing import Optional

MIN_SAMPLE = 30
ERROR_RATE_LIMIT_PCT = 5.0
P95_RATIO_LIMIT = 2.0
P95_ABS_LIMIT_MS = 1000.0
WINDOWS_TO_DEGRADE = 3
WINDOWS_TO_RECOVER = 3

# Regras de latência. B é o padrão do agente; A fica como referência.
# B e C usam o mesmo limiar relativo; C mede a média em vez do p95.
RULE_A = "A"
RULE_B = "B"
RULE_C = "C"
RULES = (RULE_A, RULE_B, RULE_C)
# 1.15 (era 1.3 até 2026-10-28): com latência variável (G4, spec 10.1 item 12),
# 1.3 detectava a falha parcial de 10% em 1/10 execuções e 1.15 em 10/10, sem
# falso alarme em 8 h de controle com ruído. Sem ruído, os dois dão o mesmo
# resultado em todas as rodadas anteriores (o delta de 500 ms é que decide).
RELATIVE_RATIO_LIMIT = 1.15
RELATIVE_DELTA_MS = 500.0

# Candidatas em avaliação (PRE-REGISTRO v4). NÃO são o padrão do agente; ficam fora de
# `RULES` para que mix_test.compare e noise_sim continuem iterando só A, B e C.
#   BF: regra B com piso e delta por feature (G5).
#   D : fração de requisições acima de um limite de latência (L, escolhido por feature
#       na coleta) comparada com a da v1 na mesma janela. Usa as ~n requisições da janela
#       e não as ~4 da cauda do p95. Precisa do vetor de buckets; sem ele não dispara.
RULE_BF = "BF"
RULE_D = "D"
ALL_RULES = RULES + (RULE_BF, RULE_D)

# PROVISÓRIO: valores iniciais para a seleção offline (Fase 2). Congelados no PRE-REGISTRO v4.
# (piso_ms, delta_ms) por feature. dashboard tem p95 saudável de 1 a 5 ms: o piso de
# 1000 ms o deixava cego (spec 10.1, item 9); 250 ms é borda de bucket existente.
PER_FEATURE_LATENCY = {"dashboard": (250.0, 0.0)}
DEFAULT_FEATURE_LATENCY = (P95_ABS_LIMIT_MS, RELATIVE_DELTA_MS)
SLOW_FRAC_DELTA = 0.05   # diferença mínima de fração lenta (v2 - v1)
SLOW_FRAC_Z = 1.645      # z unicaudal de duas proporções (alfa = 0,05 por janela)
_EPS = 1e-9              # 0,15 - 0,10 vale 0,04999... em float; o limite é inclusivo


@dataclass(frozen=True)
class Window:
    n: int
    err_pct: float
    p95_ms: float
    baseline_p95_ms: float
    mean_ms: float = 0.0
    baseline_mean_ms: float = 0.0
    # Regra D. -1 / 0 = sem dado de buckets (amostras antigas): D nunca dispara.
    slow_n: int = -1          # requisições da v2 acima de L
    base_n: int = 0           # requisições da v1 na mesma janela
    base_slow_n: int = -1     # requisições da v1 acima de L


def is_insufficient(w: Window, rule: str = RULE_A) -> bool:
    # Na regra D a v1 é parte da estatística: base fraca não é evidência de saúde.
    if rule == RULE_D and (w.base_n < MIN_SAMPLE or w.base_slow_n < 0):
        return True
    return w.n < MIN_SAMPLE


def _ratio(ratio: Optional[float]) -> float:
    # None = valor do módulo lido na chamada (noise_sim ainda sobrescreve o global)
    return RELATIVE_RATIO_LIMIT if ratio is None else ratio


def _relative_slow(value: float, baseline: float, ratio: Optional[float] = None) -> bool:
    return (
        value > _ratio(ratio) * baseline
        and value > baseline + RELATIVE_DELTA_MS
        and value > P95_ABS_LIMIT_MS
    )


def _feature_slow(value: float, baseline: float, feature: Optional[str],
                  ratio: Optional[float] = None) -> bool:
    floor, delta = PER_FEATURE_LATENCY.get(feature, DEFAULT_FEATURE_LATENCY)
    return value > _ratio(ratio) * baseline and value > baseline + delta and value > floor


def _slow_fraction_up(w: Window) -> bool:
    """Teste unicaudal de duas proporções (variância combinada) + diferença mínima."""
    if w.slow_n < 0 or w.base_slow_n < 0 or w.base_n < MIN_SAMPLE or w.n <= 0:
        return False
    p2 = w.slow_n / w.n
    p1 = w.base_slow_n / w.base_n
    diff = p2 - p1
    if diff + _EPS < SLOW_FRAC_DELTA:
        return False
    pooled = (w.slow_n + w.base_slow_n) / (w.n + w.base_n)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / w.n + 1.0 / w.base_n))
    if se == 0.0:  # só com pooled 0 ou 1, que implica diff 0: já descartado acima
        return False
    return diff / se >= SLOW_FRAC_Z


def is_degraded(w: Window, rule: str = RULE_A, feature: Optional[str] = None,
                ratio: Optional[float] = None) -> bool:
    if w.err_pct > ERROR_RATE_LIMIT_PCT:
        return True
    if rule == RULE_A:
        return w.p95_ms > P95_RATIO_LIMIT * w.baseline_p95_ms and w.p95_ms > P95_ABS_LIMIT_MS
    if rule == RULE_B:
        return _relative_slow(w.p95_ms, w.baseline_p95_ms, ratio)
    if rule == RULE_C:
        return w.baseline_mean_ms > 0 and _relative_slow(w.mean_ms, w.baseline_mean_ms, ratio)
    if rule == RULE_BF:
        return _feature_slow(w.p95_ms, w.baseline_p95_ms, feature, ratio)
    if rule == RULE_D:
        return _slow_fraction_up(w)
    raise ValueError(f"regra desconhecida: {rule}")


@dataclass
class SubsetDetector:
    """Acompanha um par (cluster, feature) janela a janela.

    Janelas com amostra insuficiente não alteram os contadores. Na regra D isso inclui
    a v1 com base_n < MIN_SAMPLE ou sem buckets (base_slow_n < 0).
    """

    cluster: str
    feature: str
    state: str = "healthy"
    degraded_streak: int = 0
    recovered_streak: int = 0
    rule: str = RULE_A
    ratio: Optional[float] = None  # razão relativa de B/C/BF; None = RELATIVE_RATIO_LIMIT

    def observe(self, w: Window) -> Optional[str]:
        if is_insufficient(w, self.rule):
            return None

        if is_degraded(w, self.rule, self.feature, self.ratio):
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


def both_clusters_degraded(a: SubsetDetector, b: SubsetDetector) -> bool:
    """Guardrail da seção 5: degradação simultânea sugere falha de infra."""
    return a.state == "degraded" and b.state == "degraded"
