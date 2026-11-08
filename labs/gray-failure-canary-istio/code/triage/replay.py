"""Analisador único: passa amostras coletadas pelo ShadowAgent, como o agente decide.

Semântica do agente: v2 contra a v1 da MESMA feature na MESMA janela, 3 janelas
consecutivas, n >= 30. Substitui as análises avulsas (mix_test, analyze_noise) para
tudo que for novo; elas ficam como referência histórica.

Formato de entrada (JSONL, uma linha por janela de 60 s):
  {"ts": "...Z", "windows": [{"version","feature","n","err_pct","p95_ms","mean_ms",
                              "buckets": {"<le>": contagem acumulada, ..., "+Inf": n}}],
   "p95_by_version": {...}, "mean_by_version": {...}}
  {"ts": "...Z", "error": "..."}      tentativa de coleta que falhou
  {"meta": {...}}                      metadados da coleta (opcional)
`buckets` só existe nas coletas novas; sem ele a regra D não dispara. Na regra D, n (v2)
e base_n (v1) são o total "+Inf" do histograma, a mesma métrica de slow_n.

Tratamento de tempo (definido aqui, para ser congelado no pré-registro):
- DUP_S: linhas a menos de 55 s da última mantida são duplicatas (rajada após suspensão
  do host) e são descartadas; fica a primeira. Duas janelas increase[1m] a Δ s uma da
  outra compartilham 60-Δ s de dados: 55 s limita a sobreposição a 5 s (8 %) e tolera
  jitter do coletor antigo. Com 30 s, janelas com até metade dos dados em comum
  contavam como consecutivas. Nas coletas existentes não há espaçamento em [30, 55) s:
  a mudança não altera nenhum RESUMO (test_replay_regression). Compara-se tempo, não
  rótulo de minuto, porque coletores com deriva (~60,3 s por passo) fazem o rótulo do
  minuto pular sem que falte nenhuma janela.
- GAP_S: mais de 90 s entre duas amostras mantidas é um buraco; as contagens de janelas
  seguidas são zeradas (`ShadowAgent.reset_streaks`), mantendo o estado.
- Feature sem tráfego numa janela, ou janela com n < 30, segue a semântica do detector
  (não avança nem zera). Só buraco de dados zera.

Uso:
  python3 replay.py ARQ.jsonl --cluster a --rules A,B,C,BF,D --limits heavy-reports=3750,dashboard=250
  (a regra D exige borda para todas as features; faltando alguma, ValueError)
"""
import argparse
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import detector
from agent import ShadowAgent
from detector import Window
from prom import slow_count

DUP_S = 55.0
GAP_S = 90.0
FEATURES = ("dashboard", "heavy-reports")
_KIND = {"would_apply": "detected", "blocked": "blocked", "recovered": "recovered"}
_WATCH = ("c_detected", "c_recovered")

Event = Tuple[int, str, str]  # (índice após o skip, feature, tipo)


def _epoch(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


@dataclass
class Loaded:
    samples: List[dict]
    meta: Optional[dict] = None
    errors: int = 0
    duplicates: int = 0
    lines: int = 0


def load_samples(path: str) -> Loaded:
    """Lê o JSONL, ordena por tempo e descarta duplicatas em rajada (ficando a primeira)."""
    meta, errors, rows, lines = None, 0, [], 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            lines += 1
            row = json.loads(raw)
            if "meta" in row:
                meta = row["meta"]
            elif "error" in row:
                errors += 1
            elif "windows" in row:
                rows.append(row)
    rows.sort(key=lambda r: _epoch(r["ts"]))  # estável: preenchimentos anexados no fim entram no lugar
    kept, dups, last = [], 0, None
    for row in rows:
        t = _epoch(row["ts"])
        if last is not None and t - last < DUP_S:
            dups += 1
            continue
        kept.append(row)
        last = t
    return Loaded(samples=kept, meta=meta, errors=errors, duplicates=dups, lines=lines)


@dataclass
class ReplayResult:
    cluster: str
    rule: str
    ratio: float
    n_samples: int = 0
    gaps: List[int] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)  # decisão da regra escolhida
    watch: List[Event] = field(default_factory=list)   # regra C, registro apenas
    no_bucket_windows: int = 0


def first_detected(res: ReplayResult, feature: str) -> Optional[int]:
    return next((i for i, f, k in res.events if f == feature and k == "detected"), None)


def count_kind(events: Sequence[Event], feature: str, kind: str) -> int:
    return sum(1 for _, f, k in events if f == feature and k == kind)


def _window(w: dict, limit: Optional[float], res: ReplayResult, rule: str) -> Window:
    n, slow = int(round(w["n"])), -1
    if limit is not None:
        if "buckets" in w:
            total, slow = slow_count(w["buckets"], limit)
            if rule == detector.RULE_D:
                # numerador e denominador da fração lenta vêm do mesmo histograma (+Inf),
                # não de istio_requests_total; base_n herda isso pelo agente (base.n)
                n = total
        else:
            res.no_bucket_windows += 1
    return Window(n=n, err_pct=w["err_pct"], p95_ms=w["p95_ms"],
                  baseline_p95_ms=0.0, mean_ms=w.get("mean_ms", 0.0), slow_n=slow)


def replay(samples: Sequence[dict], cluster: str, rule: str = detector.RULE_B,
           ratio: Optional[float] = None, skip: int = 1,
           limits: Optional[Dict[str, float]] = None,
           features: Sequence[str] = FEATURES) -> ReplayResult:
    if rule not in detector.ALL_RULES:
        raise ValueError(f"regra desconhecida: {rule}")
    if rule == detector.RULE_D and not limits:
        raise ValueError("a regra D exige limits={feature: borda_ms}")
    if rule == detector.RULE_D:
        missing = [f for f in features if f not in limits]
        if missing:
            raise ValueError(f"regra D sem borda em --limits para: {', '.join(missing)}")
    seq = list(samples)[skip:]
    times = [_epoch(s["ts"]) for s in seq]
    for a, b in zip(times, times[1:]):
        if b - a < DUP_S:
            raise ValueError(f"amostras a {b - a:.0f} s uma da outra ou fora de ordem; use load_samples")

    cur: Dict[tuple, Window] = {}
    # razão passada aos detectores, sem mexer no global: replays em paralelo são seguros
    used = detector.RELATIVE_RATIO_LIMIT if ratio is None else ratio
    with tempfile.TemporaryDirectory() as tmp:
        res = ReplayResult(cluster=cluster, rule=rule, ratio=used)
        agent = ShadowAgent([cluster], list(features), lambda _c: cur,
                            os.path.join(tmp, "events.jsonl"), rule=rule, ratio=used)
        for idx, s in enumerate(seq):
            if idx > 0 and times[idx] - times[idx - 1] > GAP_S:
                agent.reset_streaks()
                res.gaps.append(idx)
            cur.clear()
            for w in s["windows"]:
                cur[(w["version"], w["feature"])] = _window(w, (limits or {}).get(w["feature"]), res, rule)
            for e in agent.tick():
                if e["event"] in _KIND:
                    res.events.append((idx, e["feature"], _KIND[e["event"]]))
                elif e["event"] in _WATCH:
                    res.watch.append((idx, e["feature"], e["event"]))
            res.n_samples += 1
    return res


def _parse_limits(text: Optional[str]) -> Optional[Dict[str, float]]:
    if not text:
        return None
    return {k: float(v) for k, v in (p.split("=", 1) for p in text.split(","))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--cluster", required=True)
    ap.add_argument("--rules", default="A,B,C,BF,D")
    ap.add_argument("--limits", help="feature=borda_ms,... (regra D)")
    ap.add_argument("--skip", type=int, default=1)
    ap.add_argument("--ratio", type=float, default=None)
    a = ap.parse_args()
    ld = load_samples(a.file)
    print(f"{a.file}: {ld.lines} linhas, {len(ld.samples)} janelas, {ld.duplicates} duplicatas, "
          f"{ld.errors} erros de coleta, meta={'sim' if ld.meta else 'não'}")
    limits = _parse_limits(a.limits)
    for rule in a.rules.split(","):
        if rule == detector.RULE_D and not limits:
            print(f"  regra D: pulada (sem --limits)")
            continue
        r = replay(ld.samples, a.cluster, rule, a.ratio, a.skip, limits)
        print(f"  regra {rule} (razão {r.ratio}): janelas {r.n_samples}, buracos {len(r.gaps)}")
        for f in FEATURES:
            print(f"    {f:14s} detecções={count_kind(r.events, f, 'detected')} "
                  f"primeira={first_detected(r, f)} recuperações={count_kind(r.events, f, 'recovered')}"
                  f" | C: {count_kind(r.watch, f, 'c_detected')}")
        if r.no_bucket_windows:
            print(f"    janelas sem buckets (D não avalia): {r.no_bucket_windows}")


if __name__ == "__main__":
    main()
