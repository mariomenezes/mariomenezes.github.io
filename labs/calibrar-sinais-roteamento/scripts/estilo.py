"""Estilo comum das figuras do blog (paleta e tipografia do guia de identidade).

As figuras são desenhadas na largura em que aparecem no post (cerca de 8,2 polegadas a 100 dpi),
para que a fonte de 12 pt apareça com 12 px na tela, sem redução.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

REF, FOCO, NEUTRO, ALARME, ANTIGO = "#4C72B0", "#DD8452", "#8C8C8C", "#C44E52", "#B0B0B0"
FAIXA, FAIXA_REF, ESCURO, TEXTO2 = "#FBE3D6", "#EAF0F8", "#0F1B2D", "#4B5563"
LARGURA = 8.2

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 12, "axes.titlesize": 14, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.titlepad": 30, "axes.labelsize": 12, "axes.labelcolor": "#1f2937",
    "xtick.labelsize": 11, "ytick.labelsize": 11, "xtick.color": "#374151", "ytick.color": "#374151",
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#9ca3af",
    "axes.grid": True, "grid.color": "#eceff3", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "legend.fontsize": 11, "figure.dpi": 100, "savefig.dpi": 100,
    "svg.fonttype": "none", "savefig.bbox": "tight", "savefig.pad_inches": 0.15,
})


def num(x, casas=1, lang="pt"):
    s = f"{x:,.{casas}f}"
    if lang == "pt":
        s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return s


def virgula(*axes, y=False):
    """Separador decimal com vírgula no eixo x (e no y, se y=True) das figuras -pt."""
    from matplotlib.ticker import FuncFormatter
    f = FuncFormatter(lambda v, _: (f"{v:g}").replace(".", ","))
    for ax in axes:
        ax.xaxis.set_major_formatter(f)
        if y:
            ax.yaxis.set_major_formatter(f)


def subtitulo(ax, texto):
    """Linha abaixo do título com o que olhar na figura."""
    ax.text(0, 1.02, texto, transform=ax.transAxes, fontsize=11, color=TEXTO2, va="bottom")


PILHA = "font-family: 'DejaVu Sans', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


def salvar(fig, caminho):
    """Salva e, no SVG, troca a fonte única por uma pilha sem serifa (o navegador pode não ter DejaVu)."""
    fig.savefig(caminho)
    plt.close(fig)
    if caminho.endswith(".svg"):
        s = open(caminho, encoding="utf-8").read().replace("font-family: 'DejaVu Sans'", PILHA)
        open(caminho, "w", encoding="utf-8").write(s)


def caixa(ax, x, y, w, h, titulo, detalhe="", cor=REF, fundo="#FFFFFF", tam=12):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.6, edgecolor=cor, facecolor=fundo))
    if detalhe:
        ax.text(x + w / 2, y + h * 0.63, titulo, ha="center", va="center", fontsize=tam, fontweight="bold", color=ESCURO)
        ax.text(x + w / 2, y + h * 0.30, detalhe, ha="center", va="center", fontsize=tam - 1.5, color=TEXTO2)
    else:
        ax.text(x + w / 2, y + h / 2, titulo, ha="center", va="center", fontsize=tam, fontweight="bold", color=ESCURO)


def seta(ax, a, b, texto="", cor="#6B7280", estilo="-|>", ls="-", tam=10.5, off=(0, 0.08)):
    ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle=estilo, color=cor, lw=1.5, linestyle=ls,
                                                    shrinkA=2, shrinkB=2, mutation_scale=14))
    if texto:
        ax.text((a[0] + b[0]) / 2 + off[0], (a[1] + b[1]) / 2 + off[1], texto, ha="center", va="bottom",
                fontsize=tam, color=TEXTO2, bbox=dict(facecolor="white", edgecolor="none", pad=1))


def tela(w=LARGURA, h=4.2):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10 * h / w); ax.axis("off"); ax.set_aspect("equal")
    return fig, ax


def capa(caminho, titulo, subtitulo_txt, desenhar_miniatura):
    """Capa 1200x627 para pré-visualização de links: fundo escuro, título, subtítulo e miniatura."""
    fig = plt.figure(figsize=(12, 6.27), dpi=100)
    fig.patch.set_facecolor(ESCURO)
    fig.text(0.05, 0.86, titulo, color="white", fontsize=38, fontweight="bold", va="top", wrap=True)
    fig.text(0.05, 0.50, subtitulo_txt, color="#C9D3E0", fontsize=21, va="top")
    fig.text(0.05, 0.07, "mariomenezes.github.io", color="#8FA3BF", fontsize=14)
    ax = fig.add_axes([0.60, 0.10, 0.36, 0.24])
    ax.set_facecolor(ESCURO)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.grid(False); ax.tick_params(colors="#8FA3BF", labelsize=10)
    desenhar_miniatura(ax)
    with plt.rc_context({"savefig.bbox": None}):
        fig.savefig(caminho, dpi=100, facecolor=ESCURO)
    plt.close(fig)
