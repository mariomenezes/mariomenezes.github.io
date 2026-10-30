"""Figuras do post sobre RAG no homelab, a partir dos dados em ../data.

Uso (container com matplotlib):
  python3 make_figures.py <dir de dados> <dir de saida>

Gera, para pt e en: ambiente, indice (crescimento + composicao), scores (antes/depois),
latencia (30 repeticoes) e capa 1200x627. Estilo comum em estilo.py.
"""
import csv, json, os, random, sys
from datetime import datetime

import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from estilo import *

DATA, OUT = sys.argv[1], sys.argv[2]
LARANJA_CLARO = "#F0B490"

T = {
 "pt": dict(
    amb_t="Onde cada peça roda", amb_s="Em azul, o que participa do RAG; em cinza, outros serviços",
    t_index="Trechos no índice a cada execução do indexador",
    s_index="Uma única execução levou o índice de 64 para 971 trechos",
    x_time="horário (UTC, 29–30 out)", y_chunks="trechos no índice",
    ann="1 execução: 42 arquivos alterados,\n6 → 50 arquivos, 64 → 971 trechos (48 s)", comp="Origem dos 972 trechos",
    fix="82 trechos: dados/ e rascunhos\nexcluídos do indexador",
    c_notes="notas reais", c_other="outros dados do benchmark", c_pacote="um arquivo (pacote de avaliação)",
    t_scores="Sem dados/ no índice, as perguntas fora do tema\ncaem abaixo das demais",
    s_scores="Score do 1º resultado por pergunta; o traço liga o antes ao depois",
    x_score="score do 1º resultado (cosseno)",
    before="antes (índice de 972 trechos)", after_ok="depois (82): esperado em 1º",
    after_bad="depois (82): esperado fora do 1º", after_off="depois (82): fora do tema",
    band="faixa das perguntas com arquivo-alvo\n(depois): {lo}–{hi}",
    t_lat="Latência de uma consulta (índice de 972 trechos)",
    s_lat="30 repetições, 0 erros; traço preto: mediana; tracejado vermelho: p95",
    x_lat="milissegundos", embed="embedding da pergunta", busca="busca no Qdrant", total="total",
    p50="mediana", p95="p95", cover1="RAG no homelab com visibilidade",
    cover2="o corpus contaminado, não o score,\nera o problema"),
 "en": dict(
    amb_t="Where each piece runs", amb_s="Blue: part of the RAG; grey: other services",
    t_index="Chunks in the index at each indexer run",
    s_index="A single run took the index from 64 to 971 chunks",
    x_time="time (UTC, Oct 29–30)", y_chunks="chunks in the index",
    ann="1 run: 42 files changed,\n6 → 50 files, 64 → 971 chunks (48 s)", comp="Origin of the 972 chunks",
    fix="82 chunks: dados/ and drafts\nexcluded from the indexer",
    c_notes="actual notes", c_other="other benchmark data", c_pacote="one file (evaluation pack)",
    t_scores="Without dados/ in the index, off-topic questions\nfall below the rest",
    s_scores="Top-1 score per question; the line joins before and after",
    x_score="top-1 score (cosine)",
    before="before (972-chunk index)", after_ok="after (82): expected ranked 1st",
    after_bad="after (82): expected not 1st", after_off="after (82): off-topic",
    band="range of questions with a target file\n(after): {lo}–{hi}",
    t_lat="Query latency (972-chunk index)",
    s_lat="30 repetitions, 0 errors; black mark: median; dashed red: p95",
    x_lat="milliseconds", embed="question embedding", busca="Qdrant search", total="total",
    p50="median", p95="p95", cover1="RAG in a homelab with visibility",
    cover2="the polluted corpus, not the score,\nwas the problem"),
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

hist = [(datetime.strptime(r["momento_utc"], "%Y-%m-%d %H:%M:%S"), int(r["trechos"]))
        for r in csv.DictReader(open(os.path.join(DATA, "indexer_historico.csv"))) if r["na_figura"] == "1"]
comp = json.load(open(os.path.join(DATA, "composicao.json")))
antes = json.load(open(os.path.join(DATA, "resultado_antes.json")))
depois = json.load(open(os.path.join(DATA, "resultado_depois.json")))


def titulo_fig(fig, titulo, sub, y=0.98, gap=0.075):
    """Título e subtítulo alinhados à margem esquerda da figura (para eixos com rótulos longos)."""
    fig.text(0.01, y, titulo, fontsize=14, fontweight="bold", va="top", color="black", linespacing=1.25)
    n = titulo.count("\n") + 1
    fig.text(0.01, y - gap * n - 0.012, sub, fontsize=11, color=TEXTO2, va="top")


def bloco(ax, x, y, w, h, titulo, linhas, rag):
    cor, fundo = (REF, FAIXA_REF) if rag else (NEUTRO, "#F4F4F4")
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                lw=1.8 if rag else 1.2, edgecolor=cor, facecolor=fundo))
    ax.text(x + 0.15, y + h - 0.17, titulo, fontsize=12, fontweight="bold", va="top", color=ESCURO)
    for i, l in enumerate(linhas):
        ax.text(x + 0.15, y + h - 0.55 - i * 0.27, l, fontsize=10.5, va="top", color="#222")


def fig_env(lang):
    t = T[lang]; pt = lang == "pt"
    fig, ax = tela(LARGURA, 5.0)
    ax.set_title(t["amb_t"]); subtitulo(ax, t["amb_s"])
    bloco(ax, 0.1, 4.95, 9.8, 1.1, "PC de trabalho" if pt else "Work PC",
          ["vault de notas (Markdown) · OpenCode v2.2.1 · ferramenta MCP buscar_vault" if pt
           else "notes vault (Markdown) · OpenCode v2.2.1 · MCP tool buscar_vault",
           "consulta: embedding + busca" if pt else "query: embedding + search"], True)
    seta(ax, (5.0, 4.9), (5.0, 4.32), estilo="<|-|>", cor="#374151")
    ax.text(5.15, 4.61, "LAN", fontsize=10.5, color=TEXTO2, va="center")
    ax.add_patch(FancyBboxPatch((0.1, 0.05), 9.8, 4.2, boxstyle="round,pad=0.02,rounding_size=0.1", lw=1.2,
                                edgecolor="#9ca3af", facecolor="#F6F8FB"))
    ax.text(0.3, 4.05, "Hospedeiro Proxmox VE 8.4.19" if pt else "Proxmox VE 8.4.19 host",
            fontsize=12, fontweight="bold", color=ESCURO, va="center")
    ax.text(0.3, 3.73, "Ryzen 5 5600G (12 threads) · 62 GB RAM", fontsize=10.5, color=TEXTO2, va="center")
    w, y0, h = 3.07, 0.2, 3.25
    bloco(ax, 0.3, y0, w, h, "Container de serviços" if pt else "Services container",
          ["Qdrant 1.20.0", "  1024 dim · cosseno" if pt else "  1024 dim · cosine", "Syncthing 1.19.2",
           "  pasta receive-only" if pt else "  receive-only folder",
           "indexador Python 3.11.2" if pt else "Python 3.11.2 indexer",
           "  timer a cada hora" if pt else "  hourly timer"], True)
    bloco(ax, 0.3 + w + 0.1, y0, w, h, "GPU 0 · 16 GB",
          ["modelo de fallback" if pt else "fallback model", "do roteador" if pt else "of the router", "",
           "não participa do RAG" if pt else "not part of the RAG"], False)
    bloco(ax, 0.3 + 2 * (w + 0.1), y0, w, h, "GPU 1 · 16 GB",
          ["llama.cpp b216-f12cc6d", "HIP · 4 slots · ctx 4096", "Qwen3-Embedding-0.6B", "  Q8_0 (RAG)",
           "completação de código" if pt else "code completion", "  (fora do RAG)" if pt else "  (not RAG)"], True)
    salvar(fig, os.path.join(OUT, f"ambiente-{lang}.svg"))


def fig_index(lang):
    t = T[lang]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(LARGURA, 6.0), gridspec_kw={"height_ratios": [3, 1], "hspace": 0.75})
    xs = [h[0] for h in hist]; ys = [h[1] for h in hist]
    ax.step(xs, ys, where="post", color=FOCO, lw=2.8)
    ax.plot(xs, ys, "o", color=FOCO, ms=6)
    ax.set_ylabel(t["y_chunks"]); ax.set_xlabel(t["x_time"])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M")); ax.set_ylim(0, 1150)
    ax.annotate(t["ann"], xy=(xs[3], ys[3]), xytext=(xs[0], 560), fontsize=11, color="#333",
                arrowprops=dict(arrowstyle="->", color="#333"))
    ax.annotate("64", xy=(xs[2], ys[2]), xytext=(0, 9), textcoords="offset points", fontsize=11, color=REF, ha="center", fontweight="bold")
    ax.annotate("971", xy=(xs[3], ys[3]), xytext=(-10, 0), textcoords="offset points", fontsize=11, color="#333", ha="right", va="center")
    ax.annotate("994", xy=(xs[6], ys[6]), xytext=(0, 9), textcoords="offset points", fontsize=11, color="#333", ha="center")
    ax.annotate(t["fix"], xy=(xs[-1], ys[-1]), xytext=(xs[-1], 330), fontsize=11, color=REF, ha="right",
                arrowprops=dict(arrowstyle="->", color=REF))
    ax.set_title(t["t_index"]); subtitulo(ax, t["s_index"])
    total = sum(comp.values())
    parts = [(comp["notas"], REF, t["c_notes"]), (comp["outros_dados"], LARANJA_CLARO, t["c_other"]),
             (comp["pacote_cego"], FOCO, t["c_pacote"])]
    left = 0
    for v, c, lab in parts:
        ax2.barh([0], [v], left=left, color=c, height=0.8, edgecolor="white", lw=1.5)
        pct = 100 * v / total
        ax2.text(left + v / 2, 0, f"{v} ({num(pct, 0, lang)}%)" if v > 200 else f"{v}\n({num(pct, 0, lang)}%)",
                 ha="center", va="center", fontsize=11 if v > 200 else 10, color="white" if c != LARANJA_CLARO else ESCURO,
                 fontweight="bold")
        if v > 200:
            ax2.text(left + v / 2, -0.55, lab, ha="center", va="top", fontsize=11, color=TEXTO2)
        else:
            ax2.text(left, -0.55, lab, ha="left", va="top", fontsize=11, color=REF)
        left += v
    ax2.set_xlim(0, total); ax2.set_ylim(-0.5, 0.5); ax2.set_yticks([]); ax2.set_xticks([]); ax2.grid(False)
    for s in ax2.spines.values():
        s.set_visible(False)
    ax2.set_title(t["comp"], pad=10, fontsize=12.5)
    salvar(fig, os.path.join(OUT, f"indice-{lang}.svg"))


def fig_scores(lang):
    t = T[lang]; li = 0 if lang == "pt" else 1
    rows, rows_d = antes["consultas"], depois["consultas"]
    fig, ax = plt.subplots(figsize=(LARGURA, 6.6))
    fig.subplots_adjust(left=0.37, right=0.97, top=0.78, bottom=0.21)
    n = len(rows); hits_after = []; cores = []
    for i, (r, rd) in enumerate(zip(rows, rows_d)):
        y = n - 1 - i
        b_, a_ = r["antes"][0][1], rd["antes"][0][1]
        if r["esperado"] is None: c = NEUTRO
        elif rd["pos_antes"] == 1: c = REF; hits_after.append(a_)
        else: c = FOCO; hits_after.append(a_)
        cores.append(c)
        ax.plot([b_, a_], [y, y], color=ANTIGO, lw=1.6, zorder=1)
        ax.scatter([b_], [y], facecolors="white", edgecolors=c, s=70, lw=2, zorder=2)
        ax.scatter([a_], [y], color=c, s=70, zorder=3)
        ax.text(max(a_, b_) + 0.012, y, num(a_, 2, lang), va="center", fontsize=11, color="#333")
    ax.set_yticks(range(n)); ax.set_yticklabels([LAB[r["q"]][li] for r in rows][::-1], fontsize=11)
    ax.grid(axis="y", visible=False)
    lo, hi = min(hits_after), max(hits_after)
    ax.axvspan(lo, hi, color=FAIXA_REF, zorder=0)
    ax.text(lo + 0.004, n - 0.45, t["band"].format(lo=num(lo, 2, lang), hi=num(hi, 2, lang)), fontsize=10.5, color=REF, va="bottom")
    ax.set_xlim(0.40, 0.80); ax.set_ylim(-0.6, n + 0.75); ax.set_xlabel(t["x_score"])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: num(v, 2, lang)))
    fig.legend(handles=[
        Line2D([0], [0], marker="o", ls="", markerfacecolor="white", markeredgecolor="#555", mew=2, markersize=9, label=t["before"]),
        Line2D([0], [0], marker="o", ls="", markerfacecolor=REF, markeredgecolor=REF, markersize=9, label=t["after_ok"]),
        Line2D([0], [0], marker="o", ls="", markerfacecolor=FOCO, markeredgecolor=FOCO, markersize=9, label=t["after_bad"]),
        Line2D([0], [0], marker="o", ls="", markerfacecolor=NEUTRO, markeredgecolor=NEUTRO, markersize=9, label=t["after_off"])],
        loc="lower left", bbox_to_anchor=(0.01, 0.0), ncol=2, fontsize=11, columnspacing=1.5, handletextpad=0.4)
    titulo_fig(fig, t["t_scores"], t["s_scores"], gap=0.04)
    salvar(fig, os.path.join(OUT, f"scores-{lang}.svg"))


def fig_lat(lang):
    t = T[lang]; raw = antes["lat_raw"]; summ = antes["latencia_ms"]
    fig, ax = plt.subplots(figsize=(LARGURA, 4.2))
    fig.subplots_adjust(left=0.25, right=0.97, top=0.76, bottom=0.15)
    random.seed(7)
    order = [("embed", REF, t["embed"]), ("busca", FOCO, t["busca"]), ("total", NEUTRO, t["total"])]
    for i, (k, c, lab) in enumerate(order[::-1]):
        v = raw[k]; y = i
        ax.scatter(v, [y + random.uniform(-0.12, 0.12) for _ in v], color=c, s=26, alpha=0.75, zorder=2, lw=0)
        p50, p95 = summ[k]["p50"], summ[k]["p95"]
        ax.plot([p50, p50], [y - 0.24, y + 0.24], color="#222", lw=2.2, zorder=3)
        ax.plot([p95, p95], [y - 0.24, y + 0.24], color=ALARME, lw=2.2, ls="--", zorder=3)
        ax.text(min(v), y + 0.3, f"{t['p50']} {num(p50, 1, lang)} · {t['p95']} {num(p95, 1, lang)} ms",
                va="bottom", fontsize=11, color="#333")
    ax.set_yticks(range(3)); ax.set_yticklabels([o[2] for o in order[::-1]]); ax.grid(axis="y", visible=False)
    ax.set_xlabel(t["x_lat"]); ax.set_xlim(0, 36); ax.set_ylim(-0.45, 2.75)
    titulo_fig(fig, t["t_lat"], t["s_lat"], gap=0.085)
    salvar(fig, os.path.join(OUT, f"latencia-{lang}.svg"))


def cover(lang):
    t = T[lang]
    xs = [h[0] for h in hist]; ys = [h[1] for h in hist]

    def mini(ax):
        ax.axvspan(xs[2], xs[-1], color="#3A2A2A")
        ax.axhline(64, color="#7FA7E0", ls="--", lw=2)
        ax.step(xs, ys, where="post", color="#FFA066", lw=3)
        ax.plot(xs, ys, "o", color="#FFA066", ms=6)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_ylim(0, 1100)
    capa(os.path.join(OUT, f"cover-{lang}.png"), t["cover1"], t["cover2"], mini)


for lang in ("pt", "en"):
    fig_env(lang); fig_index(lang); fig_scores(lang); fig_lat(lang); cover(lang)
print("ok")
