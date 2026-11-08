"""Análise por versão no estilo das ferramentas de mercado e detecção por execução (v5).

Flagger, Argo Rollouts e Kayenta analisam o canário por versão, com métricas agregadas
sobre todo o tráfego. Aqui elas são emuladas offline nos MESMOS dados da avaliação: os
buckets de cada feature são somados por versão (soma de increase, exata) e o p99 sai
do histograma somado, como faria uma consulta sem o rótulo `feature`.

Métodos (`detect`):
- feature:<regra>  o detector por feature (replay, regra B, BF ou D), na feature injetada;
- agg_b            regra B sobre o p99 agregado por versão (v2 contra v1 na mesma janela),
                   3 janelas seguidas: a nossa regra sem o rótulo de feature;
- flagger_rel      estilo Flagger com MetricTemplate relativo: a cada intervalo de 1 min
                   a checagem falha se a taxa de sucesso da v2 < 99% ou se
                   p99(v2)/p99(v1) > 1,15; reverte quando as falhas ACUMULADAS chegam a
                   5 (`threshold: 5`). Não é o Flagger de verdade (rodada seguinte).

Execução detectada: primeira detecção com rótulo em (t_on, t_off + 60]. A janela extra
cobre requisições que leram a falha antes de t_off e terminaram depois. Detecção com
rótulo <= t_on é alarme falso antes da falha, não acerto.
"""
from math import comb
from typing import Dict, List, Optional

from detector import RULE_B, SubsetDetector, Window
from replay import _epoch, replay

FLAGGER_THRESHOLD = 5
FLAGGER_MIN_SUCCESS_PCT = 99.0
FLAGGER_MAX_RATIO = 1.15
AGG_QUANTILE = 0.99


def _edge(k: str) -> float:
    return float("inf") if k == "+Inf" else float(k)


def histogram_quantile(q: float, buckets: Dict[str, float]) -> float:
    """Como o Prometheus: interpolação linear no bucket; no +Inf devolve a maior borda finita."""
    edges = sorted(buckets, key=_edge)
    total = buckets["+Inf"]
    if total <= 0:
        return 0.0
    rank, lo, clo = q * total, 0.0, 0.0
    for k in edges:
        c = buckets[k]
        if c >= rank:
            if k == "+Inf":
                return lo
            hi = _edge(k)
            return lo + (hi - lo) * ((rank - clo) / (c - clo) if c > clo else 1.0)
        lo, clo = _edge(k), c
    return lo


def aggregate(sample: dict, version: str) -> Optional[dict]:
    ws = [w for w in sample["windows"] if w["version"] == version]
    if not ws or any("buckets" not in w for w in ws):
        return None
    n = sum(w["n"] for w in ws)
    buckets: Dict[str, float] = {}
    for w in ws:
        for k, v in w["buckets"].items():
            buckets[k] = buckets.get(k, 0.0) + v
    return {"n": n, "err_pct": sum(w["err_pct"] * w["n"] for w in ws) / n if n else 0.0, "buckets": buckets}


def _agg_windows(samples: List[dict]) -> List[Optional[Window]]:
    out = []
    for s in samples:
        a1, a2 = aggregate(s, "v1"), aggregate(s, "v2")
        if a1 is None or a2 is None:
            out.append(None)
            continue
        # p95_ms carrega o p99 agregado: a regra B é aplicada a ele sem mudança
        out.append(Window(n=int(a2["n"]), err_pct=a2["err_pct"],
                          p95_ms=histogram_quantile(AGG_QUANTILE, a2["buckets"]),
                          baseline_p95_ms=histogram_quantile(AGG_QUANTILE, a1["buckets"])))
    return out


def _first_agg_b(samples) -> Optional[int]:
    det = SubsetDetector("x", "*", rule=RULE_B)
    for i, w in enumerate(_agg_windows(samples)):
        if w is not None and det.observe(w) == "detected":
            return i
    return None


def _first_flagger(samples) -> Optional[int]:
    failed = 0
    for i, w in enumerate(_agg_windows(samples)):
        if w is None:
            continue
        bad = (100.0 - w.err_pct < FLAGGER_MIN_SUCCESS_PCT
               or (w.baseline_p95_ms > 0 and w.p95_ms / w.baseline_p95_ms > FLAGGER_MAX_RATIO))
        failed += bad
        if failed >= FLAGGER_THRESHOLD:
            return i
    return None


def _first_feature(samples, rule, feature, limits) -> Optional[int]:
    res = replay(samples, "x", rule=rule, skip=0, limits=limits)
    return next((i for i, f, k in res.events if f == feature and k == "detected"), None)


def detect(samples: List[dict], t_on: float, t_off: float, method: str, feature: Optional[str] = None,
           limits: Optional[Dict[str, float]] = None) -> dict:
    if method == "agg_b":
        idx = _first_agg_b(samples)
    elif method == "flagger_rel":
        idx = _first_flagger(samples)
    elif method.startswith("feature:"):
        idx = _first_feature(samples, method.split(":", 1)[1], feature, limits)
    else:
        raise ValueError(f"método desconhecido: {method}")
    label = _epoch(samples[idx]["ts"]) if idx is not None else None
    hit = label is not None and t_on < label <= t_off + 60
    return {"method": method, "detected": hit, "first_label": label,
            "false_alarm_before": label is not None and label <= t_on,
            "ttd_windows": round((label - t_on) / 60) if hit else None}


def mcnemar_one_sided(b: int, c: int) -> float:
    """P(X >= b), X ~ Bin(b + c, 1/2): b = só a análise por feature detectou, c = só a agregada."""
    n = b + c
    if n == 0:
        return 1.0
    return sum(comb(n, i) for i in range(b, n + 1)) / 2 ** n


