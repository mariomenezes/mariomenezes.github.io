"""Valores medidos em σ=0,1 para o portão de validade do simulador (Fase 2, v4).

Lê a suíte G4 já coletada (results/noise): controle de 4 h (`ncontrol-<c>`) e 5
execuções por fração e cluster (`np0.2r*-<c>`, `np0.1r*-<c>`), heavy-reports. As
definições são as mesmas de `decision_curve.gate_campaign`:
- razão = p95(v2)/p95(v1) por janela de controle (pula a 1ª janela, n >= 30 nas duas);
- p95_v1_med e mean_v1_med: mediana por janela de controle da v1;
- b115_control_alarms: detecções da regra B (1,15x) no controle;
- b<razão>_f<fração>: execuções com pelo menos uma detecção em heavy-reports.

Uso: python3 gate_measure.py [--dir results/noise] [--out phase2/gate-measured-sigma0.1.json]
"""
import argparse
import glob
import json
import os

from calib_lib import quantile
from replay import load_samples, replay

FEATURE = "heavy-reports"


def control_metrics(samples) -> dict:
    ratios, p95_v1, mean_v1 = [], [], []
    for s in samples[1:]:
        w = {x["version"]: x for x in s["windows"] if x["feature"] == FEATURE}
        if "v1" in w and "v2" in w and w["v1"]["n"] >= 30 and w["v2"]["n"] >= 30:
            p95_v1.append(w["v1"]["p95_ms"])
            mean_v1.append(w["v1"].get("mean_ms", 0.0))
            if w["v1"]["p95_ms"] > 0:
                ratios.append(w["v2"]["p95_ms"] / w["v1"]["p95_ms"])
    alarms = sum(1 for _, f, k in replay(samples, "x", rule="B", ratio=1.15).events
                 if f == FEATURE and k == "detected")
    return {"ratio_q50": quantile(ratios, 0.5), "ratio_q99": quantile(ratios, 0.99),
            "p95_v1_med": quantile(p95_v1, 0.5), "mean_v1_med": quantile(mean_v1, 0.5),
            "b115_control_alarms": alarms, "control_windows": len(ratios)}


def detected(samples, ratio: float) -> bool:
    return any(f == FEATURE and k == "detected" for _, f, k in replay(samples, "x", rule="B", ratio=ratio).events)


def measure(d: str, clusters=("a", "b")) -> dict:
    out = {}
    for c in clusters:
        for k, v in control_metrics(load_samples(os.path.join(d, f"ncontrol-{c}.jsonl")).samples).items():
            out[f"{c}/{k}"] = v
        for tag, frac in (("f20", "0.2"), ("f10", "0.1")):
            files = sorted(glob.glob(os.path.join(d, f"np{frac}r*-{c}.jsonl")))
            out[f"{c}/runs_{tag}"] = len(files)
            for name, r in (("b115", 1.15), ("b130", 1.30)):
                out[f"{c}/{name}_{tag}"] = sum(detected(load_samples(p).samples, r) for p in files)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--dir", default=os.path.join(here, "results", "noise"))
    ap.add_argument("--out", default=os.path.join(here, "phase2", "gate-measured-sigma0.1.json"))
    a = ap.parse_args()
    m = measure(a.dir)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, sort_keys=True)
    print(json.dumps(m, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
