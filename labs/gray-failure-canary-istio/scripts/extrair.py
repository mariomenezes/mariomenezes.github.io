"""Extrai dos dados brutos os números usados nas figuras e no texto dos posts da série.

Uso (na raiz do lab): python3 scripts/extrair.py
Lê data/*.tar.gz e data/*.json, usa o código do experimento em code/ (só biblioteca padrão)
e grava data/figuras.json. As figuras saem de scripts/make_figures.py, que só lê esse arquivo.
"""
import json
import os
import statistics
import sys
import tarfile
import tempfile

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(LAB, "code", "triage"))

import eval_flagger  # noqa: E402
import eval_v5  # noqa: E402
import market_emul as me  # noqa: E402
from calib_lib import clopper_pearson  # noqa: E402
from replay import _epoch, load_samples  # noqa: E402

LIM = eval_v5.LIMITS
PRIM = eval_v5.PRIMARY
DATA = os.path.join(LAB, "data")


def untar(tmp):
    for name in os.listdir(DATA):
        if name.endswith(".tar.gz"):
            with tarfile.open(os.path.join(DATA, name)) as t:
                t.extractall(tmp, filter="data")


def runs(d, c):
    p = os.path.join(d, c, "runs.jsonl")
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def plan(name):
    return os.path.join(LAB, "code", "triage", "plans", name)


def v5_section(tmp):
    d = os.path.join(tmp, "eval-v5")
    r = eval_v5.analyze(d, plan("EVAL-V5-sigma0.1.json"))
    feat = {"dash10": "dashboard", "dash20": "dashboard", "heavy10": "heavy-reports", "heavy20": "heavy-reports"}
    ttd = {s: [] for s in feat}
    for c in ("a", "b"):
        for x in runs(d, c):
            if x["status"] != "ok" or x["kind"] != "fault":
                continue
            s = load_samples(os.path.join(d, c, x["file"])).samples
            f = feat[x["scenario"]]
            det = me.detect(s, x["t_on"], x["t_off"], f"feature:{PRIM[f]}", feature=f, limits=LIM)
            if det["detected"]:
                ttd[x["scenario"]].append(det["ttd_windows"])
    return {"methods": {sid: {m: (v["hits"], v["n"]) for m, v in s["methods"].items()}
                        for sid, s in r["scenarios"].items()},
            "primary": {sid: (s["primary"]["hits"], s["primary"]["n"], s["primary"]["lo1"])
                        for sid, s in r["scenarios"].items()},
            "ttd": ttd, "control": r["control"], "h5": r["h5"],
            "runs_ok": sum(1 for c in ("a", "b") for x in runs(d, c) if x["status"] == "ok"),
            "discarded": sum(1 for c in ("a", "b") for x in runs(d, c) if x["status"] != "ok")}


def flagger_section(tmp):
    d = os.path.join(tmp, "flagger-v6")
    r = eval_flagger.analyze(d, plan("FLAGGER-V6.json"))
    rows = []
    for c in ("a", "b"):
        for x in runs(d, c):
            if x["status"] != "ok":
                continue
            s = load_samples(os.path.join(d, c, x["file"])).samples
            row = {"cluster": c, "rep": x["rep"], "scenario": x["scenario"], "phase": x["flagger_phase"]}
            if x["kind"] == "fault":
                f = "dashboard" if x["scenario"].startswith("dash") else "heavy-reports"
                det = me.detect(s, x["t_on"], x["t_off"], f"feature:{PRIM[f]}", feature=f, limits=LIM)
                row.update(
                    flagger_hit=eval_flagger.flagger_hit(x["flagger_phase"], x.get("flagger_failed_at"),
                                                         x["t_on"], x["t_off"]),
                    flagger_min=(x["flagger_failed_at"] - x["t_on"]) / 60 if x.get("flagger_failed_at") else None,
                    ours=det["detected"], ours_min=det["ttd_windows"],
                    agg_b=me.detect(s, x["t_on"], x["t_off"], "agg_b")["detected"],
                    flagger_rel=me.detect(s, x["t_on"], x["t_off"], "flagger_rel")["detected"])
            rows.append(row)
    return {"scenarios": {sid: {k: (v["hits"], v["n"]) for k, v in s.items() if isinstance(v, dict) and "hits" in v}
                          | {"agreement": (s["agreement"]["agree"], s["agreement"]["n"])}
                          for sid, s in r["scenarios"].items()},
            "control": r["control"], "h7": r["h7"], "rows": rows,
            "runs_ok": len(rows), "discarded": sum(1 for c in ("a", "b") for x in runs(d, c) if x["status"] != "ok")}


def path_section(tmp):
    """p95 do dashboard por janela, no piloto com o caminho quebrado e no piloto corrigido."""
    out = {}
    for tag in ("pilot-flagger-caminho-quebrado", "pilot-flagger-caminho-ok"):
        d = os.path.join(tmp, tag)
        vals = {"v1": [], "v2": []}
        for c in ("a", "b"):
            for x in runs(d, c):
                if x["status"] != "ok" or x["scenario"] != "dash10":
                    continue
                for s in load_samples(os.path.join(d, c, x["file"])).samples:
                    if _epoch(s["ts"]) > x["t_on"]:  # só antes da falha: latência do caminho, sem a falha
                        continue
                    for w in s["windows"]:
                        if w["feature"] == "dashboard":
                            vals[w["version"]].append(w["p95_ms"])
        out[tag] = vals
    return out


def power_section():
    from math import comb

    def maxk(n, t):
        k = -1
        while k + 1 <= n and clopper_pearson(n - (k + 1), n, two_sided=False)[0] >= t:
            k += 1
        return k

    def pp(n, p, k):
        return sum(comb(n, i) * (1 - p) ** i * p ** (n - i) for i in range(k + 1))
    grid = [round(0.60 + 0.005 * i, 3) for i in range(81)]
    crit = {"v4": (29, 0.90), "v5": (30, 0.80)}
    res = {}
    for name, (n, t) in crit.items():
        k = maxk(n, t)
        res[name] = {"n": n, "lb": t, "max_misses": k, "curve": [(p, pp(n, p, k)) for p in grid],
                     "at_0975": pp(n, 0.975, k), "at_095": pp(n, 0.95, k), "at_070": pp(n, 0.70, k)}
    res["power_n"] = []
    for n in (29, 30, 40, 46, 50, 60, 64, 76, 90):
        k = maxk(n, 0.90)
        res["power_n"].append((n, k, pp(n, 0.975, k)))
    return res


def gate_section():
    g = json.load(open(os.path.join(DATA, "gate-result-seed1.json")))
    p2 = json.load(open(os.path.join(DATA, "phase2-cal1-eval2.json")))
    sel = {}
    for key, cell in p2["calibration"].items():
        f, c, s = key.split("|")
        sel[key] = {n: {"fa_ub95": cell[n]["fa_ub95"], "alarms": cell[n]["alarms"],
                        "f10": cell[n]["faults"]["f10"]["rate"], "f05": cell[n]["faults"]["f05"]["rate"]}
                    for n in ("B", "BF", "D")}
    return {"metrics": g["metrics"], "verdict": g["verdict"], "calibration": sel,
            "final": p2.get("final_selection")}


def showcase_section(tmp, cluster="a", rep=1):
    """Uma execução de dash10 do Flagger real, minuto a minuto: o sinal do detector por feature
    (fração do dashboard acima de 250 ms, v1 e v2) e a razão de p99 agregada canary/primary
    calculada dos mesmos dados (a emulação da análise do Flagger, que concordou 59/60 com ele)."""
    d = os.path.join(tmp, "flagger-v6")
    r = next(x for x in runs(d, cluster) if x["scenario"] == "dash10" and x["rep"] == rep and x["status"] == "ok")
    s = load_samples(os.path.join(d, cluster, r["file"])).samples
    aggw = me._agg_windows(s)
    rows = []
    for x, aw in zip(s, aggw):
        t = (_epoch(x["ts"]) - r["t_on"]) / 60
        w = {(y["version"], y["feature"]): y for y in x["windows"]}
        frac = {}
        for v in ("v1", "v2"):
            b = w[(v, "dashboard")]["buckets"]
            frac[v] = (b["+Inf"] - b["250"]) / b["+Inf"] if b["+Inf"] else None
        rows.append({"t": t, "frac_v1": frac["v1"], "frac_v2": frac["v2"],
                     "p99_ratio": (aw.p95_ms / aw.baseline_p95_ms) if aw and aw.baseline_p95_ms else None})
    det = me.detect(s, r["t_on"], r["t_off"], "feature:D", feature="dashboard", limits=LIM)
    return {"cluster": cluster, "rep": rep, "rows": rows, "fault_min": (r["t_off"] - r["t_on"]) / 60,
            "ours_label_min": (det["first_label"] - r["t_on"]) / 60 if det["first_label"] else None,
            "flagger_phase": r["flagger_phase"], "failed_checks_max": r.get("failed_checks_max")}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        untar(tmp)
        out = {"v5": v5_section(tmp), "flagger": flagger_section(tmp), "path": path_section(tmp),
               "power": power_section(), "gate": gate_section(), "showcase": showcase_section(tmp)}
    for name in ("linha-do-tempo.json", "mutacao.json", "caminho-medicoes.json"):
        p = os.path.join(DATA, name)
        if os.path.exists(p):
            out[name.split(".")[0]] = json.load(open(p))
    with open(os.path.join(DATA, "figuras.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    fl = out["flagger"]
    print("v5:", out["v5"]["runs_ok"], "ok,", out["v5"]["discarded"], "descartes;",
          "flagger:", fl["runs_ok"], "ok,", fl["discarded"], "descartes")
    print("flagger minutos até reverter (heavy10): mediana",
          statistics.median([r["flagger_min"] for r in fl["rows"] if r["scenario"] == "heavy10"]))


if __name__ == "__main__":
    main()
