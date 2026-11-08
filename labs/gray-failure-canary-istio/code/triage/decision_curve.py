"""Curva de decisão: detecção contra alarmes falsos, por limite, sob vários ruídos.

Plano de 29/10, itens 2 a 5. Offline, só biblioteca padrão, sem cluster.

Reaproveita do `noise_sim.py` o modelo do lab (atraso de 3 s, overhead de 50 ms,
VirtualService com perTryTimeout de 5 s e 2 tentativas, p95 por interpolação de
buckets) e acrescenta ruídos difíceis e réplicas:

  none, ln0.1/0.2/0.3 (lognormal), heavy98_2 (98% normal, 2% x1,6), pareto
  (cauda pesada), bimodal (+-15%), bursts (rajadas independentes por versão),
  ln0.1_pods3 e ln0.1_pods3_drift5 (3 réplicas por versão com deriva persistente
  por pod).

Divisão dos dados (protocolo do plano): o limite é APRENDIDO numa rodada de
calibração (semente A) e MEDIDO em outra (semente B). A curva e as tabelas vêm da
rodada de avaliação.

Regras comparadas por limite (razão do p95 de v2 sobre o da v1 na mesma janela):
  relative       degrada se p95 > razão x baseline e > piso (delta relativo)
  fixed_delta    a regra B atual: também exige p95 > baseline + 500 ms
  aprendida      razão = quantil 99,9% do ruído saudável (calib_lib.learn_threshold),
                 piso = maior p95 saudável da calibração
  B 1,15x        a regra B atual com o limite fixo

Uso:
  python3 decision_curve.py --out results/calibration/sim
  python3 decision_curve.py --quick            # poucos minutos de teste
  python3 decision_curve.py --noises ln0.1,bursts --hours 72 --runs 200 --jobs 4
  python3 decision_curve.py --mode gate --seed 1          # portão σ=0,1 (Fase 2, v4)
  python3 decision_curve.py --mode phase2 --seed 1 --eval-seed 2   # seleção e avaliação v4
"""
import argparse
import bisect
import csv
import math
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

from calib_lib import (RelativeRule, clopper_pearson, learn_threshold, poisson_upper,
                       quantile, run_detector)
import detector
from detector import Window
from noise_sim import BUCKETS, DELAY_S, OVERHEAD_S, PER_TRY_S

RATIOS = [round(1.03 + 0.01 * i, 2) for i in range(0, 38)]  # 1,03 .. 1,40
LEARN_RATIOS = [round(1.03 + 0.01 * i, 2) for i in range(0, 198)]  # 1,03 .. 3,00
FLOOR_Q = 0.99   # piso aprendido = quantil do p95 saudável (o máximo vira refém de um pico)
PRE = 5          # janelas de baseline antes da falha, como no protocolo do lab
FAULT_WINDOWS = 8
CHUNK_HOURS = 6  # a cada 6 h os pods são sorteados de novo (restart/deploy)
FA_TARGET = 0.1  # falsos alarmes por cluster-hora (limite superior de 95%)


# ----------------------------------------------------------------------- ruídos

@dataclass(frozen=True)
class Noise:
    name: str
    sigma: float = 0.0
    spike_p: float = 0.0
    spike_mult: float = 1.0
    pareto_alpha: float = 0.0
    pareto_scale: float = 0.0
    bimodal: Optional[Tuple[float, float, float]] = None  # (p_baixo, mult_baixo, mult_alto)
    burst_p: float = 0.0      # chance por janela e por versão de iniciar uma rajada
    burst_len: float = 3.0    # duração média em janelas (geométrica)
    burst_mult: float = 1.0
    replicas: int = 1
    pod_sigma: float = 0.0    # deriva persistente por pod (lognormal)


NOISES: Dict[str, Noise] = {n.name: n for n in [
    Noise("none"),
    Noise("ln0.1", sigma=0.1),
    Noise("ln0.2", sigma=0.2),
    Noise("ln0.3", sigma=0.3),
    Noise("heavy98_2", sigma=0.1, spike_p=0.02, spike_mult=1.6),
    Noise("pareto", sigma=0.1, pareto_alpha=3.0, pareto_scale=0.15),
    Noise("bimodal", sigma=0.05, bimodal=(0.5, 0.85, 1.15)),
    Noise("bursts", sigma=0.1, burst_p=0.003, burst_len=3.0, burst_mult=1.25),
    Noise("ln0.1_pods3", sigma=0.1, replicas=3, pod_sigma=0.03),
    Noise("ln0.1_pods3_drift5", sigma=0.1, replicas=3, pod_sigma=0.05),
]}

# (nome, fração das requisições, atraso extra em s). Como no lab: +1,5 s só na v2.
FRACTION_FAULTS = [("frac20", 0.20, 1.5), ("frac10", 0.10, 1.5), ("frac05", 0.05, 1.5)]
# um único pod da v2 ganha um atraso extra em todas as requisições (1/3 do tráfego)
POD_FAULTS = [("pod+1.0s", 1.0), ("pod+0.5s", 0.5), ("pod+0.25s", 0.25)]


# ------------------------------------------------------------------- simulação

def fast_quantile(sorted_lat: Sequence[float], q: float) -> float:
    """Mesma conta de noise_sim.histogram_quantile, com contagem por bisect."""
    n = len(sorted_lat)
    counts = [bisect.bisect_right(sorted_lat, b) for b in BUCKETS]
    rank = q * n
    for i, c in enumerate(counts):
        if c >= rank:
            lo = BUCKETS[i - 1] if i > 0 else 0.0
            clo = counts[i - 1] if i > 0 else 0
            inb = c - clo
            return lo + (BUCKETS[i] - lo) * ((rank - clo) / inb if inb else 1.0)
    return BUCKETS[-1]


def _mult(rng: random.Random, nz: Noise) -> float:
    m = rng.lognormvariate(0.0, nz.sigma) if nz.sigma > 0 else 1.0
    if nz.spike_p and rng.random() < nz.spike_p:
        m *= nz.spike_mult
    if nz.pareto_alpha:
        m *= 1.0 + nz.pareto_scale * (rng.paretovariate(nz.pareto_alpha) - 1.0)
    if nz.bimodal:
        p, lo, hi = nz.bimodal
        m *= lo if rng.random() < p else hi
    return m


def one_request(rng, nz, pod_f, burst_f, frac, extra_s, pod_extra_s):
    """(latência_ms, erro). Retry como no noise_sim: tentativa > 5 s é refeita."""
    def attempt():
        d = DELAY_S * _mult(rng, nz) * pod_f * burst_f
        if frac > 0 and rng.random() < frac:
            d += extra_s
        return d + pod_extra_s + OVERHEAD_S

    t1 = attempt()
    if t1 <= PER_TRY_S:
        return t1 * 1000, False
    t2 = attempt()
    if t2 <= PER_TRY_S:
        return (PER_TRY_S + t2) * 1000, False
    return 10000.0, True


class Version:
    """Estado de uma versão numa rodada: fatores por pod e rajada em curso."""

    def __init__(self, rng, nz: Noise):
        self.nz = nz
        self.pods = [rng.lognormvariate(0.0, nz.pod_sigma) if nz.pod_sigma > 0 else 1.0
                     for _ in range(nz.replicas)]
        self.burst_left = 0

    def burst_factor(self, rng) -> float:
        nz = self.nz
        if self.burst_left > 0:
            self.burst_left -= 1
            return nz.burst_mult
        if nz.burst_p and rng.random() < nz.burst_p:
            self.burst_left = max(0, int(rng.expovariate(1.0 / nz.burst_len)))
            return nz.burst_mult
        return 1.0

    def window(self, rng, n, frac=0.0, extra_s=0.0, slow_pod_extra=0.0):
        """Uma janela de 60 s. slow_pod_extra vale só para o pod 0."""
        bf = self.burst_factor(rng)
        lat, errs = [], 0
        r = len(self.pods)
        for _ in range(n):
            p = rng.randrange(r) if r > 1 else 0
            ms, e = one_request(rng, self.nz, self.pods[p], bf, frac, extra_s,
                                slow_pod_extra if p == 0 else 0.0)
            lat.append(ms)
            errs += e
        lat.sort()
        return lat, 100.0 * errs / n


def simulate(rng, nz: Noise, n_windows: int, n_mean: int, pre: int = 0,
             frac: float = 0.0, extra_s: float = 0.0, pod_extra_s: float = 0.0) -> List[Window]:
    """Série de janelas v2 contra v1 (mesma janela). A falha liga na janela `pre`."""
    v1, v2 = Version(rng, nz), Version(rng, nz)
    out = []
    for t in range(n_windows):
        n1 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
        n2 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
        on = t >= pre and (frac > 0 or pod_extra_s > 0)
        l1, _ = v1.window(rng, n1)
        l2, e2 = v2.window(rng, n2, frac if on else 0.0, extra_s if on else 0.0,
                           pod_extra_s if on else 0.0)
        out.append(Window(n=n2, err_pct=e2, p95_ms=fast_quantile(l2, 0.95),
                          baseline_p95_ms=fast_quantile(l1, 0.95),
                          mean_ms=sum(l2) / n2, baseline_mean_ms=sum(l1) / n1))
    return out


def healthy_runs(rng, nz, hours, n_mean) -> List[List[Window]]:
    chunks = max(1, int(round(hours / CHUNK_HOURS)))
    per = int(hours * 60 / chunks)
    return [simulate(rng, nz, per, n_mean) for _ in range(chunks)]


def fault_runs(rng, nz, runs, n_mean, **fault) -> List[List[Window]]:
    return [simulate(rng, nz, PRE + FAULT_WINDOWS, n_mean, pre=PRE, **fault) for _ in range(runs)]


# ------------------------------------------------------------------- avaliação

def alarms_in_healthy(series: List[List[Window]], rule: RelativeRule) -> int:
    return sum(1 for s in series for _, ev in run_detector(s, rule) if ev == "detected")


def detections(series: List[List[Window]], rule: RelativeRule) -> Tuple[int, List[int]]:
    """(execuções que detectaram dentro da falha, janelas até detectar desde a falha)."""
    hits, ttd = 0, []
    for s in series:
        first = next((i for i, ev in run_detector(s, rule) if ev == "detected"), None)
        if first is not None and first >= PRE:
            hits += 1
            ttd.append(first - PRE + 1)
    return hits, ttd


def learned_rule(cal_healthy: List[List[Window]], alpha: float = 1e-3) -> Tuple[RelativeRule, Dict]:
    """Regra do plano como escrita: razão = quantil 99,9% do ruído saudável por janela."""
    ratios = [w.p95_ms / w.baseline_p95_ms for s in cal_healthy for w in s
              if w.n >= 30 and w.baseline_p95_ms > 0]
    info = learn_threshold(ratios, alpha=alpha)
    floor = quantile([w.p95_ms for s in cal_healthy for w in s], FLOOR_Q)
    info["floor_ms"] = floor
    return RelativeRule(ratio=info["threshold"], floor_ms=floor, delta_ms=0.0), info


def alarm_calibrated(cal_healthy: List[List[Window]], delta_ms: float, floor_ms: float,
                     target: float = FA_TARGET) -> Optional[RelativeRule]:
    """Menor razão cujo falso alarme, JÁ com o filtro de 3 janelas, tem UB95 abaixo do alvo
    nos dados de calibração. Devolve None se nem 3,00x fecha o alvo."""
    hrs = sum(len(s) for s in cal_healthy) / 60.0
    for r in LEARN_RATIOS:
        rule = RelativeRule(ratio=r, floor_ms=floor_ms, delta_ms=delta_ms)
        if poisson_upper(alarms_in_healthy(cal_healthy, rule), hrs) < target:
            return rule
    return None


def run_noise(args_tuple) -> Dict:
    name, hours, runs, n_mean, seed = args_tuple
    nz = NOISES[name]
    base = random.Random(f"{seed}/{name}")
    cal_rng = random.Random(base.random())
    eval_rng = random.Random(base.random())

    cal_healthy = healthy_runs(cal_rng, nz, hours, n_mean)
    ev_healthy = healthy_runs(eval_rng, nz, hours, n_mean)
    faults = {fn: fault_runs(eval_rng, nz, runs, n_mean, frac=fr, extra_s=ex)
              for fn, fr, ex in FRACTION_FAULTS}
    if nz.replicas > 1:
        faults.update({fn: fault_runs(eval_rng, nz, runs, n_mean, pod_extra_s=ex)
                       for fn, ex in POD_FAULTS})

    rule_p, info = learned_rule(cal_healthy)
    floor = info["floor_ms"]
    rule_ar = alarm_calibrated(cal_healthy, 0.0, 1000.0)
    rule_af = alarm_calibrated(cal_healthy, 500.0, 1000.0)
    hrs = sum(len(s) for s in ev_healthy) / 60.0

    def point(rule):
        k = alarms_in_healthy(ev_healthy, rule)
        row = {"alarms": k, "hours": hrs, "fa_per_h": k / hrs, "fa_ub95": poisson_upper(k, hrs)}
        for fn, series in faults.items():
            h, ttd = detections(series, rule)
            lo, hi = clopper_pearson(h, len(series))
            row[fn] = {"hits": h, "n": len(series), "lo": lo, "hi": hi,
                       "ttd_med": quantile(ttd, 0.5) if ttd else None,
                       "ttd_p90": quantile(ttd, 0.9) if ttd else None}
        return row

    curve = []
    for fam, delta in (("relative", 0.0), ("fixed_delta", 500.0)):
        for r in RATIOS:
            p = point(RelativeRule(ratio=r, floor_ms=1000.0, delta_ms=delta))
            p.update(family=fam, ratio=r)
            curve.append(p)

    rules = [("B 1,15x fixo (delta 500 ms, piso 1000 ms)", RelativeRule(1.15, 1000.0, 500.0)),
             (f"quantil 99,9% por janela ({rule_p.ratio:.3f}x, piso {rule_p.floor_ms:.0f} ms): regra do plano como escrita", rule_p)]
    if rule_ar:
        rules.append((f"aprendida por alarme, delta relativo ({rule_ar.ratio:.2f}x, piso {rule_ar.floor_ms:.0f} ms)", rule_ar))
    if rule_af:
        rules.append((f"aprendida por alarme, com delta 500 ms ({rule_af.ratio:.2f}x)", rule_af))
    table = []
    for label, rule in rules:
        table.append({"label": label, "ratio": rule.ratio, "point": point(rule)})
    table_none = []
    if rule_ar is None:
        table_none.append("relative")
    if rule_af is None:
        table_none.append("fixed_delta")
    healthy_p95 = sorted(w.p95_ms for s in ev_healthy for w in s)
    return {"noise": name, "curve": curve, "table": table, "no_limit_closes_target": table_none,
            "learned_info": info,
            "healthy_p95": (quantile(healthy_p95, .05), quantile(healthy_p95, .5),
                            quantile(healthy_p95, .95), healthy_p95[-1]),
            "fault_names": list(faults)}


# -------------------------------------------------------------------- relatório

def _fmt_det(d) -> str:
    return f"{d['hits']}/{d['n']} [{100*d['lo']:.0f}-{100*d['hi']:.0f}%]"


def write_outputs(results: List[Dict], out: str, meta: Dict) -> None:
    os.makedirs(out, exist_ok=True)
    cols = ["noise", "family", "ratio", "alarms", "hours", "fa_per_h", "fa_ub95"]
    with open(os.path.join(out, "curve.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols + ["scenario", "hits", "n", "ci_lo", "ci_hi", "ttd_med_win", "ttd_p90_win"])
        for res in results:
            for c in res["curve"]:
                for fn in res["fault_names"]:
                    d = c[fn]
                    w.writerow([res["noise"], c["family"], c["ratio"], c["alarms"], f"{c['hours']:.1f}",
                                f"{c['fa_per_h']:.4f}", f"{c['fa_ub95']:.4f}", fn, d["hits"], d["n"],
                                f"{d['lo']:.3f}", f"{d['hi']:.3f}", d["ttd_med"], d["ttd_p90"]])

    L = []
    L.append("# Calibração do limite: curva de decisão simulada\n")
    L.append(f"Simulação offline (`decision_curve.py`), semente {meta['seed']}, "
             f"{meta['hours']} h saudáveis por ruído na calibração e outras {meta['hours']} h na avaliação, "
             f"{meta['runs']} execuções por cenário de falha ({PRE} janelas de baseline + {FAULT_WINDOWS} de falha), "
             f"{meta['n']} requisições por janela e versão. É previsão de modelo, não medição no cluster.\n")
    L.append("Intervalos: Clopper-Pearson bicaudal de 95% (o 74% do post é o limite unicaudal). "
             "Alarmes falsos: limite superior unicaudal de 95% de Poisson, por cluster-hora.\n")

    L.append("As linhas \"aprendida por alarme\" escolhem, na rodada de CALIBRAÇÃO, a menor razão cujo falso alarme "
             f"(já com o filtro de 3 janelas) tem UB95 abaixo de {FA_TARGET}/cluster-hora; os números da tabela vêm da "
             "rodada de AVALIAÇÃO, com outra semente. Com delta fixo de 500 ms, o limite efetivo nunca fica abaixo de "
             "1 + 500/baseline, cerca de 1,14x numa baseline de 3,5 s, qualquer que seja a razão escolhida.\n")

    L.append("## Resumo entre ruídos (falha de 10% e de 5%, +1,5 s; avaliação)\n")
    L.append("| Ruído | B 1,15x: falsos/h, 10%, 5% | Por alarme (delta relativo): limite, falsos/h, 10%, 5% |")
    L.append("|---|---|---|")
    for res in results:
        t = res["table"]
        b_ = t[0]["point"]
        rel = next((x for x in t if x["label"].startswith("aprendida por alarme, delta relativo")), None)
        def pct_(d):
            return f"{100*d['hits']/d['n']:.0f}%"
        left = f"{b_['alarms']} em {b_['hours']:.0f} h; {pct_(b_['frac10'])}; {pct_(b_['frac05'])}"
        if rel:
            r_ = rel["point"]
            right = (f"{rel['ratio']:.2f}x; {r_['alarms']} em {r_['hours']:.0f} h; "
                     f"{pct_(r_['frac10'])}; {pct_(r_['frac05'])}")
        else:
            right = "nenhum limite até 3,00x fecha o alvo"
        L.append(f"| {res['noise']} | {left} | {right} |")
    L.append("")

    L.append("## Detalhe por ruído\n")
    for res in results:
        fns = res["fault_names"]
        info = res["learned_info"]
        L.append(f"### {res['noise']}\n")
        p = res["healthy_p95"]
        L.append(f"p95 saudável da v1+v2 por janela: p5/p50/p95/máx = {p[0]:.0f}/{p[1]:.0f}/{p[2]:.0f}/{p[3]:.0f} ms. "
                 f"Razão saudável: p50 {info['p50']:.3f}, p99 {info['p99']:.3f}, máx {info['max']:.3f}; "
                 f"quantil 99,9% empírico {info['empirical_q']:.3f}, lognormal {info['lognormal_q']:.3f}.\n")
        L.append("| Regra | falsos/h (UB95) | " + " | ".join(fns) + " | TTD mediano médio (janelas) |")
        L.append("|" + "---|" * (len(fns) + 3))
        for item in res["table"]:
            row = item["point"]
            tt = [row[f]["ttd_med"] for f in fns if row[f]["ttd_med"] is not None]
            L.append(f"| {item['label']} | {row['alarms']} ({row['fa_per_h']:.3f}; {row['fa_ub95']:.3f}) | "
                     + " | ".join(_fmt_det(row[f]) for f in fns)
                     + f" | {('%.1f' % (sum(tt)/len(tt))) if tt else '-'} |")
        for fam in res["no_limit_closes_target"]:
            L.append(f"\nNenhum limite até 3,00x fecha o alvo de {FA_TARGET} falsos/h na calibração (família `{fam}`).")
        L.append("")
    with open(os.path.join(out, "summary.md"), "w") as fh:
        fh.write("\n".join(L))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib ausente: sem PNG (curve.csv e summary.md foram gravados)")
        return
    cols_n = min(3, len(results))
    rows_n = math.ceil(len(results) / cols_n)
    fig, axes = plt.subplots(rows_n, cols_n, figsize=(5 * cols_n, 3.8 * rows_n), squeeze=False)
    for ax, res in zip([a for r in axes for a in r], results):
        for fam, ls in (("relative", "-"), ("fixed_delta", "--")):
            pts = [c for c in res["curve"] if c["family"] == fam]
            for fn, colr in (("frac10", "tab:blue"), ("frac05", "tab:orange")):
                ax.plot([max(c["fa_ub95"], 1e-3) for c in pts], [c[fn]["hits"] / c[fn]["n"] for c in pts],
                        ls, color=colr, label=f"{fn} {fam}")
        ax.set_xscale("log")
        ax.axvline(FA_TARGET, color="gray", lw=0.8)
        ax.set_title(res["noise"], fontsize=10)
        ax.set_xlabel("falsos alarmes por cluster-hora (UB95)")
        ax.set_ylabel("detecção")
        ax.set_ylim(-0.02, 1.02)
    for ax in [a for r in axes for a in r][len(results):]:
        ax.set_visible(False)
    axes[0][0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "curves.png"), dpi=130)


# ==================================================================== Fase 2 (v4)
#
# Por feature (heavy-reports e dashboard), por modelo de cluster (a, b) e por σ do
# atraso de heavy-reports. Avalia as regras B, BF e D com o detector real, nos buckets
# da annotation (BUCKETS), seleciona a regra SÓ com a semente de calibração e mede com
# outra semente. O portão de validade compara o simulador com o medido em σ=0,1.

# n por janela e versão medido no controle; latência base do dashboard: no cluster a os
# pedidos ficam abaixo de 1 ms (p95 0,9-1,0 por interpolação), no b logo acima (p95 4,8).
# A média medida é 1,0 ms nos dois. O σ do lab só age em heavy-reports.
CLUSTER_MODELS = {"a": {"heavy-reports": 76, "dashboard": 176, "dash_ms": 0.95},
                  "b": {"heavy-reports": 95, "dashboard": 95, "dash_ms": 1.05}}
DASH_SIGMA = 0.02
SIGMAS_V4 = (0.1, 0.3)
LIMIT_GRID = {"heavy-reports": (3500.0, 3750.0, 4000.0), "dashboard": (100.0, 250.0, 500.0)}
DEFAULT_LIMIT = {"heavy-reports": 3750.0, "dashboard": 250.0}
FLOOR_GRID = {"dashboard": (100.0, 250.0, 500.0)}
DELTA_GRID = (0.02, 0.05, 0.10)
FAULTS_V4 = {"heavy-reports": [("f20", 0.20, 1.5), ("f10", 0.10, 1.5), ("f05", 0.05, 1.5)],
             "dashboard": [("f20", 0.20, 0.5), ("f10", 0.10, 0.5), ("f05", 0.05, 0.5)]}
PRIMARY_FAULT, SECOND_FAULT = "f10", "f05"
SELECTABLE = ("B", "BF", "D")  # ordem = desempate por simplicidade


@dataclass
class SimWindow:
    w: Window
    counts: Dict[float, Tuple[int, int]]  # limite -> (lentas v2, lentas v1)


def slow_above(sorted_lat: Sequence[float], limit_ms: float) -> int:
    """Requisições acima da borda: n menos o bucket acumulado le=limit (que conta <=)."""
    return len(sorted_lat) - bisect.bisect_right(sorted_lat, limit_ms)


def check_edges(limits: Sequence[float]) -> None:
    bad = [x for x in limits if float(x) not in {float(b) for b in BUCKETS}]
    if bad:
        raise ValueError(f"limites fora das bordas dos buckets: {bad}")


check_edges([x for g in LIMIT_GRID.values() for x in g])


def _dash_window(rng, n, base_ms, frac, extra_s):
    lat = []
    for _ in range(n):
        ms = base_ms * rng.lognormvariate(0.0, DASH_SIGMA)
        if frac > 0 and rng.random() < frac:
            ms += extra_s * 1000.0
        lat.append(ms)
    lat.sort()
    return lat, 0.0


def simulate_feature(rng, feature: str, cluster: str, sigma: float, n_windows: int, pre: int = 0,
                     frac: float = 0.0, extra_s: float = 0.0) -> List[SimWindow]:
    """Série v2 contra v1 da mesma janela; a falha (só na v2) liga na janela `pre`."""
    cm = CLUSTER_MODELS[cluster]
    n_mean = cm[feature]
    limits = LIMIT_GRID[feature]
    if feature == "heavy-reports":
        nz = Noise("sim", sigma=sigma)
        v1, v2 = Version(rng, nz), Version(rng, nz)
    out = []
    for t in range(n_windows):
        n1 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
        n2 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
        on = t >= pre and frac > 0
        if feature == "heavy-reports":
            l1, _ = v1.window(rng, n1)
            l2, e2 = v2.window(rng, n2, frac if on else 0.0, extra_s if on else 0.0)
        else:
            l1, _ = _dash_window(rng, n1, cm["dash_ms"], 0.0, 0.0)
            l2, e2 = _dash_window(rng, n2, cm["dash_ms"], frac if on else 0.0, extra_s)
        counts = {L: (slow_above(l2, L), slow_above(l1, L)) for L in limits}
        d = counts[DEFAULT_LIMIT[feature]]
        out.append(SimWindow(Window(n=n2, err_pct=e2, p95_ms=fast_quantile(l2, 0.95),
                                    baseline_p95_ms=fast_quantile(l1, 0.95), mean_ms=sum(l2) / n2,
                                    baseline_mean_ms=sum(l1) / n1, slow_n=d[0], base_n=n1,
                                    base_slow_n=d[1]), counts))
    return out


@dataclass(frozen=True)
class RuleSpec:
    name: str
    rule: str
    floor: Optional[float] = None   # BF: piso (variante)
    limit: Optional[float] = None   # D: borda L
    delta: Optional[float] = None   # D: diferença mínima (variante)
    ratio: Optional[float] = None   # B/BF: razão (None = detector.RELATIVE_RATIO_LIMIT)
    variant: bool = False           # True = parâmetros fora do detector (só sensibilidade)


def window_for(spec: RuleSpec, sw: SimWindow) -> Window:
    if spec.rule == detector.RULE_D and spec.limit is not None:
        s2, s1 = sw.counts[spec.limit]
        return replace(sw.w, slow_n=s2, base_slow_n=s1)
    return sw.w


def _frac_up(w: Window, delta: float) -> bool:
    """Mesmo teste de detector._slow_fraction_up, com a diferença mínima explícita."""
    if w.slow_n < 0 or w.base_slow_n < 0 or w.base_n < detector.MIN_SAMPLE or w.n <= 0:
        return False
    p2, p1 = w.slow_n / w.n, w.base_slow_n / w.base_n
    if p2 - p1 + detector._EPS < delta:
        return False
    pooled = (w.slow_n + w.base_slow_n) / (w.n + w.base_n)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / w.n + 1.0 / w.base_n))
    return se > 0 and (p2 - p1) / se >= detector.SLOW_FRAC_Z


def make_decider(spec: RuleSpec, feature: str):
    """(degradada?, insuficiente?) por janela. Sem `variant`, é o detector real."""
    insuf = lambda w: detector.is_insufficient(w, spec.rule)  # noqa: E731
    if not spec.variant:
        return (lambda w: detector.is_degraded(w, spec.rule, feature, spec.ratio)), insuf
    err = lambda w: w.err_pct > detector.ERROR_RATE_LIMIT_PCT  # noqa: E731
    if spec.rule == detector.RULE_BF:
        _, d_ms = detector.PER_FEATURE_LATENCY.get(feature, detector.DEFAULT_FEATURE_LATENCY)
        r = detector.RELATIVE_RATIO_LIMIT if spec.ratio is None else spec.ratio
        return (lambda w: err(w) or (w.p95_ms > r * w.baseline_p95_ms and w.p95_ms > w.baseline_p95_ms + d_ms
                                     and w.p95_ms > spec.floor)), insuf
    if spec.rule == detector.RULE_D:
        return (lambda w: err(w) or _frac_up(w, spec.delta)), insuf
    raise ValueError(f"variante não suportada: {spec}")


def streak_events(seq: Sequence[Window], dec, insuf) -> List[Tuple[int, str]]:
    """Mesma semântica de SubsetDetector.observe (3 para degradar, 3 para recuperar)."""
    state, bad, good, out = "healthy", 0, 0, []
    for i, w in enumerate(seq):
        if insuf(w):
            continue
        if dec(w):
            bad, good = bad + 1, 0
            if state == "healthy" and bad >= detector.WINDOWS_TO_DEGRADE:
                state = "degraded"
                out.append((i, "detected"))
            continue
        bad, good = 0, good + 1
        if state == "degraded" and good >= detector.WINDOWS_TO_RECOVER:
            state, good = "healthy", 0
            out.append((i, "recovered"))
    return out


def primary_specs(feature: str) -> List[RuleSpec]:
    return [RuleSpec("B", detector.RULE_B), RuleSpec("BF", detector.RULE_BF),
            RuleSpec("D", detector.RULE_D, limit=DEFAULT_LIMIT[feature])]


def sensitivity_specs(feature: str) -> List[RuleSpec]:
    out = [RuleSpec(f"BF piso {fl:.0f}", detector.RULE_BF, floor=fl, variant=True)
           for fl in FLOOR_GRID.get(feature, ())]
    out += [RuleSpec(f"D L={L:.0f} Δ={100 * d:.0f}pp", detector.RULE_D, limit=L, delta=d, variant=True)
            for L in LIMIT_GRID[feature] for d in DELTA_GRID]
    return out


def evaluate_cell(args) -> Tuple[str, Dict]:
    label, feature, cluster, sigma, hours, runs = args
    rng = random.Random(f"{label}/{feature}/{cluster}/{sigma}")
    chunks = max(1, int(round(hours / CHUNK_HOURS)))
    per = int(hours * 60 / chunks)
    healthy = [simulate_feature(rng, feature, cluster, sigma, per) for _ in range(chunks)]
    faults = {fn: [simulate_feature(rng, feature, cluster, sigma, PRE + FAULT_WINDOWS, pre=PRE,
                                    frac=fr, extra_s=ex) for _ in range(runs)]
              for fn, fr, ex in FAULTS_V4[feature]}
    hrs = sum(len(s) for s in healthy) / 60.0
    res = {"_data": round(sum(sw.w.p95_ms for s in healthy for sw in s), 3)}
    for spec in primary_specs(feature) + sensitivity_specs(feature):
        dec, insuf = make_decider(spec, feature)
        k = sum(1 for s in healthy for _, ev in streak_events([window_for(spec, x) for x in s], dec, insuf)
                if ev == "detected")
        row = {"alarms": k, "hours": hrs, "fa_ub95": poisson_upper(k, hrs), "faults": {}}
        for fn, series in faults.items():
            hits, ttd = 0, []
            for s in series:
                first = next((i for i, ev in streak_events([window_for(spec, x) for x in s], dec, insuf)
                              if ev == "detected"), None)
                if first is not None and first >= PRE:
                    hits += 1
                    ttd.append(first - PRE + 1)
            row["faults"][fn] = {"hits": hits, "n": len(series), "rate": hits / len(series),
                                 "lo1": clopper_pearson(hits, len(series), two_sided=False)[0],
                                 "ttd_med": quantile(ttd, 0.5) if ttd else None}
        res[spec.name] = row
    return f"{feature}|{cluster}|{sigma}", res


def select_rule(table: Dict[str, List[Dict]], names: Sequence[str] = SELECTABLE):
    """Critério de seleção (v4, seção "Seleção"), só com a calibração.

    Elegível: falso alarme com UB95 < FA_TARGET em TODOS os clusters. Entre as
    elegíveis: maior detecção no pior cluster na falha primária (f10); desempate pela
    falha seguinte (f05), depois pelo pior TTD mediano em f10 (menor vence; sem TTD
    perde), depois pela ordem de `names` (mais simples primeiro)."""
    elig = [n for n in names if all(c["fa_ub95"] < FA_TARGET for c in table[n])]

    def key(n):
        cs = table[n]
        ttds = [c["faults"][PRIMARY_FAULT]["ttd_med"] for c in cs]
        worst_ttd = math.inf if any(t is None for t in ttds) else max(ttds)
        return (-min(c["faults"][PRIMARY_FAULT]["rate"] for c in cs),
                -min(c["faults"][SECOND_FAULT]["rate"] for c in cs), worst_ttd, list(names).index(n))
    detail = {"eligible": elig}
    return (min(elig, key=key) if elig else None), detail


LEVEL_SENSITIVE = {"heavy-reports": ("D",)}  # regras cuja base saudável depende do nível absoluto


def final_selection(cal: Dict, verdict: Dict, features=("heavy-reports", "dashboard"), sigmas=SIGMAS_V4,
                    clusters=("a", "b")) -> Dict:
    """Seleção da calibração com as consequências do portão (v4, seção "Portão"):
    métrica de decisão fora -> B em tudo; só nível fora -> sem as regras sensíveis ao
    nível em heavy-reports; nenhuma elegível -> B, com previsão de falha de H3."""
    out = {}
    for f in features:
        for s in sigmas:
            if not verdict["decision_ok"]:
                out[f"{f}|{s}"] = {"rule": "B", "eligible": [], "predict_h3_fail": False,
                                   "why": "portão: métrica de decisão fora; B em tudo"}
                continue
            names = [n for n in SELECTABLE
                     if verdict["level_ok"] or n not in LEVEL_SENSITIVE.get(f, ())]
            table = {n: [cal[f"{f}|{c}|{s}"][n] for c in clusters] for n in names}
            name, detail = select_rule(table, names)
            out[f"{f}|{s}"] = {"rule": name or "B", "eligible": detail["eligible"],
                               "predict_h3_fail": name is None,
                               "why": "seleção na calibração" if name else "nenhuma elegível: B, H3 deve falhar"}
    return out


def run_phase2(seed: int, eval_seed: int, features=("heavy-reports", "dashboard"), clusters=("a", "b"),
               sigmas=SIGMAS_V4, hours: float = 72, runs: int = 200, jobs: int = 1) -> Dict:
    if seed == eval_seed:
        raise ValueError("as sementes de calibração e de avaliação precisam ser diferentes")

    def cells(label):
        todo = [(label, f, c, s, hours, runs) for f in features for c in clusters for s in sigmas]
        if jobs > 1:
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                return dict(ex.map(evaluate_cell, todo))
        return dict(map(evaluate_cell, todo))

    cal = cells(f"cal{seed}")
    selection = {}
    for f in features:
        for s in sigmas:
            table = {n: [cal[f"{f}|{c}|{s}"][n] for c in clusters] for n in SELECTABLE}
            name, detail = select_rule(table)
            selection[f"{f}|{s}"] = {"rule": name, **detail}
    # a avaliação roda DEPOIS e nunca entra na seleção
    ev = cells(f"eval{eval_seed}")
    return {"seed": seed, "eval_seed": eval_seed, "hours": hours, "runs": runs,
            "calibration": cal, "selection": selection, "evaluation": ev}


# ------------------------------------------------------- portão de validade (σ=0,1)

GATE_METRICS = ("ratio_q50", "ratio_q99", "b115_control_alarms", "b115_f20", "b115_f10",
                "b130_f20", "b130_f10", "p95_v1_med", "mean_v1_med")
LEVEL_METRICS = ("p95_v1_med", "mean_v1_med")  # nível absoluto; o resto decide


def gate_campaign(rng, cluster: str, control_windows: int = 240, reps: int = 5, sigma: float = 0.1) -> Dict:
    """Uma campanha com o desenho da suíte G4 medida (results/noise): controle de 4 h e 5
    execuções por fração (5 janelas de base + 8 de falha), heavy-reports."""
    ctrl = [sw.w for sw in simulate_feature(rng, "heavy-reports", cluster, sigma, control_windows)]
    ratios = [w.p95_ms / w.baseline_p95_ms for w in ctrl if w.baseline_p95_ms > 0]
    b115 = make_decider(RuleSpec("B", detector.RULE_B, ratio=1.15), "heavy-reports")
    b130 = make_decider(RuleSpec("B", detector.RULE_B, ratio=1.30), "heavy-reports")
    out = {"ratio_q50": quantile(ratios, 0.5), "ratio_q99": quantile(ratios, 0.99),
           "b115_control_alarms": sum(1 for _, e in streak_events(ctrl, *b115) if e == "detected"),
           "p95_v1_med": quantile([w.baseline_p95_ms for w in ctrl], 0.5),
           "mean_v1_med": quantile([w.baseline_mean_ms for w in ctrl], 0.5)}
    for tag, fr in (("f20", 0.20), ("f10", 0.10)):
        runs = [[sw.w for sw in simulate_feature(rng, "heavy-reports", cluster, sigma, PRE + FAULT_WINDOWS,
                                                 pre=PRE, frac=fr, extra_s=1.5)] for _ in range(reps)]
        for name, dd in (("b115", b115), ("b130", b130)):
            out[f"{name}_{tag}"] = sum(1 for s in runs if any(e == "detected" for _, e in streak_events(s, *dd)))
    return out


def _gate_one(args):
    seed, cluster, r = args
    return cluster, gate_campaign(random.Random(f"gate{seed}/{cluster}/{r}"), cluster)


def central_interval(xs: Sequence[float]) -> Tuple[float, float]:
    return quantile(xs, 0.025), quantile(xs, 0.975)


def predict_gate(seed: int = 1, clusters=("a", "b"), replicates: int = 200, jobs: int = 1) -> Dict:
    todo = [(seed, c, r) for c in clusters for r in range(replicates)]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            got = list(ex.map(_gate_one, todo))
    else:
        got = list(map(_gate_one, todo))
    return {f"{c}/{m}": central_interval([g[m] for cc, g in got if cc == c])
            for c in clusters for m in GATE_METRICS}


def check_gate(pred: Dict[str, Tuple[float, float]], measured: Dict[str, float]) -> Dict:
    out = {}
    for k, (lo, hi) in pred.items():
        v = measured.get(k)
        out[k] = {"lo": lo, "hi": hi, "measured": v, "ok": v is not None and lo <= v <= hi}
    return out


def gate_verdict(res: Dict) -> Dict:
    lvl = lambda k: k.split("/", 1)[1] in LEVEL_METRICS  # noqa: E731
    return {"decision_ok": all(r["ok"] for k, r in res.items() if not lvl(k)),
            "level_ok": all(r["ok"] for k, r in res.items() if lvl(k)),
            "failed": sorted(k for k, r in res.items() if not r["ok"])}


def _main_v4(a) -> None:
    import json
    out = a.out if a.out != "results/calibration/sim" else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "phase2")
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    if a.mode == "gate":
        pred = predict_gate(a.seed, replicates=a.replicates, jobs=a.jobs)
        with open(a.measured, encoding="utf-8") as f:
            measured = json.load(f)
        res = check_gate(pred, measured)
        verdict = gate_verdict(res)
        path = os.path.join(out, f"gate-result-seed{a.seed}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"seed": a.seed, "replicates": a.replicates, "verdict": verdict, "metrics": res},
                      f, indent=1, sort_keys=True)
        for k, r in sorted(res.items()):
            print(f"{'ok ' if r['ok'] else 'FORA'} {k:26s} medido {r['measured']!s:>8.8} intervalo "
                  f"[{r['lo']:.4g}, {r['hi']:.4g}]")
        print(json.dumps(verdict, ensure_ascii=False))
    else:
        hours, runs = (a.hours, a.runs) if not a.quick else (12, 40)
        res = run_phase2(a.seed, a.eval_seed, hours=hours, runs=runs, jobs=a.jobs)
        gate_path = os.path.join(out, f"gate-result-seed{a.seed}.json")
        if not os.path.exists(gate_path):
            raise SystemExit(f"rode antes o portão: --mode gate --seed {a.seed} ({gate_path})")
        with open(gate_path, encoding="utf-8") as f:
            res["gate_verdict"] = json.load(f)["verdict"]
        res["final_selection"] = final_selection(res["calibration"], res["gate_verdict"])
        path = os.path.join(out, f"phase2-cal{a.seed}-eval{a.eval_seed}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1, sort_keys=True, ensure_ascii=False)
        print(json.dumps(res["final_selection"], ensure_ascii=False, indent=1))
    print(f"gravado {path} em {time.time() - t0:.0f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/calibration/sim")
    ap.add_argument("--noises", default=",".join(NOISES))
    ap.add_argument("--hours", type=float, default=72, help="horas saudáveis por ruído e por rodada")
    ap.add_argument("--runs", type=int, default=200, help="execuções por cenário de falha")
    ap.add_argument("--n", type=int, default=80, help="requisições por janela e versão")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--quick", action="store_true", help="12 h e 40 execuções, só para testar")
    ap.add_argument("--mode", choices=("curve", "phase2", "gate"), default="curve",
                    help="curve: curva da v3; phase2: seleção (calibração) e avaliação v4; gate: portão σ=0,1")
    ap.add_argument("--eval-seed", type=int, default=2)
    ap.add_argument("--replicates", type=int, default=200, help="campanhas simuladas no portão")
    ap.add_argument("--measured", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase2",
                                                       "gate-measured-sigma0.1.json"))
    a = ap.parse_args()
    if a.mode != "curve":
        return _main_v4(a)
    if a.quick:
        a.hours, a.runs = 12, 40
    names = a.noises.split(",")
    for nm in names:
        if nm not in NOISES:
            ap.error(f"ruído desconhecido: {nm} (opções: {', '.join(NOISES)})")
    t0 = time.time()
    jobs = [(nm, a.hours, a.runs, a.n, a.seed) for nm in names]
    if a.jobs > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            results = list(ex.map(run_noise, jobs))
    else:
        results = [run_noise(j) for j in jobs]
    write_outputs(results, a.out, {"seed": a.seed, "hours": a.hours, "runs": a.runs, "n": a.n})
    print(f"gravado em {a.out}/ (summary.md, curve.csv) em {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
