"""Figuras dos posts da série gray failure em canary (versão 3 e posts derivados).

Uso (na raiz do lab): python3 scripts/make_figures.py data/figuras.json <pasta_assets_img>
Gera, para cada post, <pasta>/<slug>/<figura>-pt.svg e -en.svg e a capa cover-pt.png / cover-en.png.
"""
import json
import os
import statistics as st
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from estilo import *  # noqa: E402,F403
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

D = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
LANGS = ("pt", "en")


def path(slug, name, lang, ext="svg"):
    d = os.path.join(OUT, slug)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{name}-{lang}.{ext}")


def pct(x, lang):
    return num(100 * x, 0, lang) + "%"


# ------------------------------------------------------------------ v3 do post original

SLUG_V3 = "gray-failure-canary-istio"
MNAME = {"pt": {"feature:B": "regra B\n(p95)", "feature:BF": "regra BF\n(piso por feature)",
                "feature:D": "regra D\n(fração lenta)", "agg_b": "por versão\n(p99 agregado)",
                "flagger_rel": "estilo Flagger\n(emulado)"},
         "en": {"feature:B": "rule B\n(p95)", "feature:BF": "rule BF\n(per-feature floor)",
                "feature:D": "rule D\n(slow fraction)", "agg_b": "per version\n(aggregate p99)",
                "flagger_rel": "Flagger-style\n(emulated)"}}
SCEN = {"pt": {"dash10": "dashboard 10%", "dash20": "dashboard 20%", "heavy10": "heavy-reports 10%",
               "heavy20": "heavy-reports 20%"},
        "en": {"dash10": "dashboard 10%", "dash20": "dashboard 20%", "heavy10": "heavy-reports 10%",
               "heavy20": "heavy-reports 20%"}}
PRIMARY = {"dash10": "feature:D", "dash20": "feature:D", "heavy10": "feature:B", "heavy20": "feature:B"}


def fig_v5_methods(lang):
    T = {"pt": ("Cada feature precisa da sua regra; a visão por versão não vê o dashboard",
                "Execuções detectadas em 30, por cenário e método. Contorno grosso: regra escolhida antes dos dados",
                "execuções detectadas (de 30)"),
         "en": ("Each feature needs its own rule; the per-version view misses the dashboard",
                "Runs detected out of 30, per scenario and method. Thick outline: rule chosen before the data",
                "runs detected (out of 30)")}[lang]
    m = D["v5"]["methods"]
    scen = ["dash10", "dash20", "heavy10", "heavy20"]
    meths = ["feature:B", "feature:BF", "feature:D", "agg_b", "flagger_rel"]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.9))
    w = 0.15
    for i, s in enumerate(scen):
        for j, mm in enumerate(meths):
            h = m[s][mm][0]
            x = i + (j - 2) * w
            col = NEUTRO if mm in ("agg_b", "flagger_rel") else (FOCO if s.startswith("dash") else REF)
            ax.bar(x, h, w * 0.92, color=col, alpha=0.95 if h else 0.0,
                   edgecolor=ESCURO if PRIMARY[s] == mm else "none", linewidth=2.2 if PRIMARY[s] == mm else 0)
            ax.text(x, h + 0.6, str(h), ha="center", va="bottom", fontsize=9.5, color=ESCURO if h else ALARME,
                    fontweight="bold" if h == 0 else "normal")
    ax.set_xticks(range(4))
    ax.set_xticklabels([SCEN[lang][s] for s in scen])
    ax.set_ylim(0, 35)
    ax.set_ylabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    lab = " · ".join(f"{k+1}: {MNAME[lang][mm].replace(chr(10), ' ')}" for k, mm in enumerate(meths))
    for i in range(4):
        for j in range(5):
            ax.text(i + (j - 2) * w, -1.6, str(j + 1), ha="center", va="top", fontsize=8.5, color=TEXTO2)
    ax.tick_params(axis="x", pad=22)
    fig.text(0.01, -0.04, lab, fontsize=9, color=TEXTO2)
    salvar(fig, path(SLUG_V3, "v5-metodos", lang))


def fig_v5_ttd(lang):
    T = {"pt": ("Na maioria das execuções, o alarme sai no 3º minuto de falha",
                "Minutos até a detecção pela regra escolhida (3 janelas seguidas exigem pelo menos 3), 30 execuções por cenário",
                "minutos desde o início da falha"),
         "en": ("In most runs the alarm fires in the 3rd minute of the fault",
                "Minutes to detection by the chosen rule (3 consecutive windows need at least 3), 30 runs per scenario",
                "minutes since the fault started")}[lang]
    ttd = D["v5"]["ttd"]
    scen = ["dash10", "dash20", "heavy10", "heavy20"]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.9))
    for i, s in enumerate(scen):
        vals = sorted(ttd[s])
        cnt = {}
        for v in vals:
            cnt[v] = cnt.get(v, 0) + 1
        for v, c in cnt.items():
            ax.scatter([v], [i], s=40 + 14 * c, color=FOCO if s.startswith("dash") else REF, zorder=3)
            ax.text(v, i + 0.28, f"{c}", ha="center", va="bottom", fontsize=9.5, color=TEXTO2)
    ax.set_yticks(range(4))
    ax.set_yticklabels([SCEN[lang][s] for s in scen])
    ax.set_xlim(2, 9)
    ax.set_ylim(-0.6, 3.8)
    ax.set_xlabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    salvar(fig, path(SLUG_V3, "v5-ttd", lang))


# ------------------------------------------------------------------ Flagger real

SLUG_FL = "flagger-real-detector-por-feature"


def fig_fl_ambiente(lang):
    T = {"pt": dict(t="Um host, dois clusters, o mesmo laboratório duas vezes",
                    host="Host Proxmox", hd="2 VMs, um nó k0s em cada",
                    c="Cluster {}", cd="Kubernetes 1.36 (k0s) · Istio 1.31.1",
                    fl="Flagger 1.45.0", fld="decide promover ou reverter",
                    app="app-fl-primary  |  app-fl (canary)", appd="mesmo app, σ=0,1, 1 pod cada",
                    gen="gerador de carga", gend="2 pods × 8 workers, 50% com x-canary",
                    prom="Prometheus", promd="retenção 72 h, scrape 15 s",
                    run="runner + coletor", rund="fora do cluster, port-forward"),
         "en": dict(t="One host, two clusters, the same lab twice",
                    host="Proxmox host", hd="2 VMs, one k0s node each",
                    c="Cluster {}", cd="Kubernetes 1.36 (k0s) · Istio 1.31.1",
                    fl="Flagger 1.45.0", fld="decides promote or roll back",
                    app="app-fl-primary  |  app-fl (canary)", appd="same app, σ=0.1, 1 pod each",
                    gen="load generator", gend="2 pods × 8 workers, 50% with x-canary",
                    prom="Prometheus", promd="72 h retention, 15 s scrape",
                    run="runner + collector", rund="outside the cluster, port-forward")}[lang]
    fig, ax = tela(h=5.0)
    ax.text(0, 6.0, T["t"], fontsize=14, fontweight="bold", color=ESCURO)
    for k, x0 in enumerate((0.1, 5.1)):
        ax.add_patch(Rectangle((x0, 0.25), 4.7, 5.35, facecolor=FAIXA_REF, edgecolor="none"))
        ax.text(x0 + 0.15, 5.3, T["c"].format("ab"[k]), fontsize=12, fontweight="bold", color=ESCURO)
        ax.text(x0 + 0.15, 4.98, T["cd"], fontsize=9.5, color=TEXTO2)
        caixa(ax, x0 + 0.2, 3.65, 4.3, 1.0, T["fl"], T["fld"], cor=ALARME, tam=11)
        caixa(ax, x0 + 0.2, 2.45, 4.3, 1.0, T["app"], T["appd"], cor=FOCO, tam=10.5)
        caixa(ax, x0 + 0.2, 1.25, 2.05, 1.0, T["gen"], T["gend"].split(",")[0], cor=REF, tam=8.8)
        caixa(ax, x0 + 2.45, 1.25, 2.05, 1.0, T["prom"], T["promd"].split(",")[0], cor=NEUTRO, tam=8.8)
        ax.text(x0 + 0.2, 0.55, T["gend"].split(", ")[1], fontsize=9, color=TEXTO2)
    ax.text(0.1, -0.3, f'{T["host"]}: {T["hd"]}  ·  {T["run"]}: {T["rund"]}', fontsize=9.5, color=TEXTO2)
    salvar(fig, path(SLUG_FL, "ambiente", lang))


def fig_fl_grade(lang):
    T = {"pt": ("O Flagger promoveu as 30 versões com falha no dashboard",
                "Cada coluna é uma execução (15 por cluster). Cheio: detectou dentro da falha; vazio: não detectou",
                {"flagger": "Flagger real", "ours": "detector por feature", "agg_b": "por versão (emulado)",
                 "flagger_rel": "estilo Flagger (emulado)"}, "cluster a", "cluster b"),
         "en": ("Flagger promoted all 30 versions with the dashboard fault",
                "Each column is one run (15 per cluster). Filled: detected inside the fault; empty: not detected",
                {"flagger": "real Flagger", "ours": "per-feature detector", "agg_b": "per version (emulated)",
                 "flagger_rel": "Flagger-style (emulated)"}, "cluster a", "cluster b")}[lang]
    rows = D["flagger"]["rows"]
    keys = ["flagger", "ours", "agg_b", "flagger_rel"]
    fig, axes = plt.subplots(2, 1, figsize=(LARGURA, 5.6))
    for ax, s in zip(axes, ("dash10", "heavy10")):
        rs = sorted([r for r in rows if r["scenario"] == s], key=lambda r: (r["cluster"], r["rep"]))
        for j, r in enumerate(rs):
            for i, k in enumerate(keys):
                hit = r["flagger_hit"] if k == "flagger" else r[k]
                col = ALARME if k == "flagger" else (FOCO if k == "ours" else NEUTRO)
                ax.scatter([j], [-i], s=58, marker="s", color=col if hit else "white", edgecolor=col, linewidth=1.3)
        ax.axvline(14.5, color="#d1d5db", lw=1)
        ax.set_yticks([-i for i in range(4)])
        ax.set_yticklabels([T[2][k] for k in keys], fontsize=10)
        ax.set_xticks([7, 22])
        ax.set_xticklabels([T[3], T[4]], fontsize=10)
        ax.set_xlim(-1, 30)
        ax.set_ylim(-3.6, 0.6)
        ax.grid(False)
        tot = {k: sum(1 for r in rs if (r["flagger_hit"] if k == "flagger" else r[k])) for k in keys}
        for i, k in enumerate(keys):
            ax.text(30.3, -i, f"{tot[k]}/30", va="center", fontsize=10, color=ESCURO, fontweight="bold")
        ax.set_title(SCEN[lang][s], fontsize=12, pad=6)
    axes[0].text(0, 1.38, T[0], transform=axes[0].transAxes, fontsize=14, fontweight="bold", color=ESCURO)
    axes[0].text(0, 1.22, T[1], transform=axes[0].transAxes, fontsize=10.5, color=TEXTO2)
    fig.subplots_adjust(hspace=0.55)
    salvar(fig, path(SLUG_FL, "execucoes", lang))


def fig_fl_tempo(lang):
    T = {"pt": ("No heavy-reports, os dois agem, em escalas diferentes",
                "Minutos desde o início da falha (8 min de falha), heavy-reports 10%, 30 execuções",
                "minutos desde o início da falha", "detector por feature (3 janelas seguidas)",
                "Flagger: reversão (5 checagens falhas acumuladas)", "fim da falha", "não detectou: 2"),
         "en": ("On heavy-reports both act, on different time scales",
                "Minutes since the fault started (8-minute fault), heavy-reports 10%, 30 runs",
                "minutes since the fault started", "per-feature detector (3 consecutive windows)",
                "Flagger: rollback (5 accumulated failed checks)", "fault ends", "not detected: 2")}[lang]
    rs = [r for r in D["flagger"]["rows"] if r["scenario"] == "heavy10"]
    ours = [r["ours_min"] for r in rs if r["ours"]]
    fl = [r["flagger_min"] for r in rs if r["flagger_hit"]]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.6))
    ax.axvspan(0, 8, color=FAIXA, zorder=0)
    import random
    rnd = random.Random(3)
    ax.scatter(ours, [1 + rnd.uniform(-0.12, 0.12) for _ in ours], s=34, color=FOCO, zorder=3)
    ax.scatter(fl, [0 + rnd.uniform(-0.12, 0.12) for _ in fl], s=34, color=ALARME, marker="D", zorder=3)
    ax.text(0.15, 1.33, T[3] + f" · {len(ours)}/30 · " + ("mediana" if lang == "pt" else "median") + f" {num(st.median(ours), 0, lang)} min",
            fontsize=10, color=ESCURO)
    ax.text(0.15, 0.33, T[4] + f" · {len(fl)}/30 · " + ("mediana" if lang == "pt" else "median") + f" {num(st.median(fl), 1, lang)} min",
            fontsize=10, color=ESCURO)
    ax.axvline(8, color=ALARME, ls="--", lw=1)
    ax.text(8.1, -0.45, T[5], fontsize=9.5, color=ALARME)
    ax.text(9.0, 1.0, T[6], fontsize=9.5, color=TEXTO2, va="center")
    ax.set_yticks([])
    ax.set_xlim(0, 10.5)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    if lang == "pt":
        virgula(ax)
    salvar(fig, path(SLUG_FL, "tempo", lang))


def fig_fl_viu(lang):
    """Uma execução real de dash10: o que o detector por feature viu e o que a análise por versão viu."""
    T = {"pt": dict(t="Mesma execução, dois olhares: um vê a falha, o outro não",
                    s="Uma execução real do dashboard 10% (cluster a). Cada ponto é um minuto",
                    top="Meu detector: % do dashboard acima de 250 ms", v1="v1 (atual)", v2="v2 (canary)",
                    det="alarme no 3º minuto", bot="Versão inteira, a conta da análise do Flagger: p99 canary ÷ p99 primary", lim="limite 1,15",
                    prom="nunca passa do limite; o Flagger promoveu a versão", x="minutos desde o início da falha",
                    falha="falha ligada (10% do dashboard +0,5 s)"),
         "en": dict(t="Same run, two views: one sees the fault, the other does not",
                    s="One real dashboard 10% run (cluster a). Each dot is one minute",
                    top="My detector: % of dashboard above 250 ms", v1="v1 (current)", v2="v2 (canary)",
                    det="alarm in minute 3", bot="Whole version, the math of Flagger's analysis: canary p99 ÷ primary p99", lim="1.15 limit",
                    prom="never crosses the limit; Flagger promoted the version", x="minutes since the fault started",
                    falha="fault on (10% of dashboard +0.5 s)")}[lang]
    S = D["showcase"]
    rows = S["rows"]
    xs = [r["t"] - 0.5 for r in rows]  # rótulo m cobre [m-1, m): ponto no meio da janela
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(LARGURA, 5.6), sharex=True, gridspec_kw={"hspace": 0.35})
    for ax in (a1, a2):
        ax.axvspan(0, S["fault_min"], color=FAIXA, zorder=0)
    a1.plot(xs, [100 * r["frac_v1"] for r in rows], color=REF, marker="o", lw=2, ms=5, label=T["v1"])
    a1.plot(xs, [100 * r["frac_v2"] for r in rows], color=FOCO, marker="o", lw=2.4, ms=6, label=T["v2"])
    dx = S["ours_label_min"] - 0.5
    dy = 100 * next(r["frac_v2"] for r in rows if r["t"] == S["ours_label_min"])
    a1.annotate(T["det"], xy=(dx, dy), xytext=(dx - 1.2, dy + 8), fontsize=10.5, color=ESCURO, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=ESCURO))
    a1.scatter([dx], [dy], s=140, facecolor="none", edgecolor=ALARME, linewidth=2, zorder=4)
    a1.set_ylim(-1, 20)
    a1.set_ylabel("%")
    a1.text(0.0, 1.04, T["top"], transform=a1.transAxes, fontsize=11.5, fontweight="bold", color=ESCURO)
    a1.text(8.7, 1.2, T["v1"], fontsize=10.5, color=REF, fontweight="bold")
    a1.text(5.0, 16.3, T["v2"], fontsize=10.5, color=FOCO, fontweight="bold")
    a1.text(0.15, 18.3, T["falha"], fontsize=9.5, color=TEXTO2)
    a2.plot(xs, [r["p99_ratio"] for r in rows], color=NEUTRO, marker="o", lw=2, ms=5)
    a2.axhline(1.15, color=ALARME, ls="--", lw=1.5)
    a2.text(8.6, 1.165, T["lim"], fontsize=10, color=ALARME)
    a2.text(1.0, 0.86, T["prom"], fontsize=10.5, color=ESCURO, fontweight="bold")
    a2.set_ylim(0.8, 1.25)
    a2.text(0.0, 1.04, T["bot"], transform=a2.transAxes, fontsize=11.5, fontweight="bold", color=ESCURO)
    a2.set_xlabel(T["x"])
    a2.set_xlim(-3.7, 11.2)
    fig.text(0.125, 1.0, T["t"], fontsize=14, fontweight="bold", color=ESCURO, va="bottom")
    fig.text(0.125, 0.965, T["s"], fontsize=11, color=TEXTO2, va="bottom")
    if lang == "pt":
        virgula(a1, a2, y=True)
    salvar(fig, path(SLUG_FL, "o-que-cada-um-viu", lang))


def grade(ax, x0, y0, hits, n=30, cols=6, size=0.36, gap=0.1, cor=REF, vazio="#5B6B82"):
    """30 quadrados (5 linhas × 6 colunas): cheios = detectou."""
    for i in range(n):
        r, c = divmod(i, cols)
        x, y = x0 + c * (size + gap), y0 - r * (size + gap)
        hit = i < hits
        ax.add_patch(Rectangle((x, y), size, size, facecolor=cor if hit else "none",
                               edgecolor=cor if hit else vazio, linewidth=1.6))


def capa_flagger(lang):
    """Capa horizontal 1200x627 (prévia do link e imagem do post no LinkedIn), com o mesmo conteúdo do cartão vertical."""
    T = {"pt": dict(t="Uma falha em uma só função do app\npassou pelo Flagger em 30 de 30 versões",
                    sub="10% das requisições da tela rápida com +0,5 s, só na versão nova",
                    fl="Flagger", fls="métricas da versão inteira", me_="Meu detector", mes="métricas por função",
                    cap="detectou a falha em",
                    l1="Lentidão no relatório lento: Flagger 30/30 · meu 28/30",
                    l2="Sem falha: 0 alarmes falsos nos dois (30 execuções)",
                    note="Laboratório, não produção · métrica por função no Flagger não testada"),
         "en": dict(t="A fault in just one function of the app\ngot past Flagger in 30 of 30 versions",
                    sub="10% of the fast screen's requests with +0.5 s, only in the new version",
                    fl="Flagger", fls="whole-version metrics", me_="My detector", mes="per-function metrics",
                    cap="detected the fault in",
                    l1="Slowdown on the slow report: Flagger 30/30 · mine 28/30",
                    l2="No fault: 0 false alarms for both (30 runs)",
                    note="A lab, not production · per-function metric in Flagger not tested")}[lang]
    fl = D["flagger"]["scenarios"]
    fig = plt.figure(figsize=(12, 6.27), dpi=100)
    fig.patch.set_facecolor(ESCURO)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 12); ax.set_ylim(0, 6.27); ax.axis("off")
    ax.text(0.5, 5.85, T["t"], color="white", fontsize=27, fontweight="bold", va="top", linespacing=1.18)
    ax.text(0.5, 4.72, T["sub"], color="#C9D3E0", fontsize=14.5)
    for x0, name, sub, hits, cor, numcor in ((0.5, T["fl"], T["fls"], fl["dash10"]["flagger"][0], NEUTRO, "#FF8A8D"),
                                             (6.3, T["me_"], T["mes"], fl["dash10"]["ours"][0], FOCO, FOCO)):
        ax.add_patch(Rectangle((x0 - 0.2, 1.45), 5.3, 3.0, facecolor="#16263D", edgecolor="none"))
        ax.text(x0, 4.1, name, color="white", fontsize=19, fontweight="bold")
        ax.text(x0, 3.75, sub, color="#C9D3E0", fontsize=11.5)
        ax.text(x0, 3.4, T["cap"], color="#8FA3BF", fontsize=11)
        ax.text(x0, 2.05, f"{hits}/30", color=numcor, fontsize=54, fontweight="bold")
        grade(ax, x0 + 2.8, 4.0, hits, cor=cor, size=0.30, gap=0.08, cols=6)
    ax.text(0.5, 1.0, T["l1"], color="white", fontsize=13.5)
    ax.text(0.5, 0.62, T["l2"], color="white", fontsize=13.5)
    ax.text(0.5, 0.2, "mariomenezes.github.io  ·  " + T["note"], color="#8FA3BF", fontsize=10.5)
    with plt.rc_context({"savefig.bbox": None}):
        fig.savefig(path(SLUG_FL, "cover", lang, "png"), dpi=100, facecolor=ESCURO)
    plt.close(fig)


# ------------------------------------------------------------------ pré-registro

SLUG_PR = "pre-registro-experimento-kubernetes"


def fig_pr_linha(lang):
    T = {"pt": ("Cada versão foi gravada antes dos dados a que se refere",
                "Commits que alteraram o pré-registro (●) e que gravaram dados de cluster (■)",
                {"v1": "v1–v2: limiar e controle", "v3": "v3: contagem do controle", "v4": "v4: regras D/BF, seleção, portão", "v5": "v5: critério H1, comparação",
                 "r5": "dados v5", "v6": "v6: Flagger real", "r6": "dados v6"}),
         "en": ("Each version was committed before the data it refers to",
                "Commits that changed the pre-registration (●) and that stored cluster data (■)",
                {"v1": "v1–v2: threshold and control", "v3": "v3: control counting", "v4": "v4: rules D/BF, selection, gate", "v5": "v5: H1 criterion, comparison",
                 "r5": "v5 data", "v6": "v6: real Flagger", "r6": "v6 data"})}[lang]
    ev = D["linha-do-tempo"]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.4))
    for e in ev:
        d = datetime.fromisoformat(e["date"])
        if e["kind"] == "dados":
            ax.scatter([d], [0], marker="s", s=70, color=FOCO, zorder=3)
        elif e["kind"] == "prereg":
            ax.scatter([d], [1], marker="o", s=55, color=REF, zorder=3)
    marks = [("2026-10-29T09:35:00-03:00", 1, "v1", (30, 16)), ("2026-11-04T14:22:00-03:00", 1, "v3", (-20, -30)),
             ("2026-11-05T16:19:00-03:00", 1, "v4", (-70, 22)), ("2026-11-05T17:22:00-03:00", 1, "v5", (-20, 44)),
             ("2026-11-07T21:55:00-03:00", 1, "v6", (10, 22)), ("2026-11-07T19:30:00-03:00", 0, "r5", (-30, -26)),
             ("2026-11-08T12:02:00-03:00", 0, "r6", (12, -26))]
    for dt, y, k, (dx, dy) in marks:
        d = datetime.fromisoformat(dt)
        ax.annotate(T[2][k], xy=(d, y), xytext=(dx, dy), textcoords="offset points",
                    ha="center", fontsize=9, color=TEXTO2, arrowprops=dict(arrowstyle="-", color="#c7ccd4", lw=0.8))
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["dados" if lang == "pt" else "data", "pré-registro" if lang == "pt" else "pre-registration"])
    ax.set_ylim(-0.9, 2.1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m" if lang == "pt" else "%b %d"))
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    salvar(fig, path(SLUG_PR, "linha-do-tempo", lang))


def fig_pr_previsto(lang):
    from calib_lib_min import cp_lower, cp_upper
    T = {"pt": ("O que foi previsto antes, e o que saiu",
                "Taxa observada com intervalo unicaudal de 95%; linha vermelha: critério gravado antes dos dados",
                "taxa"),
         "en": ("What was predicted before, and what came out",
                "Observed rate with a one-sided 95% interval; red line: criterion committed before the data",
                "rate")}[lang]
    v5, fl = D["v5"], D["flagger"]
    items = [
        ("H1 dash10 (D)", 30, 30, "lo", 0.80, "≥"),
        ("H1 heavy10 (B)", 30, 30, "lo", 0.80, "≥"),
        ("H6a Flagger, dash10", fl["scenarios"]["dash10"]["flagger"][0], 30, "up", 0.20, "<"),
        ("H6b Flagger, heavy10", fl["scenarios"]["heavy10"]["flagger"][0], 30, "lo", 0.80, "≥"),
        ("H8 emulação = real, dash10" if lang == "pt" else "H8 emulation = real, dash10",
         fl["scenarios"]["dash10"]["agreement"][0], 30, "lo", 0.80, "≥"),
        ("H8 emulação = real, heavy10" if lang == "pt" else "H8 emulation = real, heavy10",
         fl["scenarios"]["heavy10"]["agreement"][0], 30, "lo", 0.80, "≥"),
    ]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.0))
    for i, (lab, k, n, side, thr, op) in enumerate(items):
        y = -i
        r = k / n
        if side == "lo":
            lo, hi = cp_lower(k, n), 1.0
        else:
            lo, hi = 0.0, cp_upper(k, n)
        ax.plot([lo, hi], [y, y], color=REF, lw=3, solid_capstyle="butt")
        ax.scatter([r], [y], color=ESCURO, s=36, zorder=3)
        ax.plot([thr, thr], [y - 0.32, y + 0.32], color=ALARME, lw=2)
        ax.text(1.03, y, f"{k}/{n}", va="center", fontsize=10)
    ax.set_yticks([-i for i in range(len(items))])
    ax.set_yticklabels([x[0] for x in items], fontsize=10)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    if lang == "pt":
        virgula(ax)
    salvar(fig, path(SLUG_PR, "previsto-observado", lang))


# ------------------------------------------------------------------ 29 de 29

SLUG_29 = "criterio-29-de-29"


def fig_29_poder(lang):
    T = {"pt": ("O critério antigo reprovaria um detector bom em metade das vezes",
                "Chance de aprovar H1 contra a taxa real de detecção",
                "taxa real de detecção", "chance de aprovar",
                "v4: 29 execuções, LI ≥ 0,90 (só 29/29 passa)", "v5: 30 execuções, LI ≥ 0,80 (até 2 falhas)",
                "taxa simulada 97,5%"),
         "en": ("The old criterion would fail a good detector about half the time",
                "Chance of passing H1 against the true detection rate",
                "true detection rate", "chance of passing",
                "v4: 29 runs, LB ≥ 0.90 (only 29/29 passes)", "v5: 30 runs, LB ≥ 0.80 (up to 2 misses)",
                "simulated rate 97.5%")}[lang]
    P = D["power"]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.3))
    for k, col, ls, lab in (("v4", ANTIGO, "--", T[4]), ("v5", REF, "-", T[5])):
        xs, ys = zip(*P[k]["curve"])
        ax.plot(xs, ys, color=col if k == "v5" else NEUTRO, ls=ls, lw=2.2, label=lab)
    ax.axvline(0.975, color=FOCO, lw=1.2)
    ax.text(0.97, 0.03, T[6], ha="right", fontsize=9.5, color=FOCO, bbox=dict(facecolor="white", edgecolor="none", pad=1))
    for k, dy in (("v4", -0.09), ("v5", 0.05)):
        y = P[k]["at_0975"]
        ax.scatter([0.975], [y], color=ESCURO, zorder=4, s=30)
        ax.text(0.95, y + dy, pct(y, lang), ha="right", fontsize=11, fontweight="bold", color=ESCURO)
    ax.set_xlim(0.6, 1.0)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(T[2])
    ax.set_ylabel(T[3])
    ax.legend(loc="upper left")
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    if lang == "pt":
        virgula(ax, y=True)
    salvar(fig, path(SLUG_29, "poder", lang))


def fig_29_n(lang):
    T = {"pt": ("Mantendo LI ≥ 0,90, seriam precisas ~70 execuções por cenário",
                "Chance de aprovar com taxa real de 97,5%, por número de execuções (limite inferior ≥ 0,90)",
                "execuções por cenário", "chance de aprovar", "falhas toleradas"),
         "en": ("Keeping LB ≥ 0.90 would take ~70 runs per scenario",
                "Chance of passing at a 97.5% true rate, by number of runs (lower bound ≥ 0.90)",
                "runs per scenario", "chance of passing", "misses allowed")}[lang]
    pts = D["power"]["power_n"]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.8))
    ns, ks, ps = zip(*pts)
    ax.plot(ns, ps, color=REF, marker="o", lw=1.6)
    for n, k, p in pts:
        ax.text(n, p + 0.03, f"{k}", ha="center", fontsize=9.5, color=TEXTO2)
    ax.axhline(0.8, color=ALARME, ls="--", lw=1)
    ax.text(29, 0.82, "80%", fontsize=9.5, color=ALARME)
    ax.text(0.99, 0.04, T[4] + " (" + ("número sobre cada ponto" if lang == "pt" else "number above each point") + ")",
            transform=ax.transAxes, ha="right", fontsize=9.5, color=TEXTO2)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel(T[2])
    ax.set_ylabel(T[3])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    if lang == "pt":
        virgula(ax, y=True)
    salvar(fig, path(SLUG_29, "execucoes-necessarias", lang))


# ------------------------------------------------------------------ portão do simulador

SLUG_SIM = "simulador-decisao-nivel"
GNAME = {"pt": {"ratio_q50": "razão v2/v1, mediana", "ratio_q99": "razão v2/v1, q99", "b115_control_alarms": "alarmes no controle",
                "b115_f20": "detecções B 1,15× (20%)", "b115_f10": "detecções B 1,15× (10%)",
                "b130_f20": "detecções B 1,30× (20%)", "b130_f10": "detecções B 1,30× (10%)",
                "p95_v1_med": "p95 da v1, mediana (nível)", "mean_v1_med": "média da v1, mediana (nível)"},
         "en": {"ratio_q50": "v2/v1 ratio, median", "ratio_q99": "v2/v1 ratio, q99", "b115_control_alarms": "control alarms",
                "b115_f20": "detections B 1.15× (20%)", "b115_f10": "detections B 1.15× (10%)",
                "b130_f20": "detections B 1.30× (20%)", "b130_f10": "detections B 1.30× (10%)",
                "p95_v1_med": "v1 p95, median (level)", "mean_v1_med": "v1 mean, median (level)"}}


def fig_sim_portao(lang):
    T = {"pt": ("O simulador acertou todas as decisões e errou o nível",
                "Intervalo central de 95% de 200 campanhas simuladas (barra) e valor medido no cluster (ponto), σ=0,1",
                "posição dentro do intervalo previsto (0 = mínimo, 1 = máximo)", "dentro", "fora"),
         "en": ("The simulator got every decision right and the level wrong",
                "Central 95% interval of 200 simulated campaigns (bar) and the value measured in the cluster (dot), σ=0.1",
                "position inside the predicted interval (0 = low, 1 = high)", "inside", "outside")}[lang]
    M = D["gate"]["metrics"]
    order = ["ratio_q50", "ratio_q99", "b115_control_alarms", "b115_f20", "b115_f10", "b130_f20", "b130_f10",
             "p95_v1_med", "mean_v1_med"]
    fig, ax = plt.subplots(figsize=(LARGURA, 5.0))
    for i, m in enumerate(order):
        for c, dy, mk in (("a", 0.15, "o"), ("b", -0.15, "s")):
            r = M[f"{c}/{m}"]
            lo, hi, v = r["lo"], r["hi"], r["measured"]
            pos = 0.5 if hi == lo else (v - lo) / (hi - lo)
            pos_c = max(-0.6, min(1.6, pos))
            y = -i + dy
            ax.plot([0, 1], [y, y], color=FAIXA_REF if r["ok"] else "#f3d1d2", lw=7, solid_capstyle="butt", zorder=1)
            ax.scatter([pos_c], [y], marker=mk, s=40, color=REF if r["ok"] else ALARME, zorder=3)
            if not r["ok"]:
                ax.text(pos_c - 0.05, y, f"{c}: {num(v, 0, lang)} vs [{num(lo, 0, lang)}–{num(hi, 0, lang)}]",
                        ha="right", va="center", fontsize=8.8, color=ALARME)
    ax.axvline(0, color="#d1d5db", lw=1)
    ax.axvline(1, color="#d1d5db", lw=1)
    ax.set_yticks([-i for i in range(len(order))])
    ax.set_yticklabels([GNAME[lang][m] for m in order], fontsize=9.8)
    ax.set_xlim(-1.8, 1.7)
    ax.set_xticks([0, 0.5, 1])
    ax.set_xlabel(T[2])
    ax.text(1.05, 0.5, "● a   ■ b", transform=ax.transAxes, fontsize=10, color=TEXTO2)
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    if lang == "pt":
        virgula(ax)
    salvar(fig, path(SLUG_SIM, "portao", lang))


def fig_sim_selecao(lang):
    T = {"pt": ("Em σ=0,3, só a regra D fica abaixo do alvo de alarme falso no heavy-reports",
                "Calibração (simulação, 72 h por célula): alarme falso UB95 por cluster-hora e detecção em 10%,\npior cluster. Vermelho: inelegível (UB95 ≥ 0,1)",
                "regra escolhida"),
         "en": ("At σ=0.3 only rule D stays under the false-alarm target on heavy-reports",
                "Calibration (simulation, 72 h per cell): false-alarm UB95 per cluster-hour and detection at 10%,\nworst cluster. Red: ineligible (UB95 ≥ 0.1)",
                "chosen rule")}[lang]
    C = D["gate"]["calibration"]
    F = D["gate"]["final"]
    rows = [("heavy-reports", "0.1"), ("heavy-reports", "0.3"), ("dashboard", "0.1"), ("dashboard", "0.3")]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.4))
    for i, (feat, sg) in enumerate(rows):
        for j, n in enumerate(("B", "BF", "D")):
            cells = [C[f"{feat}|{c}|{sg}"][n] for c in "ab"]
            fa = max(x["fa_ub95"] for x in cells)
            det = min(x["f10"] for x in cells)
            bad = fa >= 0.1
            chosen = F[f"{feat}|{sg}"]["rule"] == n
            ax.add_patch(Rectangle((j, -i - 0.45), 0.94, 0.9, facecolor="#f3d1d2" if bad else FAIXA_REF,
                                   edgecolor=ESCURO if chosen else "none", linewidth=2.2))
            ax.text(j + 0.47, -i + 0.1, f"{num(fa, 2, lang)}/h", ha="center", va="center", fontsize=10.5,
                    color=ALARME if bad else ESCURO, fontweight="bold")
            ax.text(j + 0.47, -i - 0.22, pct(det, lang), ha="center", va="center", fontsize=10, color=TEXTO2)
    ax.set_xlim(-0.05, 3)
    ax.set_ylim(-3.6, 0.6)
    ax.set_xticks([0.47, 1.47, 2.47])
    ax.set_xticklabels(["B", "BF", "D"])
    ax.xaxis.tick_top()
    ax.set_yticks([0, -1, -2, -3])
    ax.set_yticklabels([f"{f} · σ={sg.replace('.', ',') if lang == 'pt' else sg}" for f, sg in rows], fontsize=10)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("")
    fig.subplots_adjust(top=0.72)
    fig.text(0.02, 0.97, T[0], fontsize=14, fontweight="bold", color=ESCURO, va="top")
    fig.text(0.02, 0.89, T[1], fontsize=10, color=TEXTO2, va="top")
    ax.text(1.0, -0.06, ("contorno: " if lang == "pt" else "outline: ") + T[2] + (" (depois do portão)" if lang == "pt" else " (after the gate)"),
            transform=ax.transAxes, ha="right", fontsize=9, color=TEXTO2)
    salvar(fig, path(SLUG_SIM, "selecao", lang))


# ------------------------------------------------------------------ endpoint fantasma

SLUG_EP = "istio-multicluster-endpoint-fantasma"


def fig_ep_p95(lang):
    T = {"pt": ("Um serviço de 1 ms com p95 de 9 a 25 s",
                "p95 do dashboard por minuto, antes de ligar a falha, nos dois pilotos (escala log)",
                "p95 por minuto (ms, escala log)", "caminho quebrado", "depois do clusterLocal"),
         "en": ("A 1 ms service with a 9 to 25 s p95",
                "Dashboard p95 per minute, before the fault was turned on, in both pilots (log scale)",
                "p95 per minute (ms, log scale)", "broken path", "after clusterLocal")}[lang]
    P = D["path"]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.7))
    import random
    rnd = random.Random(1)
    for i, (k, lab, col) in enumerate((("pilot-flagger-caminho-quebrado", T[3], ALARME),
                                       ("pilot-flagger-caminho-ok", T[4], REF))):
        vals = P[k]["v1"] + P[k]["v2"]
        ax.scatter(vals, [i + rnd.uniform(-0.15, 0.15) for _ in vals], s=30, color=col, alpha=0.85, zorder=3)
        ax.text(1.5 if i == 1 else 600, i + 0.3, f"{lab}: " + ("mediana" if lang == "pt" else "median")
                + f" {num(st.median(vals), 1 if st.median(vals) < 10 else 0, lang)} ms", fontsize=10, color=ESCURO)
    ax.set_xscale("log")
    ax.set_yticks([])
    ax.set_ylim(-0.6, 1.7)
    ax.set_xlim(0.5, 40000)
    ax.set_xlabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    salvar(fig, path(SLUG_EP, "p95-caminho", lang))


def fig_ep_req(lang):
    T = {"pt": ("Só o caminho pelo Service ficava lento; sem carga, exatamente 10 s",
                "Tempo de requisições individuais ao dashboard (ms, escala log); cada ponto é uma requisição",
                "tempo da requisição (ms, escala log)", "timeout de conexão: 10 s"),
         "en": ("Only the path through the Service was slow; with no load, exactly 10 s",
                "Individual dashboard request times (ms, log scale); each dot is one request",
                "request time (ms, log scale)", "connect timeout: 10 s")}[lang]
    M = D["caminho-medicoes"]
    rows = [
        ("antes", "dentro_do_conteiner_127_0_0_1", {"pt": "dentro do contêiner", "en": "inside the container"}),
        ("antes", "gerador_para_ip_do_pod", {"pt": "direto no IP do pod", "en": "straight to the pod IP"}),
        ("antes", "pod_de_teste_sem_carga_para_app_service_do_lab", {"pt": "Service do lab antigo", "en": "old lab Service"}),
        ("antes", "pod_de_teste_sem_carga_para_service_primary", {"pt": "Service do Flagger, sem carga", "en": "Flagger Service, no load"}),
        ("antes", "gerador_para_service_primary", {"pt": "Service do Flagger, com carga", "en": "Flagger Service, with load"}),
        ("depois", "pod_de_teste_sem_carga_para_service_primary", {"pt": "depois: Service do Flagger", "en": "after: Flagger Service"}),
        ("depois", "gerador_para_service_app_fl_cluster_b", {"pt": "depois: cluster b", "en": "after: cluster b"}),
    ]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.4))
    for i, (when, k, lab) in enumerate(rows):
        vals = [max(v, 0.5) for v in M[when][k]]
        slow = when == "antes" and "service" in k and "lab" not in k
        ax.scatter(vals, [-i] * len(vals), s=34, color=ALARME if slow else REF, zorder=3, alpha=0.85)
    ax.axvline(10000, color=ALARME, ls="--", lw=1)
    ax.text(10500, 0.3, T[3], fontsize=9.5, color=ALARME)
    ax.set_xscale("log")
    ax.set_yticks([-i for i in range(len(rows))])
    ax.set_yticklabels([r[2][lang] for r in rows], fontsize=10)
    ax.set_xlim(0.4, 60000)
    ax.set_xlabel(T[2])
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    salvar(fig, path(SLUG_EP, "requisicoes", lang))


# ------------------------------------------------------------------ mutação

SLUG_MUT = "teste-de-mutacao-experimento"


def fig_mut(lang):
    T = {"pt": ("206 de 210 mutantes mortos; os 4 vivos eram equivalentes",
                "Mutantes por commit (o que os testes pegaram e o que sobreviveu), na ordem dos commits",
                "mutantes", "mortos", "vivos (equivalentes)"),
         "en": ("206 of 210 mutants killed; the 4 survivors were equivalent",
                "Mutants per commit (what the tests caught and what survived), in commit order",
                "mutants", "killed", "alive (equivalent)")}[lang]
    M = list(reversed(D["mutacao"]))
    fig, ax = plt.subplots(figsize=(LARGURA, 3.9))
    for i, m in enumerate(M):
        k = sum(a for a, b in m["pairs"])
        t = sum(b for a, b in m["pairs"])
        ax.bar(i, k, color=REF, width=0.75)
        if t > k:
            ax.bar(i, t - k, bottom=k, color=FOCO, width=0.75)
    ax.set_xticks(range(len(M)))
    ax.set_xticklabels([m["commit"][:7] for m in M], rotation=70, fontsize=8)
    ax.set_ylabel(T[2])
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=REF, label=T[3]), Patch(color=FOCO, label=T[4])], loc="upper left")
    ax.set_title(T[0])
    subtitulo(ax, T[1])
    salvar(fig, path(SLUG_MUT, "mutantes", lang))


# ------------------------------------------------------------------ capas

def capas():
    def mini_bars(vals, cols, labels=None, labels_en=None):
        def f(ax, lang="pt"):
            labs = labels_en if (lang == "en" and labels_en) else labels
            ax.bar(range(len(vals)), vals, color=cols, width=0.6)
            ax.set_yticks([])
            if labs:
                ax.set_xticks(range(len(vals)))
                ax.set_xticklabels(labs, fontsize=10, color="#C9D3E0")
            else:
                ax.set_xticks([])
        return f

    fl = D["flagger"]["scenarios"]
    C = {
        SLUG_FL: ({"pt": ("Flagger real contra\ndetector por feature", "dashboard com falha: 0 de 30 contra 30 de 30"),
                   "en": ("Real Flagger vs a\nper-feature detector", "dashboard fault: 0 of 30 vs 30 of 30")},
                  mini_bars([fl["dash10"]["flagger"][0] + 0.4, fl["dash10"]["ours"][0], fl["heavy10"]["flagger"][0],
                             fl["heavy10"]["ours"][0]], [ALARME, FOCO, ALARME, FOCO],
                            ["Flagger", "feature", "Flagger", "feature"])),
        SLUG_PR: ({"pt": ("Critérios antes\ndos dados", "pré-registro num laboratório de Kubernetes"),
                   "en": ("Criteria before\nthe data", "pre-registration in a Kubernetes lab")},
                  mini_bars([1, 1, 1, 1, 1, 1], [REF, REF, FOCO, REF, REF, FOCO])),
        SLUG_29: ({"pt": ("O critério de\n29 de 29", "48% de chance de reprovar um detector bom"),
                   "en": ("The 29 out of 29\ncriterion", "a 48% chance of failing a good detector")},
                  mini_bars([D["power"]["v4"]["at_0975"], D["power"]["v5"]["at_0975"]], [NEUTRO, REF], ["v4 48%", "v5 96%"])),
        SLUG_SIM: ({"pt": ("Acerta a decisão,\nerra o nível", "portão de validade de um simulador"),
                    "en": ("Right decision,\nwrong level", "a validity gate for a simulator")},
                   mini_bars([1, 1, 1, 1, 1, 1, 1, 0.3, 0.3], [REF] * 7 + [ALARME] * 2)),
        SLUG_EP: ({"pt": ("O endpoint que só\nexiste no outro cluster", "Istio multicluster com faixas de IP sobrepostas"),
                   "en": ("The endpoint that only\nexists in the other cluster", "Istio multicluster with overlapping pod IPs")},
                  mini_bars([9.6, 0.5], [ALARME, REF], ["9,6 s", "4,5 ms"], ["9.6 s", "4.5 ms"])),
        SLUG_MUT: ({"pt": ("Testes que testam\nos testes", "mutação num experimento de infraestrutura"),
                    "en": ("Tests that test\nthe tests", "mutation testing in an infrastructure experiment")},
                   mini_bars([206, 4], [REF, FOCO], ["206", "4"])),
    }
    for slug, (txt, draw) in C.items():
        for lang in LANGS:
            capa(path(slug, "cover", lang, "png"), txt[lang][0], txt[lang][1], lambda ax, d=draw, lg=lang: d(ax, lg))


def main():
    for lang in LANGS:
        fig_v5_methods(lang)
        fig_v5_ttd(lang)
        fig_fl_ambiente(lang)
        fig_fl_grade(lang)
        fig_fl_tempo(lang)
        fig_fl_viu(lang)
        fig_pr_linha(lang)
        fig_pr_previsto(lang)
        fig_29_poder(lang)
        fig_29_n(lang)
        fig_sim_portao(lang)
        fig_sim_selecao(lang)
        fig_ep_p95(lang)
        fig_ep_req(lang)
        fig_mut(lang)
    capas()
    for lang in LANGS:  # depois de capas(): substitui a capa genérica; esta capa horizontal serve também de imagem no LinkedIn
        capa_flagger(lang)
    print("figuras geradas em", OUT)


if __name__ == "__main__":
    main()
