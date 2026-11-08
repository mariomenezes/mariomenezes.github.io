"""Análise da avaliação v5 (PRE-REGISTRO.md v5), escrita antes dos dados de cluster.

Lê OUT/<cluster>/runs.jsonl e os arquivos de cada execução válida do runner e calcula:
- H1: por cenário, execuções detectadas pela regra primária da feature injetada
  (B em heavy-reports, D em dashboard), limite inferior unicaudal de 95% >= 0,80;
- H2: detecção pela regra primária numa feature NÃO injetada, dentro de (t_on, t_off+60];
- H3: alarmes da regra primária no controle, UB95 de Poisson < 0,1 por cluster-hora;
- H5: McNemar exato unicaudal pareado (primária x agg_b, primária x flagger_rel) por
  cenário, Holm sobre todos os testes;
- secundárias: B, BF e D em todas as features; falso alarme das análises por versão
  no controle em blocos de 14 janelas.
Acerto numa execução: `market_emul.detect` (primeira detecção em (t_on, t_off + 60]).

Uso: python3 eval_v5.py results/eval-v5 plans/EVAL-V5-sigma0.1.json [--out DIR]
"""
import argparse
import json
import os
from typing import Dict

import market_emul as me
from calib_lib import clopper_pearson, poisson_upper, quantile
from replay import load_samples, replay
from runner import load_plan

PRIMARY = {"heavy-reports": "B", "dashboard": "D"}
PRIMARY_SCENARIOS = ("heavy10", "dash10")
LIMITS = {"heavy-reports": 3750.0, "dashboard": 250.0}
H1_LB = 0.80
H3_UB = 0.1
ALPHA = 0.05
BLOCK = 14


def h1_pass(hits: int, n: int) -> bool:
    return n > 0 and clopper_pearson(hits, n, two_sided=False)[0] >= H1_LB


def h3_pass(alarms: int, windows: int) -> bool:
    return windows > 0 and poisson_upper(alarms, windows / 60.0) < H3_UB


def holm(ps: Dict[str, float]) -> Dict[str, float]:
    items = sorted(ps.items(), key=lambda kv: kv[1])
    m, out, prev = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        prev = max(prev, min(1.0, (m - i) * p))
        out[k] = prev
    return out


def apply_holm(h5: Dict[str, dict]) -> None:
    """Rejeita H0 pelo p ajustado por Holm sobre todos os testes da H5, nunca pelo bruto."""
    for k, p in holm({k: v["p"] for k, v in h5.items()}).items():
        h5[k]["p_holm"] = p
        h5[k]["reject"] = p < ALPHA


def _rate(hits, n, ttd):
    lo = clopper_pearson(hits, n, two_sided=False)[0] if n else 0.0
    return {"hits": hits, "n": n, "rate": hits / n if n else None, "lo1": lo,
            "ttd_med": quantile(ttd, 0.5) if ttd else None, "ttd_p90": quantile(ttd, 0.9) if ttd else None}


def analyze(out_dir: str, plan_path: str) -> dict:
    plan = load_plan(plan_path)
    feat_of = {s.id: s.feature for s in plan.scenarios if s.kind == "fault"}
    methods = [f"feature:{r}" for r in ("B", "BF", "D")] + ["agg_b", "flagger_rel"]
    per = {sid: {m: [] for m in methods} for sid in feat_of}  # (cluster, rep, acerto, ttd)
    violations, ctrl_windows, ctrl_alarms = [], 0, {f: 0 for f in PRIMARY}
    agg_fa = {"agg_b": [0, 0], "flagger_rel": [0, 0]}  # [blocos com alarme, blocos]
    for c in sorted(plan.clusters):
        cdir = os.path.join(out_dir, c)
        if not os.path.exists(os.path.join(cdir, "runs.jsonl")):
            continue
        for r in map(json.loads, filter(str.strip, open(os.path.join(cdir, "runs.jsonl"), encoding="utf-8"))):
            if r.get("status") != "ok":
                continue
            samples = load_samples(os.path.join(cdir, r["file"])).samples
            if r["kind"] == "control":
                ctrl_windows += len(samples)
                for f, rule in PRIMARY.items():
                    ev = replay(samples, c, rule=rule, skip=0, limits=LIMITS).events
                    ctrl_alarms[f] += sum(1 for _, ff, k in ev if ff == f and k == "detected")
                for i in range(0, len(samples) - BLOCK + 1, BLOCK):
                    blk = samples[i:i + BLOCK]
                    for m in agg_fa:
                        agg_fa[m][1] += 1
                        agg_fa[m][0] += me.detect(blk, 0, 0, m)["first_label"] is not None
                continue
            sid, feat = r["scenario"], feat_of[r["scenario"]]
            for m in methods:
                d = me.detect(samples, r["t_on"], r["t_off"], m, feature=feat, limits=LIMITS)
                per[sid][m].append((c, r["rep"], d["detected"], d["ttd_windows"]))
            for other, rule in PRIMARY.items():
                if other != feat:
                    d = me.detect(samples, r["t_on"], r["t_off"], f"feature:{rule}", feature=other, limits=LIMITS)
                    if d["detected"] or d["false_alarm_before"]:
                        violations.append({"cluster": c, "scenario": sid, "rep": r["rep"], "feature": other})
    scen, h5 = {}, {}
    for sid, ms in per.items():
        feat = feat_of[sid]
        prim = f"feature:{PRIMARY[feat]}"
        res = {m: _rate(sum(x[2] for x in v), len(v), [x[3] for x in v if x[2]]) for m, v in ms.items()}
        scen[sid] = {"feature": feat, "primary_rule": PRIMARY[feat], "primary": res[prim], "methods": res,
                     "h1_primary_scenario": sid in PRIMARY_SCENARIOS,
                     "h1_pass": h1_pass(res[prim]["hits"], res[prim]["n"])}
        pk = {(x[0], x[1]): x[2] for x in ms[prim]}
        for m in ("agg_b", "flagger_rel"):
            mk = {(x[0], x[1]): x[2] for x in ms[m]}
            b = sum(1 for k in pk if pk[k] and not mk.get(k, False))
            cc = sum(1 for k in pk if not pk[k] and mk.get(k, False))
            p = me.mcnemar_one_sided(b, cc)
            h5[f"{sid}/{m}"] = {"b": b, "c": cc, "p": p}
    apply_holm(h5)
    hrs = ctrl_windows / 60.0
    control = {"windows": ctrl_windows, "hours": hrs, "alarms": ctrl_alarms,
               "ub95": {f: poisson_upper(k, hrs) if hrs else None for f, k in ctrl_alarms.items()},
               "h3_pass": {f: h3_pass(k, ctrl_windows) for f, k in ctrl_alarms.items()},
               "agg_blocks": {m: {"with_alarm": v[0], "blocks": v[1]} for m, v in agg_fa.items()}}
    return {"plan": plan.name, "plan_sha256": plan.sha256, "scenarios": scen, "control": control,
            "isolation": {"violations": violations, "h2_pass": not violations}, "h5": h5}


def _pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def render(r: dict) -> str:
    L = [f"# Avaliação v5: {r['plan']}\n", f"Plano `{r['plan_sha256'][:12]}`. Acerto: primeira detecção em (t_on, t_off+60].\n",
         "## H1 (regra primária, limite inferior unicaudal 95% >= 0,80)\n",
         "| Cenário | Regra | Detectadas | LI95 | TTD med/p90 | H1 |", "|---|---|---|---|---|---|"]
    for sid, s in r["scenarios"].items():
        p = s["primary"]
        tag = ("passa" if s["h1_pass"] else "falha") if s["h1_primary_scenario"] else "secundário"
        L.append(f"| {sid} | {s['primary_rule']} | {p['hits']}/{p['n']} | {p['lo1']:.3f} | {p['ttd_med']}/{p['ttd_p90']} | {tag} |")
    L += ["\n## H5 (por feature x por versão, McNemar unicaudal, Holm)\n",
          "| Cenário/método | só feature | só versão | p | p Holm | rejeita H0 |", "|---|---|---|---|---|---|"]
    for k, h in r["h5"].items():
        L.append(f"| {k} | {h['b']} | {h['c']} | {h['p']:.4f} | {h['p_holm']:.4f} | {'sim' if h['reject'] else 'não'} |")
    L += ["\n## Todas as análises (secundárias)\n", "| Cenário | " + " | ".join(next(iter(r["scenarios"].values()))["methods"]) + " |",
          "|---|" + "---|" * len(next(iter(r["scenarios"].values()))["methods"])]
    for sid, s in r["scenarios"].items():
        L.append(f"| {sid} | " + " | ".join(f"{v['hits']}/{v['n']} ({_pct(v['rate'])})" for v in s["methods"].values()) + " |")
    c = r["control"]
    L += [f"\n## H3 (controle: {c['windows']} janelas, {c['hours']:.1f} cluster-horas)\n"]
    for f, k in c["alarms"].items():
        ub = c["ub95"][f]
        L.append(f"- {f}: {k} alarmes, UB95 {ub if ub is None else round(ub, 4)} por cluster-hora: "
                 f"{'passa' if c['h3_pass'][f] else 'falha'}")
    for m, v in c["agg_blocks"].items():
        L.append(f"- {m} (por versão): alarme em {v['with_alarm']} de {v['blocks']} blocos de {BLOCK} janelas")
    iso = r["isolation"]
    L += [f"\n## H2 (isolamento): {'passa' if iso['h2_pass'] else 'falha'}; violações: {len(iso['violations'])}"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("plan")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    r = analyze(a.out_dir, a.plan)
    out = a.out or a.out_dir
    with open(os.path.join(out, "ANALISE-v5.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, sort_keys=True, ensure_ascii=False)
    md = render(r)
    with open(os.path.join(out, "ANALISE-v5.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
