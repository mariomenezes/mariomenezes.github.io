"""Figuras do post de calibração dos sinais do roteador.
Uso (na raiz do lab): python3 scripts/make_figures.py data <pasta_saida>
Lê data/analise.json (do analisar.py), data/medida_posicao_instrucao.json e data/bench_v2/*/*.json.
"""
import glob, json, os, random, statistics as st, sys
sys.path.insert(0, os.path.dirname(__file__))
from estilo import *

DATA, OUT = sys.argv[1], sys.argv[2]
A = json.load(open(f"{DATA}/analise.json"))
POS = json.load(open(f"{DATA}/medida_posicao_instrucao.json"))
RUNS = [json.load(open(f)) for f in sorted(glob.glob(f"{DATA}/bench_v2/*/*.json"))]
ITENS, BENCH = A["itens"], A["bench"]
LIM_D, LIM_A = 0.85, 0.7

T = {
 "pt": dict(
  amb_t="Onde cada peça roda", amb_s="O classificador do roteador roda em CPU, antes de o pedido chegar a uma GPU",
  cli="Cliente", cli_d="OpenCode", rot="Roteador semântico", rot_d="4 vCPU · 6 GB · sem GPU",
  vela="Vela-2.0-0.3B", vela_d="responde as perguntas de decisão", xtx="Modelo principal", xtx_d="Qwen3.6-35B-A3B · RX 7900 XTX",
  fb="Fallback", fb_d="Qwen3-14B · RX 9060 XT", emb="Embeddings (só no teste B)", emb_d="Qwen3-Embedding-0.6B",
  a_ped="pedido", a_esc="modelo escolhido", a_fal="se o principal falhar",
  pd_t="Perguntas curtas: 47 de 48 certas. Tarefas reais: 0 de 4",
  pd_s="Probabilidade de \"investigação ou design\" que o roteador atribui a cada pedido",
  pd_x="P(deep) atribuída pelo roteador", lim_d="limiar 0,85",
  g=["curtas · rápidas (24)", "curtas · investigação (24)", "tarefas reais · rápidas (4)", "tarefas reais · investigação (4)"],
  miss="tf-d3: 0,69", real="nenhuma passa do limiar",
  po_t="A mesma instrução, sozinha, passa do limiar",
  po_s="P(deep) da instrução isolada, do prompt real e do prompt com a instrução repetida no fim",
  po_x="P(deep)", po_l=["só a instrução", "prompt original", "instrução repetida no fim"],
  nomes={"01-k8s-crashloop": "01 · pod em CrashLoop", "04-terraform-recriacao": "04 · plano recria recurso",
         "06-mesh-latencia": "06 · latência após mesh", "07-migracao-banco": "07 · migração de banco"},
  at_t="Ataques diretos: 7 de 8 bloqueados. Indiretos: 4 de 8",
  at_s="Probabilidade de ataque; nenhum pedido legítimo passou do limiar, mas um chegou a 0,58",
  at_x="P(attack) atribuída pelo roteador", lim_a="limiar 0,7",
  ga=["ataques diretos (8)", "ataques indiretos (8)", "benignos parecidos (16)", "pedidos técnicos (48)"],
  sh="sh-d3: 0,58",
  cu_t="A decisão custa de 0,6 a 3,4 s e cresce com o prompt",
  cu_s="Benchmark, 7 cenários × 2 rodadas; o modelo e a velocidade de geração são os mesmos nos dois braços",
  cu_x="tokens do prompt", cu_y="latência de decisão (ms)", cu_y2="tempo até o 1º token (s)",
  cu_a="via roteador (A)", cu_c="direto no modelo (C)",
  cap_t="O roteador acerta perguntas\ncurtas e erra tarefas reais",
  cap_s="47 de 48 perguntas curtas certas.\n0 de 4 tarefas reais com artefatos.",
 ),
 "en": dict(
  amb_t="Where each piece runs", amb_s="The router's classifier runs on CPU, before the request reaches a GPU",
  cli="Client", cli_d="OpenCode", rot="Semantic router", rot_d="4 vCPU · 6 GB · no GPU",
  vela="Vela-2.0-0.3B", vela_d="answers the decision questions", xtx="Main model", xtx_d="Qwen3.6-35B-A3B · RX 7900 XTX",
  fb="Fallback", fb_d="Qwen3-14B · RX 9060 XT", emb="Embeddings (test B only)", emb_d="Qwen3-Embedding-0.6B",
  a_ped="request", a_esc="chosen model", a_fal="if the main one fails",
  pd_t="Short questions: 47 of 48 right. Real tasks: 0 of 4",
  pd_s="Probability of \"investigation or design\" the router assigns to each request",
  pd_x="P(deep) assigned by the router", lim_d="threshold 0.85",
  g=["short · quick (24)", "short · investigation (24)", "real tasks · quick (4)", "real tasks · investigation (4)"],
  miss="tf-d3: 0.69", real="none crosses the threshold",
  po_t="The same instruction, on its own, crosses the threshold",
  po_s="P(deep) of the bare instruction, the real prompt, and the prompt with the instruction repeated at the end",
  po_x="P(deep)", po_l=["instruction only", "original prompt", "instruction repeated at the end"],
  nomes={"01-k8s-crashloop": "01 · pod in CrashLoop", "04-terraform-recriacao": "04 · plan recreates resource",
         "06-mesh-latencia": "06 · latency after mesh", "07-migracao-banco": "07 · database migration"},
  at_t="Direct attacks: 7 of 8 blocked. Indirect: 4 of 8",
  at_s="Attack probability; no legitimate request crossed the threshold, but one reached 0.58",
  at_x="P(attack) assigned by the router", lim_a="threshold 0.7",
  ga=["direct attacks (8)", "indirect attacks (8)", "look-alike benign (16)", "technical requests (48)"],
  sh="sh-d3: 0.58",
  cu_t="The decision costs 0.6 to 3.4 s and grows with the prompt",
  cu_s="Benchmark, 7 scenarios × 2 rounds; the model and generation speed are the same in both arms",
  cu_x="prompt tokens", cu_y="decision latency (ms)", cu_y2="time to first token (s)",
  cu_a="through the router (A)", cu_c="straight to the model (C)",
  cap_t="The router gets short questions\nright and real tasks wrong",
  cap_s="47 of 48 short questions right.\n0 of 4 real tasks with artifacts.",
 ),
}


def faixa_strip(ax, linhas, xs_por_linha, cores, mk=None):
    random.seed(7)
    for i, (xs, cor) in enumerate(zip(xs_por_linha, cores)):
        ys = [i + random.uniform(-0.17, 0.17) for _ in xs]
        ax.scatter(xs, ys, s=46, color=cor, alpha=0.85, edgecolor="white", lw=0.6, zorder=3, marker=(mk[i] if mk else "o"))
    ax.set_yticks(range(len(linhas))); ax.set_yticklabels(linhas); ax.set_ylim(-0.7, len(linhas) - 0.4)
    ax.invert_yaxis(); ax.grid(axis="y", visible=False)


# ajuste linear da latência de decisão contra tokens do prompt (braço A)
pts = [(r["usage"]["prompt_tokens"], float(r["vsr"]["x-vsr-routing-latency-ms"])) for r in RUNS
       if r["braco"] == "A" and r["vsr"].get("x-vsr-routing-latency-ms") and r["usage"].get("prompt_tokens")]
n = len(pts); mx = sum(p[0] for p in pts) / n; my = sum(p[1] for p in pts) / n
incl = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts); inter = my - incl * mx
json.dump({"pontos": n, "ms_por_token": incl, "intercepto_ms": inter}, open(f"{OUT}/ajuste_latencia.json", "w"), indent=1)
print("latência ~", round(incl, 2), "ms/token, intercepto", round(inter), "ms, n =", n)

for lang, t in T.items():
    L = lambda x, c=2: num(x, c, lang)
    # ---------- ambiente ----------
    fig, ax = tela(LARGURA, 4.0)
    ax.set_title(t["amb_t"]); subtitulo(ax, t["amb_s"])
    caixa(ax, 0.05, 2.0, 1.75, 1.0, t["cli"], t["cli_d"], cor=NEUTRO, tam=11)
    ax.add_patch(FancyBboxPatch((2.45, 0.35), 3.5, 3.6, boxstyle="round,pad=0.02,rounding_size=0.08", lw=1.2, edgecolor="#9ca3af", facecolor="#F6F8FB"))
    ax.text(2.6, 3.65, t["rot"], fontsize=12, fontweight="bold", color=ESCURO, va="center")
    ax.text(2.6, 3.28, t["rot_d"], fontsize=10.5, color=TEXTO2, va="center")
    caixa(ax, 2.65, 0.65, 3.1, 1.6, t["vela"], t["vela_d"].replace(" as ", " as\n").replace(" the ", " the\n"), cor=FOCO, fundo=FAIXA, tam=11)
    caixa(ax, 6.55, 2.55, 3.4, 1.15, t["xtx"], t["xtx_d"], cor=REF, fundo=FAIXA_REF, tam=11)
    caixa(ax, 6.55, 0.65, 3.4, 1.15, t["fb"], t["fb_d"], cor=REF, tam=11)
    seta(ax, (1.8, 2.5), (2.45, 2.5))
    seta(ax, (5.95, 3.1), (6.55, 3.1))
    seta(ax, (8.25, 2.55), (8.25, 1.8), ls="--")
    ax.text(8.35, 2.17, t["a_fal"], fontsize=10, color=TEXTO2, va="center")
    salvar(fig, f"{OUT}/ambiente-{lang}.svg")

    # ---------- P(deep) ----------
    dif = [i for i in ITENS if i["tarefa"] == "dificuldade"]
    grupos = [[i["p_deep"] for i in dif if i["rotulo"] == "quick"], [i["p_deep"] for i in dif if i["rotulo"] == "deep"],
              [b["p_deep"] for b in BENCH if b["rotulo"] == "quick"], [b["p_deep"] for b in BENCH if b["rotulo"] == "deep"]]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.9))
    faixa_strip(ax, t["g"], grupos, [REF, REF, FOCO, FOCO], mk=["o", "o", "s", "s"])
    ax.axvline(LIM_D, color=ALARME, lw=1.6, ls="--", zorder=2)
    ax.text(LIM_D - 0.01, -0.45, t["lim_d"], color=ALARME, fontsize=10.5, va="center", ha="right")
    tf = [i for i in dif if i["id"] == "tf-d3"][0]
    ax.annotate(t["miss"], xy=(tf["p_deep"], 1), xytext=(0.47, 1.42), fontsize=10.5, color=ESCURO,
                arrowprops=dict(arrowstyle="->", color=TEXTO2, lw=1.1))
    ax.text(0.30, 2.62, t["real"], fontsize=10.5, color=FOCO, fontweight="bold")
    ax.axhspan(1.5, 3.6, color=FAIXA, alpha=0.35, lw=0, zorder=0)
    ax.set_xlim(-0.02, 1.02); ax.set_xlabel(t["pd_x"])
    ax.set_title(t["pd_t"]); subtitulo(ax, t["pd_s"])
    if lang == "pt":
        virgula(ax)
    salvar(fig, f"{OUT}/pdeep-{lang}.svg")

    # ---------- posição da instrução ----------
    fig, ax = plt.subplots(figsize=(LARGURA, 3.6))
    mks = [("o", NEUTRO, NEUTRO), ("o", FOCO, FOCO), ("D", REF, "white")]
    for i, r in enumerate(POS):
        vals = [r["so_instrucao"], r["original"], r["instrucao_no_fim"]]
        ax.plot([min(vals), max(vals)], [i, i], color="#d1d5db", lw=2, zorder=1)
        for v, (m, c, f) in zip(vals, mks):
            ax.scatter(v, i, marker=m, s=80, color=f, edgecolor=c, lw=1.8, zorder=3)
    ax.set_yticks(range(len(POS))); ax.set_yticklabels([t["nomes"][r["id"]] for r in POS]); ax.invert_yaxis(); ax.grid(axis="y", visible=False)
    ax.axvline(LIM_D, color=ALARME, lw=1.6, ls="--"); ax.text(LIM_D + 0.01, -0.55, t["lim_d"], color=ALARME, fontsize=10.5)
    ax.set_xlim(-0.02, 1.02); ax.set_ylim(len(POS) - 0.5, -0.8); ax.set_xlabel(t["po_x"])
    h = [plt.Line2D([], [], marker=m, ls="", markerfacecolor=f, markeredgecolor=c, ms=8, mew=1.8, label=l) for (m, c, f), l in zip(mks, t["po_l"])]
    ax.legend(handles=h, loc="upper center", bbox_to_anchor=(0.45, -0.2), ncol=3, fontsize=10.5)
    ax.set_title(t["po_t"]); subtitulo(ax, t["po_s"])
    if lang == "pt":
        virgula(ax)
    salvar(fig, f"{OUT}/posicao-{lang}.svg")

    # ---------- ataque ----------
    atk = [i for i in ITENS if i["tarefa"] == "ataque"]
    ga = [[i["p_attack"] for i in atk if i["grupo"] == "direto"], [i["p_attack"] for i in atk if i["grupo"] == "indireto"],
          [i["p_attack"] for i in atk if i["grupo"] == "benigno"], [i["p_attack"] for i in dif]]
    fig, ax = plt.subplots(figsize=(LARGURA, 3.7))
    faixa_strip(ax, t["ga"], ga, [FOCO, FOCO, REF, REF])
    ax.axvline(LIM_A, color=ALARME, lw=1.6, ls="--", zorder=2); ax.text(LIM_A - 0.01, -0.45, t["lim_a"], color=ALARME, fontsize=10.5, va="center", ha="right")
    sh = [i for i in dif if i["id"] == "sh-d3"][0]
    ax.annotate(t["sh"], xy=(sh["p_attack"], 3), xytext=(0.38, 2.45), fontsize=10.5, color=ESCURO, arrowprops=dict(arrowstyle="->", color=TEXTO2, lw=1.1))
    ax.set_xlim(-0.02, 1.02); ax.set_xlabel(t["at_x"])
    ax.set_title(t["at_t"]); subtitulo(ax, t["at_s"])
    if lang == "pt":
        virgula(ax)
    salvar(fig, f"{OUT}/ataque-{lang}.svg")

    # ---------- custo ----------
    fig, (c1, c2) = plt.subplots(2, 1, figsize=(LARGURA, 6.4), gridspec_kw={"hspace": 0.55})
    c1.scatter([p[0] for p in pts], [p[1] for p in pts], s=50, color=FOCO, edgecolor="white", zorder=3)
    xs = [0, 1500]; c1.plot(xs, [inter + incl * x for x in xs], color=TEXTO2, lw=1.2, ls="--")
    c1.text(1000, inter + incl * 1000 - 650, f"≈ {L(incl, 1)} ms/token", fontsize=11, color=ESCURO)
    c1.set_xlim(0, 1500); c1.set_ylim(0, 3800); c1.set_xlabel(t["cu_x"]); c1.set_ylabel(t["cu_y"])
    c1.set_title(t["cu_t"]); subtitulo(c1, t["cu_s"])
    cen = sorted({r["cenario"] for r in RUNS if r["cenario"] != "08-prompt-injection"})
    for i, cn in enumerate(cen):
        a = [r["ttft"] for r in RUNS if r["cenario"] == cn and r["braco"] == "A"]
        c = [r["ttft"] for r in RUNS if r["cenario"] == cn and r["braco"] == "C"]
        c2.plot([st.mean(c), st.mean(a)], [i, i], color="#d1d5db", lw=2, zorder=1)
        c2.scatter(c, [i] * len(c), color=REF, s=42, zorder=3); c2.scatter(a, [i] * len(a), color=FOCO, s=42, zorder=3)
    c2.set_yticks(range(len(cen))); c2.set_yticklabels([x[:2] + " · " + x[3:] for x in cen], fontsize=10.5); c2.invert_yaxis(); c2.grid(axis="y", visible=False)
    c2.set_xlim(0, 4.5); c2.set_xlabel(t["cu_y2"])
    h = [plt.Line2D([], [], marker="o", ls="", color=FOCO, ms=7, label=t["cu_a"]), plt.Line2D([], [], marker="o", ls="", color=REF, ms=7, label=t["cu_c"])]
    c2.legend(handles=h, loc="lower right", fontsize=10.5)
    if lang == "pt":
        virgula(c1, c2)
    salvar(fig, f"{OUT}/custo-{lang}.svg")

    # ---------- capa ----------
    def mini(ax):
        random.seed(3)
        for k, (vals, cor) in enumerate(((grupos[1], REF), (grupos[3], FOCO))):
            ax.scatter(vals, [k + random.uniform(-0.15, 0.15) for _ in vals], s=40, color=cor)
        ax.axvline(LIM_D, color=ALARME, ls="--", lw=1.5); ax.set_xlim(-0.02, 1.02); ax.set_ylim(-0.6, 1.6); ax.set_yticks([]); ax.set_xticks([0, 0.85, 1])
        ax.set_xticklabels(["0", "0,85" if lang == "pt" else "0.85", "1"])
    capa(f"{OUT}/cover-{lang}.png", t["cap_t"], t["cap_s"], mini)
print("ok")
