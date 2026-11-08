"""Coleta de janelas de 60 s a partir do Prometheus (seções 3 e 3.1 da spec revisada).

Agrupa por (versão, feature). O label `feature` vem do header X-Feature-Context
(Telemetry API) e é normalizado para um allow-list no scrape do Prometheus.
"""

import json
import os
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

from detector import Window

SERVICE = "app-service"
NAMESPACE = "lab-apps"
VERSION_LABEL = "destination_canonical_revision"
GROUP = f"{VERSION_LABEL}, feature"

Key = Tuple[str, str]  # (version, feature)


def _selector() -> str:
    # reporter="source": medido no cliente, inclui 504 gerado pelo sidecar do
    # chamador (timeout/retry) que nunca chega ao destino. Com "destination"
    # esses erros ficam invisíveis.
    # job="probe-generator": só os sidecars que carregam o label `feature`.
    # TRIAGE_PROM_*: o laboratório do Flagger (namespace flagger-lab) usa outro job, outro
    # namespace e serviços app-fl*, com a mesma conta; sem as variáveis nada muda.
    job = os.environ.get("TRIAGE_PROM_JOB", "probe-generator")
    ns = os.environ.get("TRIAGE_PROM_NAMESPACE", NAMESPACE)
    svc_re = os.environ.get("TRIAGE_PROM_SERVICE")
    svc = f'destination_service_name=~"{svc_re}"' if svc_re else f'destination_service_name="{SERVICE}"'
    return f'job="{job}",destination_service_namespace="{ns}",{svc},reporter="source"'


def requests_query() -> str:
    return f"sum by ({GROUP}) (increase(istio_requests_total{{{_selector()}}}[1m]))"


def errors_query() -> str:
    return (
        f"sum by ({GROUP}) (increase(istio_requests_total"
        f'{{{_selector()},response_code=~"5.."}}[1m]))'
    )


def p95_query() -> str:
    return (
        f"histogram_quantile(0.95, sum by ({GROUP}, le) ("
        f"rate(istio_request_duration_milliseconds_bucket{{{_selector()}}}[1m])))"
    )


def p95_by_version_query() -> str:
    # sem o label `feature`: é o p95 que um alarme só por versão enxergaria
    return (
        f"histogram_quantile(0.95, sum by ({VERSION_LABEL}, le) ("
        f"rate(istio_request_duration_milliseconds_bucket{{{_selector()}}}[1m])))"
    )


def mean_query() -> str:
    # média exata (sum/count), sem interpolação de bucket
    return (
        f"sum by ({GROUP}) (increase(istio_request_duration_milliseconds_sum{{{_selector()}}}[1m])) / "
        f"sum by ({GROUP}) (increase(istio_request_duration_milliseconds_count{{{_selector()}}}[1m]))"
    )


def mean_by_version_query() -> str:
    return (
        f"sum by ({VERSION_LABEL}) (increase(istio_request_duration_milliseconds_sum{{{_selector()}}}[1m])) / "
        f"sum by ({VERSION_LABEL}) (increase(istio_request_duration_milliseconds_count{{{_selector()}}}[1m]))"
    )


def parse_by_version(payload: dict) -> Dict[str, float]:
    if payload.get("status") != "success":
        raise ValueError(f"prometheus error: {payload.get('error', payload)}")
    out: Dict[str, float] = {}
    for item in payload["data"]["result"]:
        out[item["metric"].get(VERSION_LABEL, "")] = float(item["value"][1])
    return out


def parse_groups(payload: dict) -> Dict[Key, float]:
    if payload.get("status") != "success":
        raise ValueError(f"prometheus error: {payload.get('error', payload)}")
    out: Dict[Key, float] = {}
    for item in payload["data"]["result"]:
        m = item["metric"]
        out[(m.get(VERSION_LABEL, ""), m.get("feature", ""))] = float(item["value"][1])
    return out


def build_url(base_url: str, promql: str, at: Optional[float] = None) -> str:
    """URL da consulta instantânea. `at` (epoch, s) avalia a consulta naquele instante."""
    params = {"query": promql}
    if at is not None:
        params["time"] = str(at)
    return f"{base_url.rstrip('/')}/api/v1/query?" + urllib.parse.urlencode(params)


def bucket_query() -> str:
    # contagem acumulada por borda (le) na janela: base da regra D (fração lenta)
    return (
        f"sum by ({GROUP}, le) ("
        f"increase(istio_request_duration_milliseconds_bucket{{{_selector()}}}[1m]))"
    )


def parse_buckets(payload: dict) -> Dict[Key, Dict[str, float]]:
    if payload.get("status") != "success":
        raise ValueError(f"prometheus error: {payload.get('error', payload)}")
    out: Dict[Key, Dict[str, float]] = {}
    for item in payload["data"]["result"]:
        m = item["metric"]
        key = (m.get(VERSION_LABEL, ""), m.get("feature", ""))
        out.setdefault(key, {})[m["le"]] = float(item["value"][1])
    return out


def slow_count(buckets: Dict[str, float], limit_ms: float) -> Tuple[int, int]:
    """(total, acima de limit_ms) a partir das contagens acumuladas por borda.

    `limit_ms` precisa ser uma borda existente: entre bordas não há contagem exata e
    interpolar esconderia o erro. Levanta KeyError se a borda ou "+Inf" não existir.
    """
    edge = next((k for k in buckets if k != "+Inf" and float(k) == float(limit_ms)), None)
    if edge is None:
        raise KeyError(f"borda {limit_ms} ms não existe nos buckets: {sorted(buckets, key=_edge_key)}")
    total = buckets["+Inf"]
    return int(round(total)), max(0, int(round(total - buckets[edge])))


def _edge_key(k: str) -> float:
    return float("inf") if k == "+Inf" else float(k)


class PromClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, promql: str, at: Optional[float] = None) -> dict:
        with urllib.request.urlopen(build_url(self.base_url, promql, at), timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())

    def _q(self, promql: str, at: Optional[float]) -> dict:
        # só repassa `at` quando existe: subclasses com query(self, promql) seguem válidas
        return self.query(promql) if at is None else self.query(promql, at)

    def buckets(self, at: Optional[float] = None) -> Dict[Key, Dict[str, float]]:
        return parse_buckets(self._q(bucket_query(), at))

    def p95_by_version(self, at: Optional[float] = None) -> Dict[str, float]:
        return parse_by_version(self._q(p95_by_version_query(), at))

    def means(self, at: Optional[float] = None) -> Dict[Key, float]:
        """Média (ms) por (versão, feature). NaN (sem contagem) vira 0.0."""
        return {k: (v if v == v else 0.0) for k, v in parse_groups(self._q(mean_query(), at)).items()}

    def mean_by_version(self, at: Optional[float] = None) -> Dict[str, float]:
        return {k: (v if v == v else 0.0) for k, v in parse_by_version(self._q(mean_by_version_query(), at)).items()}

    def windows(self, at: Optional[float] = None) -> Dict[Key, Window]:
        """Uma janela de 60 s por (versão, feature) que teve tráfego.

        `mean_ms` vem da média exata `sum/count` (sem interpolação de bucket) e
        alimenta a regra C do detector.
        """
        reqs = parse_groups(self._q(requests_query(), at))
        errs = parse_groups(self._q(errors_query(), at))
        p95s = parse_groups(self._q(p95_query(), at))
        means = parse_groups(self._q(mean_query(), at))
        out: Dict[Key, Window] = {}
        for key, n in reqs.items():
            if n <= 0:
                continue
            p95 = p95s.get(key, 0.0)
            if p95 != p95:  # NaN: sem buckets na janela
                p95 = 0.0
            mean = means.get(key, 0.0)
            if mean != mean:  # NaN: sem contagem na janela
                mean = 0.0
            out[key] = Window(
                n=int(round(n)),
                err_pct=100.0 * errs.get(key, 0.0) / n,
                p95_ms=p95,
                baseline_p95_ms=0.0,
                mean_ms=mean,
            )
        return out
