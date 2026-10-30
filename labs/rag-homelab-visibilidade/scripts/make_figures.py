"""Figuras do post sobre RAG no homelab, a partir dos dados em ../data.

Uso (container com matplotlib):
  python3 make_figures.py <dir de dados> <dir de saida>

Gera, para pt e en: indice (crescimento + composicao), scores (antes/depois),
latencia (30 repeticoes) e capa 1200x627.
"""
import csv, json, os, sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

DATA, OUT = sys.argv[1], sys.argv[2]
PNG = len(sys.argv) > 3 and sys.argv[3] == "png"

BLUE, ORANGE, GREY, RED, OLD = "#4C72B0", "#DD8452", "#8C8C8C", "#C44E52", "#B0B0B0"
ORANGE_L = "#F0B490"
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 13, "figure.dpi": 100, "svg.fonttype": "none"})

T = {
 "pt": dict(dec=",", t_index="Trechos no índice a cada execução do indexador", x_time="horário (UTC, 29–30 out)", y_chunks="trechos no índice",
            ann="1 execução: 42 arquivos alterados,\n 6 → 50 arquivos, 64 → 971 trechos (48 s)", comp="Origem dos 972 trechos", fix="82 trechos: dados/ e rascunhos\nexcluídos do indexador",
            c_notes="notas reais", c_other="outros dados do benchmark", c_pacote="um arquivo (pacote de avaliação)",
            t_scores="Sem dados/ no índice, as perguntas fora do tema caem abaixo das demais", x_score="score do 1º resultado (cosseno)",
            before="antes (índice de 972 trechos)", after_ok="depois (82 trechos): arquivo esperado em 1º", after_bad="depois (82 trechos): esperado fora do 1º", after_off="depois (82 trechos): fora do tema",
            band="faixa das perguntas com arquivo-alvo (depois): {lo}–{hi}",
            t_lat="Latência de uma consulta (índice de 972 trechos): 30 repetições, 0 erros", x_lat="milissegundos", embed="embedding da pergunta", busca="busca no Qdrant", total="total",
            p50="mediana", p95="p95", cover1="RAG no homelab com visibilidade", cover2="o corpus contaminado, não o score, era o problema"),
 "en": dict(dec=".", t_index="Chunks in the index at each indexer run", x_time="time (UTC, Oct 29–30)", y_chunks="chunks in the index",
            ann="1 run: 42 files changed,\n 6 → 50 files, 64 → 971 chunks (48 s)", comp="Origin of the 972 chunks", fix="82 chunks: dados/ and drafts\nexcluded from the indexer",
            c_notes="actual notes", c_other="other benchmark data", c_pacote="one file (evaluation pack)",
            t_scores="Without dados/ in the index, off-topic questions fall below the rest", x_score="top-1 score (cosine)",
            before="before (972-chunk index)", after_ok="after (82 chunks): expected file ranked 1st", after_bad="after (82 chunks): expected not 1st", after_off="after (82 chunks): off-topic",
            band="range of questions with a target file (after): {lo}–{hi}",
            t_lat="Query latency (972-chunk index): 30 repetitions, 0 errors", x_lat="milliseconds", embed="question embedding", busca="Qdrant search", total="total",
            p50="median", p95="p95", cover1="RAG in a homelab with visibility", cover2="the polluted corpus, not the score, was the problem"),
}
LAB = {
 "como reinicio o roteador": ("como reinicio o roteador", "how do I restart the router"),
 "onde fica a chave de API do banco vetorial": ("onde fica a chave do banco vetorial", "where is the vector DB key"),
 "qual modelo gera os embeddings e quantas dimensoes": ("modelo e dimensões dos embeddings", "embedding model and dimensions"),
 "por que o modo sleeping nao libera a GPU": ("por que sleeping não libera a GPU", "why sleeping doesn't free the GPU"),
 "qual modelo foi removido do servidor de modelos": ("qual modelo foi removido", "which model was removed"),
 "quais sao as rotas do roteador e a ordem de prioridade": ("rotas do roteador e prioridade", "router routes and priority"),
 "como testar o fallback do roteador": ("como testar o fallback do roteador", "how to test the router fallback"),
 "regras de sanitizacao antes de publicar": ("regras de sanitização", "sanitization rules"),
 "em qual cliente o braco do Claude deve rodar": ("cliente do braço Claude", "client for the Claude arm"),
 "receita de bolo de cenoura": ("receita de bolo (fora do tema)", "cake recipe (off-topic)"),
 "previsao do tempo em Lisboa": ("previsão do tempo (fora do tema)", "weather forecast (off-topic)"),
}

def fmt(v, lang, nd=2):
    s = f"{v:.{nd}f}"
    return s.replace(".", ",") if lang == "pt" else s

hist = [(datetime.strptime(r["momento_utc"], "%Y-%m-%d %H:%M:%S"), int(r["trechos"])) for r in csv.DictReader(open(os.path.join(DATA, "indexer_historico.csv"))) if r["na_figura"] == "1"]
comp = json.load(open(os.path.join(DATA, "composicao.json")))
antes = json.load(open(os.path.join(DATA, "resultado_antes.json")))
depois = json.load(open(os.path.join(DATA, "resultado_depois.json")))
res = antes

def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name + ".svg"))
    if PNG: fig.savefig(os.path.join(OUT, name + ".png"), dpi=90)
    plt.close(fig)

def fig_index(lang):
    t = T[lang]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 3.9), gridspec_kw={"width_ratios": [1.7, 1]})
    xs = [h[0] for h in hist]; ys = [h[1] for h in hist]
    ax.step(xs, ys, where="post", color=ORANGE, lw=2.8)
    ax.plot(xs, ys, "o", color=ORANGE, ms=6)
    ax.set_ylabel(t["y_chunks"]); ax.set_xlabel(t["x_time"])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); ax.set_ylim(0, 1100)
    ax.annotate(t["ann"], xy=(xs[3], ys[3]), xytext=(xs[0], 720), fontsize=9.5, color="#333", arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("64", xy=(xs[2], ys[2]), xytext=(0, 8), textcoords="offset points", fontsize=9, color=BLUE, ha="center")
    ax.annotate("971", xy=(xs[3], ys[3]), xytext=(-24, -3), textcoords="offset points", fontsize=9, color="#333", ha="right")
    ax.annotate("994", xy=(xs[6], ys[6]), xytext=(0, 7), textcoords="offset points", fontsize=9, color="#333", ha="center")
    ax.annotate(t["fix"], xy=(xs[-1], ys[-1]), xytext=(xs[-1], 300), fontsize=9.5, color=BLUE, ha="right", arrowprops=dict(arrowstyle="->", color=BLUE))
    ax.set_title(t["t_index"], loc="left", fontsize=11.5)
    total = sum(comp.values())
    parts = [("notes", comp["notas"], BLUE, t["c_notes"]), ("other", comp["outros_dados"], ORANGE_L, t["c_other"]), ("pacote", comp["pacote_cego"], ORANGE, t["c_pacote"])]
    left = 0
    for _, v, c, lab in parts:
        ax2.barh([0], [v], left=left, color=c, height=0.5)
        pct = 100 * v / total
        ax2.text(left + v / 2, 0, f"{v}\n({fmt(pct, lang, 0)}%)", ha="center", va="center", fontsize=9, color="white" if c in (BLUE, ORANGE) else "#333")
        left += v
    ax2.set_xlim(0, total); ax2.set_ylim(-1.5, 0.9); ax2.set_yticks([]); ax2.set_xlabel(t["y_chunks"])
    ax2.spines["left"].set_visible(False)
    ax2.legend(handles=[Patch(color=c, label=lab) for _, _, c, lab in parts], loc="lower center", bbox_to_anchor=(0.5, -0.02), fontsize=8.5, frameon=False)
    ax2.set_title(t["comp"], loc="left", fontsize=11.5)
    save(fig, f"indice-{lang}")

def fig_scores(lang):
    t = T[lang]; li = 0 if lang == "pt" else 1
    rows = antes["consultas"]; rows_d = depois["consultas"]
    fig, ax = plt.subplots(figsize=(9.4, 5.5))
    n = len(rows); hits_after = []
    for i, (r, rd) in enumerate(zip(rows, rows_d)):
        y = n - 1 - i
        b_, a_ = r["antes"][0][1], rd["antes"][0][1]
        if r["esperado"] is None: c = GREY
        elif rd["pos_antes"] == 1: c = BLUE; hits_after.append(a_)
        else: c = ORANGE; hits_after.append(a_)
        ax.plot([b_, a_], [y, y], color=OLD, lw=1.4, zorder=1)
        ax.scatter([b_], [y], facecolors="white", edgecolors=c, s=55, lw=1.8, zorder=2)
        ax.scatter([a_], [y], color=c, s=55, zorder=3)
        ax.text(max(a_, b_) + 0.012, y, fmt(a_, lang), va="center", fontsize=8.5, color="#333")
    ax.set_yticks(range(n)); ax.set_yticklabels([LAB[r["q"]][li] for r in rows][::-1], fontsize=9)
    lo, hi = min(hits_after), max(hits_after)
    ax.axvspan(lo, hi, color="#EEF2F8", zorder=0)
    ax.text(lo + 0.004, n - 0.35, t["band"].format(lo=fmt(lo, lang), hi=fmt(hi, lang)), fontsize=8.5, color=BLUE, va="bottom")
    ax.set_xlim(0.40, 0.80); ax.set_ylim(-0.7, n + 0.2); ax.set_xlabel(t["x_score"])
    ax.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor="white", markeredgecolor="#555", markersize=8, label=t["before"]),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=BLUE, markersize=8, label=t["after_ok"]),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=ORANGE, markersize=8, label=t["after_bad"]),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=GREY, markersize=8, label=t["after_off"])],
        loc="upper center", bbox_to_anchor=(0.45, -0.12), ncol=2, fontsize=8.5, frameon=False)
    ax.set_title(t["t_scores"], loc="left", fontsize=11.5)
    save(fig, f"scores-{lang}")

def fig_lat(lang):
    t = T[lang]; raw = res["lat_raw"]; summ = res["latencia_ms"]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    import random; random.seed(7)
    order = [("embed", BLUE, t["embed"]), ("busca", ORANGE, t["busca"]), ("total", GREY, t["total"])]
    for i, (k, c, lab) in enumerate(order[::-1]):
        v = raw[k]; y = i
        ax.scatter(v, [y + random.uniform(-0.12, 0.12) for _ in v], color=c, s=22, alpha=0.75, zorder=2)
        p50, p95 = summ[k]["p50"], summ[k]["p95"]
        ax.plot([p50, p50], [y - 0.28, y + 0.28], color="#222", lw=2, zorder=3)
        ax.plot([p95, p95], [y - 0.28, y + 0.28], color=RED, lw=2, ls="--", zorder=3)
        ax.text(max(v) + 0.8, y, f"{t['p50']} {fmt(p50, lang, 1)} · {t['p95']} {fmt(p95, lang, 1)} ms", va="center", fontsize=9, color="#333")
    ax.set_yticks(range(3)); ax.set_yticklabels([o[2] for o in order[::-1]]); ax.set_xlabel(t["x_lat"]); ax.set_xlim(0, 36); ax.set_ylim(-0.6, 2.6)
    ax.set_title(t["t_lat"], loc="left", fontsize=11.5)
    save(fig, f"latencia-{lang}")


def fig_env(lang):
    from matplotlib.patches import FancyBboxPatch
    pt = lang == "pt"
    fig, ax = plt.subplots(figsize=(11, 5.0)); ax.set_xlim(0, 110); ax.set_ylim(0, 50); ax.axis("off")
    def box(x, y, w, h, title, lines, rag, fs=9.5):
        ec = BLUE if rag else GREY
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2", fc="#EEF2F8" if rag else "#F4F4F4", ec=ec, lw=2 if rag else 1.2))
        ax.text(x + 1.4, y + h - 2.2, title, fontsize=fs + 1, fontweight="bold", va="top", color="#111")
        for i, l in enumerate(lines):
            ax.text(x + 1.4, y + h - 6.2 - i * 3.6, l, fontsize=fs, va="top", color="#222")
    box(1, 12, 25, 28, "PC de trabalho" if pt else "Work PC",
        ["vault de notas (Markdown)" if pt else "notes vault (Markdown)", "OpenCode v2.2.1", "ferramenta MCP buscar_vault" if pt else "MCP tool buscar_vault", "", "consulta: embedding + busca" if pt else "query: embedding + search"], True)
    ax.add_patch(FancyBboxPatch((33, 3), 76, 44, boxstyle="round,pad=0.3,rounding_size=1.5", fc="white", ec="#555", lw=1.6))
    ax.text(35, 45.6, "Hospedeiro Proxmox VE 8.4.19 · Ryzen 5 5600G (12 threads) · 62 GB RAM" if pt else "Proxmox VE 8.4.19 host · Ryzen 5 5600G (12 threads) · 62 GB RAM", fontsize=10.5, fontweight="bold", va="top")
    box(35, 7, 23, 32, "Container de serviços" if pt else "Services container",
        ["Qdrant 1.20.0", "  1024 dim · cosseno" if pt else "  1024 dim · cosine", "Syncthing 1.19.2", "  pasta receive-only" if pt else "  receive-only folder", "indexador Python 3.11.2" if pt else "Python 3.11.2 indexer", "  timer a cada hora" if pt else "  hourly timer"], True)
    box(60, 7, 22, 32, "GPU 0 · 16 GB",
        ["modelo de fallback" if pt else "fallback model", "do roteador" if pt else "of the router", "", "não participa do RAG" if pt else "not part of the RAG"], False)
    box(84, 7, 24, 32, "GPU 1 · 16 GB",
        ["llama.cpp b216-f12cc6d", "Vulkan · 4 slots · ctx 4096", "Qwen3-Embedding-0.6B", "  Q8_0 (RAG)", "completação de código" if pt else "code completion", "  (fora do RAG)" if pt else "  (not RAG)"], True)
    ax.annotate("", xy=(33, 26), xytext=(26.3, 26), arrowprops=dict(arrowstyle="<->", color="#333", lw=1.6))
    ax.text(29.6, 28, "LAN", ha="center", fontsize=9, color="#333")
    ax.legend(handles=[Patch(fc="#EEF2F8", ec=BLUE, lw=2, label="participa do RAG" if pt else "part of the RAG"), Patch(fc="#F4F4F4", ec=GREY, label="outros serviços" if pt else "other services")],
              loc="lower left", bbox_to_anchor=(0.0, -0.02), fontsize=9, frameon=False, ncol=2)
    save(fig, f"ambiente-{lang}")

def cover(lang):
    t = T[lang]
    fig = plt.figure(figsize=(12, 6.27), dpi=100, facecolor="#0F1B2D")
    fig.text(0.05, 0.82, t["cover1"], color="white", fontsize=40, fontweight="bold")
    fig.text(0.05, 0.73, t["cover2"], color="#C9D3E0", fontsize=22)
    ax = fig.add_axes([0.05, 0.1, 0.9, 0.52], facecolor="#0F1B2D")
    xs = [h[0] for h in hist]; ys = [h[1] for h in hist]
    ax.step(xs, ys, where="post", color="#FFA066", lw=4)
    ax.plot(xs, ys, "o", color="#FFA066", ms=9)
    ax.axvspan(xs[2], xs[-1], color="#3A2A2A")
    ax.axhline(64, color="#7FA7E0", ls="--", lw=2)
    for s in ax.spines.values(): s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([]); ax.set_ylim(0, 1100)
    fig.savefig(os.path.join(OUT, f"cover-{lang}.png"), facecolor=fig.get_facecolor())
    plt.close(fig)

for lang in ("pt", "en"):
    fig_env(lang); fig_index(lang); fig_scores(lang); fig_lat(lang); cover(lang)
print("ok")
