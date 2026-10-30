"""Figura de uso e VRAM das GPUs. Uso: python3 make_figures.py <gpu_amostra.csv> <pasta_de_saida>"""
import csv, statistics, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV, OUT = sys.argv[1], sys.argv[2]
BLUE, ORANGE = "#4C72B0", "#DD8452"
plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 12.5, "svg.fonttype": "none"})
rows = [r for r in csv.reader(open(CSV)) if len(r) == 5]
t0 = int(rows[0][0])
x = [(int(r[0]) - t0) / 60 for r in rows]
b0 = [int(r[1]) for r in rows]; b1 = [int(r[2]) for r in rows]
v0 = [int(r[3]) / 2**30 for r in rows]; v1 = [int(r[4]) / 2**30 for r in rows]
fig, (ax, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.5, 1]})
ax.plot(x, b1, color=ORANGE, lw=2.6, label="GPU 1 (embedding + completação)")
ax.plot(x, b0, color=BLUE, lw=2.6, label="GPU 0 (fallback do roteador)")
ax.set_ylim(0, 110); ax.set_xlabel("minutos desde o início da amostragem"); ax.set_ylabel("uso da GPU (%)")
ax.set_title("Uso da GPU em 5 minutos", loc="left", fontsize=11.5)
ax.legend(loc="lower right", frameon=False, fontsize=9)
m0, m1 = statistics.median(v0), statistics.median(v1)
ax2.bar(["GPU 0", "GPU 1"], [m0, m1], color=[BLUE, ORANGE], width=0.5)
for i, v in enumerate([m0, m1]):
    ax2.text(i, v + 0.2, f"{v:.1f} GB".replace(".", ","), ha="center", fontsize=10)
ax2.set_ylim(0, 16); ax2.set_ylabel("VRAM em uso (GB)")
ax2.set_title("Memória ocupada (16 GB por placa)", loc="left", fontsize=11.5)
fig.tight_layout(); fig.savefig(f"{OUT}/gpu-pt.svg"); fig.savefig(f"{OUT}/gpu-en.svg")
print("ok")
