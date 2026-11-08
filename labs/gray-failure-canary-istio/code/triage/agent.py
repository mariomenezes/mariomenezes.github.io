"""Loop de decisão em modo shadow (seções 3.1, 5, 6 e 8 da spec revisada).

Um detector por (cluster, feature). O baseline de cada feature é a v1 da mesma
feature, para que o p95 de heavy-reports não seja comparado com o de dashboard.

Regra de latência padrão: B (p95 > 1.15x baseline e > baseline + 500 ms),
escolhida no teste de falha parcial (spec 10.1, item 9) e com a razão
ajustada no teste com latência variável (item 12). A não detecta falha parcial. A regra C (a mesma
sobre a média) é observada em um detector paralelo e registrada nos eventos
(`c_detected`/`c_recovered`), sem disparar ação sozinha.

Nesta etapa o agente só detecta, aplica os guardrails de decisão e registra o
que faria. Nenhuma mudança é aplicada no cluster. O modo `auto` não existe
ainda; precisa passar pelos critérios da seção 6.1 antes.
"""

import json
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from detector import RULE_B, RULE_C, SubsetDetector, Window

Snapshot = Dict[Tuple[str, str], Window]  # (version, feature) -> Window
Source = Callable[[str], Snapshot]  # cluster -> snapshot

BASELINE = "v1"
CANDIDATE = "v2"

# Padrão do teste de falha parcial (spec 10.1, item 9): B decide, C só registra.
DEFAULT_RULE = RULE_B
WATCH_RULE = RULE_C


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ShadowAgent:
    def __init__(self, clusters: List[str], features: List[str], source: Source,
                 events_path: str, mode: str = "shadow",
                 rule: str = DEFAULT_RULE, watch_rule: str = WATCH_RULE,
                 ratio: Optional[float] = None):
        if mode not in ("off", "shadow"):
            raise ValueError(f"mode {mode!r} não suportado nesta etapa")
        self.clusters = clusters
        self.features = features
        self.source = source
        self.events_path = events_path
        self.mode = mode
        self.detectors = {
            (c, f): SubsetDetector(c, f, rule=rule, ratio=ratio)
            for c in clusters for f in features
        }
        # Detector paralelo com a regra C: registrado ao lado, sem disparar ação.
        self.watch = {
            (c, f): SubsetDetector(c, f, rule=watch_rule, ratio=ratio)
            for c in clusters for f in features
        }

    def emit(self, event: str, cluster: str, feature: str,
             window: Optional[Window], reason=None) -> dict:
        record = {
            "ts": _now(),
            "mode": self.mode,
            "cluster": cluster,
            "event": event,
            "feature": feature,
            "window_stats": None if window is None else {
                "n": window.n,
                "err_pct": round(window.err_pct, 2),
                "p95_ms": round(window.p95_ms, 1),
                "baseline_p95_ms": round(window.baseline_p95_ms, 1),
                "mean_ms": round(window.mean_ms, 1),
                "baseline_mean_ms": round(window.baseline_mean_ms, 1),
            },
            "reason": reason,
        }
        os.makedirs(os.path.dirname(self.events_path) or ".", exist_ok=True)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record

    def reset_streaks(self, cluster: Optional[str] = None) -> None:
        """Zera as contagens de janelas seguidas (degradação e recuperação), mantendo o estado.

        Usado quando há um buraco nos dados: janelas separadas por uma lacuna não são
        consecutivas. Não é chamado por `tick`; o comportamento do agente não muda.
        """
        if cluster is not None and cluster not in self.clusters:
            raise KeyError(cluster)
        for group in (self.detectors, self.watch):
            for (c, _), det in group.items():
                if cluster is None or c == cluster:
                    det.degraded_streak = 0
                    det.recovered_streak = 0

    def tick(self) -> List[dict]:
        """Uma janela de 60 s para todos os clusters e features."""
        if self.mode == "off":
            return []

        snapshots = {}
        for cluster in self.clusters:
            try:
                snapshots[cluster] = self.source(cluster)
            except Exception as exc:  # guardrail: sem métrica, sem ação
                snapshots[cluster] = None
                self.emit("source_error", cluster, "*", None, reason=str(exc)[:200])

        transitions = {}
        for cluster in self.clusters:
            snap = snapshots[cluster]
            if snap is None:
                continue
            for feature in self.features:
                base = snap.get((BASELINE, feature))
                cand = snap.get((CANDIDATE, feature))
                if base is None or cand is None:
                    continue
                w = replace(cand,
                           baseline_p95_ms=base.p95_ms,
                           baseline_mean_ms=base.mean_ms,
                           base_n=base.n,
                           base_slow_n=base.slow_n)
                transitions[(cluster, feature)] = (
                    self.detectors[(cluster, feature)].observe(w),
                    # C avalia só o canal de latência pela média: a regra de
                    # erro já está no caminho de decisão e o sinal c_* não
                    # deve duplicá-la.
                    self.watch[(cluster, feature)].observe(replace(w, err_pct=0.0)),
                    w)

        events = []
        for (cluster, feature), (transition, watch_transition, w) in transitions.items():
            if transition == "detected":
                all_degraded = len(self.clusters) > 1 and all(
                    self.detectors[(c, feature)].state == "degraded"
                    for c in self.clusters
                )
                if all_degraded:
                    events.append(self.emit("blocked", cluster, feature, w,
                                            reason="guardrail:both_clusters_degraded"))
                else:
                    events.append(self.emit("would_apply", cluster, feature, w))
            elif transition == "recovered":
                events.append(self.emit("recovered", cluster, feature, w))
            if watch_transition == "detected":
                events.append(self.emit("c_detected", cluster, feature, w,
                                        reason="regra C (média), registro apenas"))
            elif watch_transition == "recovered":
                events.append(self.emit("c_recovered", cluster, feature, w,
                                        reason="regra C (média), registro apenas"))
        return events

    def run(self, interval_s: int = 60, max_ticks: Optional[int] = None):
        n = 0
        while max_ticks is None or n < max_ticks:
            self.tick()
            n += 1
            if max_ticks is None or n < max_ticks:
                time.sleep(interval_s)


def _main():
    from prom import PromClient

    clients = {
        "a": PromClient(os.getenv("PROM_A_URL", "http://localhost:9090")),
        "b": PromClient(os.getenv("PROM_B_URL", "http://localhost:9091")),
    }
    agent = ShadowAgent(
        clusters=["a", "b"],
        features=os.getenv("FEATURES", "dashboard,heavy-reports").split(","),
        source=lambda cluster: clients[cluster].windows(),
        events_path=os.getenv("EVENTS_PATH", "/tmp/triage/events.jsonl"),
        mode=os.getenv("AGENT_MODE", "shadow"),
    )
    agent.run(interval_s=int(os.getenv("INTERVAL_S", "60")))


if __name__ == "__main__":
    _main()
