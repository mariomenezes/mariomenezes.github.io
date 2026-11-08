"""Análise da comparação com o Flagger real (PRE-REGISTRO.md v6), escrita antes dos dados.

Para cada execução válida do `flagger_runner`:
- Flagger real: acerto se reverteu (fase Failed) com horário em (t_on, t_off + 60];
  reverter até t_on é alarme falso antes da falha; no controle, qualquer reversão é falso alarme;
- nosso detector (regra primária da feature injetada, B em heavy-reports e D em dashboard),
  a regra B sobre o p99 agregado e a emulação `flagger_rel`, todos sobre o MESMO tráfego
  (coletado pelo job probe-flagger), com o critério de acerto de `market_emul.detect`.

Hipóteses: H6a (Flagger cego ao dashboard: UB95 < 0,20, ou seja, no máximo 2 reversões em 30),
H6b (Flagger vê heavy-reports: LI95 >= 0,80), H6c (controle sem reversão: UB95 < 0,10),
H7 (nosso detector contra o Flagger real, McNemar pareado com Holm), H8 (a emulação
concorda com o Flagger real em pelo menos 28 de 30 execuções por cenário, LI95 >= 0,80).

Uso: python3 eval_flagger.py results/flagger-v6 plans/FLAGGER-V6.json [--out DIR]
"""
import argparse
import json
import os
from typing import Optional

import market_emul as me
from calib_lib import clopper_pearson
from eval_v5 import LIMITS, PRIMARY, apply_holm
from replay import load_samples, replay
import flagger_runner as fr

H6A_UB = 0.20
H6B_LB = 0.80
H6C_UB = 0.10
H8_LB = 0.80
EMUL = ("agg_b", "flagger_rel")


def h6a_pass(hits: int, n: int) -> bool:
    return n > 0 and clopper_pearson(hits, n, two_sided=False)[1] < H6A_UB


def h6b_pass(hits: int, n: int) -> bool:
    return n > 0 and clopper_pearson(hits, n, two_sided=False)[0] >= H6B_LB


def h6c_pass(false_alarms: int, runs: int) -> bool:
    return runs > 0 and clopper_pearson(false_alarms, runs, two_sided=False)[1] < H6C_UB


def h8_pass(agree: int, n: int) -> bool:
    return n > 0 and clopper_pearson(agree, n, two_sided=False)[0] >= H8_LB


def flagger_hit(phase: str, failed_at: Optional[float], t_on: float, t_off: float) -> bool:
    return phase == "Failed" and failed_at is not None and t_on < failed_at <= t_off + 60


def _count(hits, n):
    lo, hi = clopper_pearson(hits, n, two_sided=False) if n else (0.0, 1.0)
    return {"hits": hits, "n": n, "rate": hits / n if n else None, "lo1": lo, "ub1": hi}


def analyze(out_dir: str, plan_path: str) -> dict:
    plan = fr.load_plan(plan_path)
    feat_of = {s.id: s.feature for s in plan.scenarios if s.kind == "fault"}
    per = {sid: [] for sid in feat_of}
    ctrl = {"flagger": [0, 0], "ours": [0, 0], **{f"emul_{m}": [0, 0] for m in EMUL}}
    for c in sorted(plan.clusters):
        p = os.path.join(out_dir, c, "runs.jsonl")
        if not os.path.exists(p):
            continue
        for r in map(json.loads, filter(str.strip, open(p, encoding="utf-8"))):
            if r.get("status") != "ok":
                continue
            samples = load_samples(os.path.join(out_dir, c, r["file"])).samples
            if r["kind"] == "control":
                ctrl["flagger"][1] += 1
                ctrl["flagger"][0] += r["flagger_phase"] == "Failed"
                alarm = any(k == "detected" for f, rule in PRIMARY.items()
                            for _, ff, k in replay(samples, c, rule=rule, skip=0, limits=LIMITS).events if ff == f)
                ctrl["ours"][1] += 1
                ctrl["ours"][0] += alarm
                for m in EMUL:
                    ctrl[f"emul_{m}"][1] += 1
                    ctrl[f"emul_{m}"][0] += me.detect(samples, 0, 0, m)["first_label"] is not None
                continue
            sid, feat = r["scenario"], feat_of[r["scenario"]]
            t_on, t_off = r["t_on"], r["t_off"]
            row = {"cluster": c, "rep": r["rep"],
                   "flagger": flagger_hit(r["flagger_phase"], r.get("flagger_failed_at"), t_on, t_off),
                   "ours": me.detect(samples, t_on, t_off, f"feature:{PRIMARY[feat]}", feature=feat,
                                     limits=LIMITS)["detected"]}
            for m in EMUL:
                row[f"emul_{m}"] = me.detect(samples, t_on, t_off, m)["detected"]
            per[sid].append(row)
    scen, h7 = {}, {}
    for sid, rows in per.items():
        n = len(rows)
        d = {"feature": feat_of[sid], "flagger": _count(sum(x["flagger"] for x in rows), n),
             "ours": _count(sum(x["ours"] for x in rows), n)}
        for m in EMUL:
            d[f"emul_{m}"] = _count(sum(x[f"emul_{m}"] for x in rows), n)
        d["agreement"] = {"agree": sum(x["flagger"] == x["emul_flagger_rel"] for x in rows), "n": n}
        scen[sid] = d
        b = sum(1 for x in rows if x["ours"] and not x["flagger"])
        cc = sum(1 for x in rows if x["flagger"] and not x["ours"])
        h7[sid] = {"b": b, "c": cc, "p": me.mcnemar_one_sided(b, cc)}
    apply_holm(h7)
    control = {k: {"false_alarms": v[0], "runs": v[1]} for k, v in ctrl.items()}
    return {"plan": plan.name, "plan_sha256": plan.sha256, "scenarios": scen, "control": control, "h7": h7}


def _line(c):
    return f"{c['hits']}/{c['n']}" + ("" if c["rate"] is None else f" ({100 * c['rate']:.0f}%)")


def render(r: dict) -> str:
    L = [f"# Comparação com o Flagger real: {r['plan']}\n", f"Plano `{r['plan_sha256'][:12]}`.\n",
         "## Detecção por cenário (mesmas execuções)\n",
         "| Cenário | Flagger real | Nosso detector | agg_b (emul.) | flagger_rel (emul.) | Real x emulado concordam |",
         "|---|---|---|---|---|---|"]
    for sid, s in r["scenarios"].items():
        a = s["agreement"]
        L.append(f"| {sid} | {_line(s['flagger'])} | {_line(s['ours'])} | {_line(s['emul_agg_b'])} | "
                 f"{_line(s['emul_flagger_rel'])} | {a['agree']}/{a['n']} |")
    s = r["scenarios"]
    L += ["\n## Hipóteses\n"]
    for sid, s_ in s.items():
        if s_["feature"] == "dashboard":
            L.append(f"- H6a ({sid}, Flagger cego ao dashboard): {s_['flagger']['hits']}/{s_['flagger']['n']} reversões, "
                     f"UB95 {s_['flagger']['ub1']:.3f}: {'passa' if h6a_pass(s_['flagger']['hits'], s_['flagger']['n']) else 'falha'}")
        else:
            L.append(f"- H6b ({sid}, Flagger vê heavy-reports): {s_['flagger']['hits']}/{s_['flagger']['n']}, "
                     f"LI95 {s_['flagger']['lo1']:.3f}: {'passa' if h6b_pass(s_['flagger']['hits'], s_['flagger']['n']) else 'falha'}")
    c = r["control"]["flagger"]
    L.append(f"- H6c (controle, Flagger): {c['false_alarms']} reversões em {c['runs']} execuções: "
             f"{'passa' if h6c_pass(c['false_alarms'], c['runs']) else 'falha'}")
    for sid, h in r["h7"].items():
        L.append(f"- H7 ({sid}, nosso detector x Flagger real): só nós {h['b']}, só Flagger {h['c']}, "
                 f"p {h['p']:.4f}, Holm {h['p_holm']:.4f}: {'rejeita H0' if h['reject'] else 'não rejeita'}")
    for sid, s_ in s.items():
        a = s_["agreement"]
        L.append(f"- H8 ({sid}, emulação x Flagger real): {a['agree']}/{a['n']} concordam: "
                 f"{'passa' if h8_pass(a['agree'], a['n']) else 'falha'}")
    L.append("\n## Controle: execuções com alarme falso\n")
    for k, v in r["control"].items():
        L.append(f"- {k}: {v['false_alarms']} de {v['runs']}")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("plan")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    r = analyze(a.out_dir, a.plan)
    out = a.out or a.out_dir
    with open(os.path.join(out, "ANALISE-flagger.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, sort_keys=True, ensure_ascii=False)
    md = render(r)
    with open(os.path.join(out, "ANALISE-flagger.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
