"""Simulação offline de G4 (latência variável): escolhe SLOW_JITTER_SIGMA e prevê
falso alarme e detecção das regras A/B/C antes de mexer no cluster.

Modelo, por janela de 60 s e por versão de `heavy-reports`:
- atraso = SLOW_DELAY_S * lognormal(0, sigma) (+ extra numa fração, na falha);
- overhead fixo de ~50 ms (média medida 3049 ms com sleep de 3 s);
- VirtualService: perTryTimeout 5 s, 2 tentativas, timeout 10 s. Tentativa > 5 s
  é refeita (latência 5 s + nova tentativa); duas estouradas viram 504 a 10 s;
- p95 como o Prometheus: histogram_quantile com interpolação linear nos buckets
  da annotation atual do probe-generator;
- detector real (detector.py), semântica do agente: v2 contra a v1 da mesma
  janela, 3 janelas consecutivas.

O modelo de retry é uma hipótese (o retryOn padrão do Istio não foi conferido);
p95 de 10 s com 504 na seção 10.1, item 2 sugere que o retry acontece.

Uso: python3 noise_sim.py [--hours 300] [--seed 1]
"""
import argparse
import math
import random

from detector import RULES, SubsetDetector, Window

BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 2500, 2750, 3000, 3250,
           3500, 3750, 4000, 4250, 4750, 5000, 7500, 10000, 30000]
DELAY_S = 3.0
OVERHEAD_S = 0.05
PER_TRY_S = 5.0


def one_request(rng, sigma, extra_frac, extra_s):
    """Retorna (latência_ms, erro)."""
    def attempt():
        d = DELAY_S * (rng.lognormvariate(0.0, sigma) if sigma > 0 else 1.0)
        if extra_frac > 0 and rng.random() < extra_frac:
            d += extra_s
        return d + OVERHEAD_S
    t1 = attempt()
    if t1 <= PER_TRY_S:
        return t1 * 1000, False
    t2 = attempt()
    if t2 <= PER_TRY_S:
        return (PER_TRY_S + t2) * 1000, False
    return 10000.0, True


def histogram_quantile(q, lat_ms):
    n = len(lat_ms)
    counts = [sum(1 for x in lat_ms if x <= b) for b in BUCKETS]
    rank = q * n
    for i, c in enumerate(counts):
        if c >= rank:
            lo = BUCKETS[i - 1] if i > 0 else 0.0
            clo = counts[i - 1] if i > 0 else 0
            inb = c - clo
            return lo + (BUCKETS[i] - lo) * ((rank - clo) / inb if inb else 1.0)
    return BUCKETS[-1]


def window(rng, n, sigma, extra_frac=0.0, extra_s=0.0):
    reqs = [one_request(rng, sigma, extra_frac, extra_s) for _ in range(n)]
    lat = [r[0] for r in reqs]
    err = 100.0 * sum(r[1] for r in reqs) / n
    return lat, err


def run(rng, hours, sigma, n_mean, fault=None, fault_windows=8, pre=5):
    """Sem `fault`: retorna detecções por regra em `hours` horas de tráfego saudável.
    Com `fault=(frac, extra_s)`: `hours` vira número de execuções (pre + fault_windows
    janelas cada) e retorna quantas execuções detectaram dentro da falha."""
    res = {r: 0 for r in RULES}
    runs = int(hours) if fault else 1
    total = pre + fault_windows if fault else int(hours * 60)
    stats = {"p95_v1": [], "err_max": 0.0}
    for _ in range(runs):
        dets = {r: SubsetDetector("sim", "heavy-reports", rule=r) for r in RULES}
        hit = {r: False for r in RULES}
        for t in range(total):
            n1 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
            n2 = max(30, int(rng.gauss(n_mean, n_mean * 0.15)))
            lat1, e1 = window(rng, n1, sigma)
            on = fault is not None and t >= pre
            lat2, e2 = window(rng, n2, sigma, *(fault if on else (0.0, 0.0)))
            p1, p2 = histogram_quantile(0.95, lat1), histogram_quantile(0.95, lat2)
            stats["p95_v1"].append(p1)
            stats["err_max"] = max(stats["err_max"], e1, e2)
            for r in RULES:
                w = Window(n=n2, err_pct=0.0 if r == "C" else e2, p95_ms=p2, baseline_p95_ms=p1,
                           mean_ms=sum(lat2) / n2, baseline_mean_ms=sum(lat1) / n1)
                if dets[r].observe(w) == "detected":
                    if fault:
                        hit[r] = hit[r] or on
                    else:
                        res[r] += 1
        if fault:
            for r in RULES:
                res[r] += hit[r]
    return res, stats


def pct(xs, q):
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=300)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sigmas", default="0,0.05,0.1,0.15,0.2")
    ap.add_argument("--n", type=int, default=80, help="requisições de heavy por versão por janela")
    ap.add_argument("--ratio", type=float, help="sobrescreve RELATIVE_RATIO_LIMIT (só na simulação)")
    ap.add_argument("--delta", type=float, help="sobrescreve RELATIVE_DELTA_MS (só na simulação)")
    args = ap.parse_args()
    import detector
    if args.ratio is not None:
        detector.RELATIVE_RATIO_LIMIT = args.ratio
    if args.delta is not None:
        detector.RELATIVE_DELTA_MS = args.delta
    print(f"# B/C: ratio={detector.RELATIVE_RATIO_LIMIT} delta={detector.RELATIVE_DELTA_MS} ms")
    rng = random.Random(args.seed)

    for sigma in [float(s) for s in args.sigmas.split(",")]:
        p_over = 0.0 if sigma == 0 else 0.5 * math.erfc(math.log((PER_TRY_S - OVERHEAD_S) / DELAY_S) / (sigma * math.sqrt(2)))
        fa, st = run(rng, args.hours, sigma, args.n)
        p = st["p95_v1"]
        line = (f"sigma={sigma:<5} P(tentativa>5s)={100*p_over:5.2f}% | p95 v1 por janela "
                f"p5/p50/p95={pct(p,.05):.0f}/{pct(p,.5):.0f}/{pct(p,.95):.0f} ms | "
                f"falso alarme/h ({args.hours:.0f} h): " +
                " ".join(f"{r}={fa[r]/args.hours:.3f}" for r in RULES))
        print(line)
        for frac, extra in ((0.2, 1.5), (0.1, 1.5), (0.1, 1.0), (0.05, 1.5)):
            det, st2 = run(rng, args.runs, sigma, args.n, fault=(frac, extra))
            print(f"    falha {int(frac*100)}% +{extra}s: detecção em {args.runs} execuções: " +
                  " ".join(f"{r}={det[r]}/{args.runs}" for r in RULES) +
                  f" | maior erro numa janela {st2['err_max']:.1f}%")


if __name__ == "__main__":
    main()
