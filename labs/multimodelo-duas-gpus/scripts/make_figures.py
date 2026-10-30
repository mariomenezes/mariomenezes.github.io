"""Figuras do post "Multimodelo em duas GPUs".
Uso: python3 make_figures.py <pasta_data> <pasta_saida>
Lê data/exp_a, exp_b, exp_c (amostras/eventos) e exp_d (latencias/ocioso) e gera, em pt e en:
ambiente, fases, regra, contorno e a capa (cover-pt.png, cover-en.png). Grava resumo_fases.json.
"""
import csv, json, statistics as st, sys
from estilo import *

DATA, OUT = sys.argv[1], sys.argv[2]


def ler(exp):
    a = list(csv.DictReader(open(f"{DATA}/{exp}/amostras.csv")))
    e = list(csv.DictReader(open(f"{DATA}/{exp}/eventos.csv")))
    for r in a:
        for k in ("t", "busy0", "busy1", "w0", "w1", "sclk1_mhz"):
            r[k] = int(r[k])
    return a, e


A, EA = ler("exp_a")
B, EB = ler("exp_b")

# número de processos HIP com fila na GPU 1 (e na GPU 0) em cada fase, conforme o roteiro
PROC_A = {"1": 2, "2": 1, "3": 1, "4": 0, "5": 2, "6": 2, "7": 2}
PROC_B = {"1": 2, "2": 1, "3": 1, "4": 2}
DESCARTE = 10  # s após cada mudança, tempo de transição


def estaveis(rows, fase):
    rs = [r for r in rows if r["fase"] == fase]
    return rs[DESCARTE:]


resumo = []
for nome, rows, proc in (("A", A, PROC_A), ("B", B, PROC_B)):
    for f, n in proc.items():
        rs = estaveis(rows, f)
        resumo.append({"exp": nome, "fase": f, "processos_gpu1": n, "amostras": len(rs),
                       "busy1_mediana": st.median(r["busy1"] for r in rs), "busy1_min": min(r["busy1"] for r in rs),
                       "busy1_max": max(r["busy1"] for r in rs), "w1_mediana": st.median(r["w1"] for r in rs),
                       "sclk1_mediana": st.median(r["sclk1_mhz"] for r in rs)})
for f, n in (("5", 2), ("6", 1)):
    rs = estaveis(B, f)
    resumo.append({"exp": "B", "fase": f, "processos_gpu0": n, "amostras": len(rs),
                   "busy0_mediana": st.median(r["busy0"] for r in rs), "busy0_min": min(r["busy0"] for r in rs),
                   "busy0_max": max(r["busy0"] for r in rs), "w0_mediana": st.median(r["w0"] for r in rs)})
C = list(csv.DictReader(open(f"{DATA}/exp_c/amostras.csv")))
NOME_C = {"1": "padrao", "2": "GPU_MAX_HW_QUEUES=1", "3": "GPU_MAX_HW_QUEUES=2", "4": "padrao"}
for f, nome in NOME_C.items():
    rs = [r for r in C if r["fase"] == f][DESCARTE:]
    resumo.append({"exp": "C", "fase": f, "config": nome, "processos_gpu1": 2, "amostras": len(rs),
                   "busy1_mediana": st.median(int(r["busy1"]) for r in rs), "busy1_min": min(int(r["busy1"]) for r in rs),
                   "busy1_max": max(int(r["busy1"]) for r in rs), "w1_mediana": st.median(int(r["w1"]) for r in rs)})
LAT = list(csv.DictReader(open(f"{DATA}/exp_d/latencias.csv")))
OC = list(csv.DictReader(open(f"{DATA}/exp_d/ocioso.csv")))
for cfg in ("padrao", "hwq1"):
    o = [r for r in OC if r["config"] == cfg]
    d = {"exp": "D", "config": cfg, "amostras_ociosas": len(o), "busy1_mediana": st.median(int(r["busy1"]) for r in o),
         "busy1_min": min(int(r["busy1"]) for r in o), "busy1_max": max(int(r["busy1"]) for r in o),
         "w1_mediana": st.median(int(r["w1"]) for r in o), "erros_http": sum(r["http"] != "200" for r in LAT if r["config"] == cfg)}
    for tipo in ("embedding", "completacao"):
        v = [float(r["segundos"]) * 1000 for r in LAT if r["config"] == cfg and r["tipo"] == tipo]
        d[f"{tipo}_n"] = len(v); d[f"{tipo}_ms_mediana"] = st.median(v); d[f"{tipo}_ms_min"] = min(v); d[f"{tipo}_ms_max"] = max(v)
    resumo.append(d)
json.dump(resumo, open(f"{OUT}/resumo_fases.json", "w"), indent=1)
for r in resumo:
    print(r)

T = {
 "pt": dict(
   amb_t="O hospedeiro e o papel de cada GPU",
   amb_s="Cada caixa laranja é um processo llama-server com fila de computação na GPU 1",
   host="Hospedeiro Proxmox", host_d="Ryzen 5 5600G · 62 GB · container com as 2 GPUs",
   g0="GPU 0 · 16 GB", g1="GPU 1 · 16 GB",
   p0="fallback do roteador", p0d="Qwen3-14B Q4_K_M · 10,4 GB",
   p1="completação de código", p1d="Qwen2.5-Coder-3B · porta 8083",
   p2="embeddings do RAG", p2d="Qwen3-Embedding-0.6B · porta 8084",
   tim="timer descarrega modelos ociosos", tim2="só alcança o roteador (GPU 0)",
   xtx="Outra máquina: RX 7900 XTX 24 GB", xtxd="modelo principal Qwen3.6-35B-A3B",
   f_t="A GPU 1 só fica em 100% quando os dois servidores estão ligados",
   f_s="Experimento A: um servidor por vez é desligado; 90 s por fase, 1 leitura por segundo",
   f_y1="uso da GPU 1 (%)", f_y2="potência da GPU 1 (W)", f_x="segundos desde o início",
   fases=["1. os dois\nligados", "2. só\nembedding", "3. só\ncompletação", "4. nenhum", "5. os dois,\nrecém-iniciados",
          "6. +1 pedido\nembedding", "7. +1 pedido\ncompletação"],
   r_t="A regra se repete nos dois experimentos e também na GPU 0",
   r_s="Mediana por fase (descartados os 10 s de transição); cada ponto é uma fase",
   r_x="processos llama-server com fila na mesma GPU", r_y="uso mediano da GPU (%)",
   r_y2="potência mediana (W)", lg_a="GPU 1, experimento A", lg_b="GPU 1, experimento B (ordem invertida)",
   lg_c="GPU 0, controle (fallback + processo temporário)",
   c_t="Com GPU_MAX_HW_QUEUES=1, a placa volta a descansar",
   c_s="Os dois servidores ligados; 2 rodadas por configuração",
   c_y1="potência da GPU 1 ociosa (W)", c_y2="tempo por pedido de embedding (ms)",
   c_l=["padrão\n(4 filas)", "GPU_MAX_HW_\nQUEUES=1"], c_n1="120 leituras, 1 por segundo", c_n2="60 pedidos de ~1.000 caracteres; o 1º de\ncada rodada (130 a 145 ms) fica acima da escala",
   cap_t="Duas GPUs de 16 GB: um processo\na mais e a placa não descansa",
   cap_s="2 servidores na mesma GPU: 100% de uso\ne ~37 W parados. 1 servidor: 2% e 11 W.",
 ),
 "en": dict(
   amb_t="The host and the role of each GPU",
   amb_s="Each orange box is one llama-server process with a compute queue on GPU 1",
   host="Proxmox host", host_d="Ryzen 5 5600G · 62 GB · container with both GPUs",
   g0="GPU 0 · 16 GB", g1="GPU 1 · 16 GB",
   p0="router fallback", p0d="Qwen3-14B Q4_K_M · 10.4 GB",
   p1="code completion", p1d="Qwen2.5-Coder-3B · port 8083",
   p2="RAG embeddings", p2d="Qwen3-Embedding-0.6B · port 8084",
   tim="timer unloads idle models", tim2="only reaches the router (GPU 0)",
   xtx="Another machine: RX 7900 XTX 24 GB", xtxd="main model Qwen3.6-35B-A3B",
   f_t="GPU 1 sits at 100% only when both servers are running",
   f_s="Experiment A: one server at a time is stopped; 90 s per phase, 1 reading per second",
   f_y1="GPU 1 busy (%)", f_y2="GPU 1 power (W)", f_x="seconds since start",
   fases=["1. both\nrunning", "2. embedding\nonly", "3. completion\nonly", "4. none", "5. both,\nfresh start",
          "6. +1 embed\nrequest", "7. +1 compl.\nrequest"],
   r_t="The rule holds in both experiments and on GPU 0 too",
   r_s="Median per phase (first 10 s after each change dropped); each point is one phase",
   r_x="llama-server processes with a queue on the same GPU", r_y="median GPU busy (%)",
   r_y2="median power (W)", lg_a="GPU 1, experiment A", lg_b="GPU 1, experiment B (reversed order)",
   lg_c="GPU 0, control (fallback + temporary process)",
   c_t="With GPU_MAX_HW_QUEUES=1 the card rests again",
   c_s="Both servers running; 2 rounds per configuration",
   c_y1="idle GPU 1 power (W)", c_y2="time per embedding request (ms)",
   c_l=["default\n(4 queues)", "GPU_MAX_HW_\nQUEUES=1"], c_n1="120 readings, 1 per second", c_n2="60 requests of ~1,000 characters; the 1st of\neach round (130 to 145 ms) is above the scale",
   cap_t="Two 16 GB GPUs: one extra\nprocess and the card never rests",
   cap_s="2 servers on one GPU: 100% busy\nand ~37 W idle. 1 server: 2% and 11 W.",
 ),
}

for lang, t in T.items():
    L = lambda x, c=1: num(x, c, lang)
    # ---------- 1. ambiente ----------
    fig, ax = tela(LARGURA, 3.8)
    ax.set_title(t["amb_t"]); subtitulo(ax, t["amb_s"])
    ax.add_patch(FancyBboxPatch((0.1, 0.15), 9.8, 4.15, boxstyle="round,pad=0.02,rounding_size=0.1", lw=1.2,
                                edgecolor="#9ca3af", facecolor="#F6F8FB"))
    ax.text(0.3, 4.05, t["host"], fontsize=12, fontweight="bold", color=ESCURO, va="center")
    ax.text(0.3, 3.72, t["host_d"], fontsize=10.5, color=TEXTO2, va="center")
    for x0, g in ((0.35, t["g0"]), (5.1, t["g1"])):
        ax.add_patch(FancyBboxPatch((x0, 0.35), 4.55, 3.0, boxstyle="round,pad=0.02,rounding_size=0.08", lw=1.2,
                                    edgecolor="#9ca3af", facecolor="white"))
        ax.text(x0 + 0.15, 3.12, g, fontsize=11.5, fontweight="bold", color=ESCURO, va="center")
    caixa(ax, 0.6, 1.75, 4.05, 1.05, t["p0"], t["p0d"], cor=REF, fundo=FAIXA_REF)
    ax.text(2.62, 1.2, t["tim"], ha="center", fontsize=10.5, color=REF)
    ax.text(2.62, 0.82, t["tim2"], ha="center", fontsize=10.5, color=TEXTO2)
    caixa(ax, 5.35, 1.95, 4.05, 0.95, t["p1"], t["p1d"], cor=FOCO, fundo=FAIXA)
    caixa(ax, 5.35, 0.65, 4.05, 0.95, t["p2"], t["p2d"], cor=FOCO, fundo=FAIXA)
    salvar(fig, f"{OUT}/ambiente-{lang}.svg")

    # ---------- 2. fases do experimento A ----------
    t0 = A[0]["t"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(LARGURA, 5.6), sharex=True, gridspec_kw={"height_ratios": [1.5, 1], "hspace": 0.12})
    x = [r["t"] - t0 for r in A]
    lim = [int(e["t"]) - t0 for e in EA]
    for i in range(7):
        n = PROC_A[str(i + 1)]
        cor = FAIXA if n == 2 else ("#FFFFFF" if n == 0 else "#F3F5F8")
        for ax_ in (a1, a2):
            ax_.axvspan(lim[i], lim[i + 1], color=cor, lw=0, zorder=0)
            if i:
                ax_.axvline(lim[i], color="#c7ccd4", lw=0.8, zorder=1)
        a1.text((lim[i] + lim[i + 1]) / 2, 104, t["fases"][i], ha="center", va="bottom", fontsize=9.6, color=ESCURO, linespacing=1.15)
    a1.plot(x, [r["busy1"] for r in A], color=FOCO, lw=2)
    a2.plot(x, [r["w1"] for r in A], color=FOCO, lw=2)
    a1.set_ylim(0, 100); a1.set_yticks([0, 25, 50, 75, 100]); a1.set_ylabel(t["f_y1"])
    a2.set_ylim(0, 55); a2.set_ylabel(t["f_y2"]); a2.set_xlabel(t["f_x"]); a2.set_xlim(0, lim[-1])
    a1.set_title(t["f_t"], pad=78); a1.text(0, 1.27, t["f_s"], transform=a1.transAxes, fontsize=11, color=TEXTO2)
    salvar(fig, f"{OUT}/fases-{lang}.svg")

    # ---------- 3. a regra: processos por GPU x uso e potência ----------
    fig, (b1, b2) = plt.subplots(1, 2, figsize=(LARGURA, 4.1), gridspec_kw={"wspace": 0.32})
    jit = {"A": -0.12, "B": 0.0, "C": 0.12}
    for r in resumo:
        if r["exp"] in ("C", "D"):
            continue
        if "processos_gpu1" in r:
            k, n, y, w = r["exp"], r["processos_gpu1"], r["busy1_mediana"], r["w1_mediana"]
            cor, mk = (FOCO, "o") if k == "A" else (FOCO, "s")
            face = cor if k == "A" else "white"
        else:
            k, n, y, w = "C", r["processos_gpu0"], r["busy0_mediana"], r["w0_mediana"]
            cor, mk, face = REF, "D", REF
        for ax_, v in ((b1, y), (b2, w)):
            ax_.scatter(n + jit[k], v, s=70, marker=mk, facecolor=face, edgecolor=cor, lw=1.8, zorder=3)
    for ax_ in (b1, b2):
        ax_.set_xticks([0, 1, 2]); ax_.set_xlim(-0.5, 2.5); ax_.set_xlabel(t["r_x"], fontsize=10.5)
    b1.set_ylim(-5, 110); b1.set_ylabel(t["r_y"]); b2.set_ylim(0, 45); b2.set_ylabel(t["r_y2"])
    b1.set_title(t["r_t"], pad=30); b1.text(0, 1.04, t["r_s"], transform=b1.transAxes, fontsize=10.5, color=TEXTO2)
    h = [plt.Line2D([], [], marker="o", ls="", markerfacecolor=FOCO, markeredgecolor=FOCO, ms=8, label=t["lg_a"]),
         plt.Line2D([], [], marker="s", ls="", markerfacecolor="white", markeredgecolor=FOCO, ms=8, mew=1.8, label=t["lg_b"]),
         plt.Line2D([], [], marker="D", ls="", markerfacecolor=REF, markeredgecolor=REF, ms=7, label=t["lg_c"])]
    fig.legend(handles=h, loc="lower center", ncol=1, bbox_to_anchor=(0.5, -0.2), fontsize=10.5)
    salvar(fig, f"{OUT}/regra-{lang}.svg")

    # ---------- 4. contorno ----------
    import random
    random.seed(1)
    fig, (c1, c2) = plt.subplots(1, 2, figsize=(LARGURA, 4.0), gridspec_kw={"wspace": 0.35})
    for i, cfg in enumerate(("padrao", "hwq1")):
        cor = FOCO if cfg == "padrao" else REF
        w = [int(r["w1"]) + random.uniform(-0.25, 0.25) for r in OC if r["config"] == cfg]
        c1.scatter([i + random.uniform(-0.18, 0.18) for _ in w], w, s=10, color=cor, alpha=0.5, lw=0)
        mw = st.median(int(r["w1"]) for r in OC if r["config"] == cfg)
        c1.hlines(mw, i - 0.28, i + 0.28, color=ESCURO, lw=2); c1.text(i + 0.32, mw, f"{L(mw, 0)} W", va="center", fontsize=11, fontweight="bold")
        v = [float(r["segundos"]) * 1000 for r in LAT if r["config"] == cfg and r["tipo"] == "embedding"]
        c2.scatter([i + random.uniform(-0.18, 0.18) for _ in v], v, s=14, color=cor, alpha=0.6, lw=0)
        mv = st.median(v)
        c2.hlines(mv, i - 0.28, i + 0.28, color=ESCURO, lw=2); c2.text(i + 0.32, mv, f"{L(mv)} ms", va="center", fontsize=11, fontweight="bold")
    for ax_, yl, n in ((c1, t["c_y1"], t["c_n1"]), (c2, t["c_y2"], t["c_n2"])):
        ax_.set_xticks([0, 1]); ax_.set_xticklabels(t["c_l"], fontsize=10.5); ax_.set_xlim(-0.5, 1.75); ax_.set_ylabel(yl, fontsize=11)
        ax_.text(0, -0.36, n, transform=ax_.transAxes, fontsize=10, color=TEXTO2)
    c1.set_ylim(0, 45); c2.set_ylim(0, 16)
    c1.set_title(t["c_t"], pad=30); c1.text(0, 1.04, t["c_s"], transform=c1.transAxes, fontsize=10.5, color=TEXTO2)
    salvar(fig, f"{OUT}/contorno-{lang}.svg")

    # ---------- capa ----------
    def mini(ax):
        ax.plot([r["t"] - t0 for r in A], [r["busy1"] for r in A], color=FOCO, lw=2.2)
        ax.set_ylim(0, 105); ax.set_yticks([0, 100]); ax.set_xticks([])
    capa(f"{OUT}/cover-{lang}.png", t["cap_t"], t["cap_s"], mini)
print("ok")
