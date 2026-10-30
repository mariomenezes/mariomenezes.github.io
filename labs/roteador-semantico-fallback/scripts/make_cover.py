"""Capa 1200x627 do post (pt e en). Números do teste de queda descrito no post: 10/10 pedidos
no fallback com a principal fora do ar e 10/10 na principal depois que ela voltou.
Uso: python3 make_cover.py <pasta_saida>"""
import sys
from estilo import *
OUT = sys.argv[1]
for lang, tit, sub, rot in (
    ("pt", "Roteador de modelos com\nfallback no homelab", "Queda real da fonte principal:\n10 de 10 pedidos no fallback.", ["fallback (principal fora)", "principal (de volta)"]),
    ("en", "A model router with\nfallback in my homelab", "A real outage of the main source:\n10 of 10 requests on the fallback.", ["fallback (main down)", "main (back up)"])):
    def mini(ax, rot=rot):
        ax.barh([1, 0], [10, 10], color=[FOCO, REF], height=0.55)
        for y, r in zip([1, 0], rot):
            ax.text(0.3, y, r, va="center", color="white", fontsize=12, fontweight="bold")
        ax.set_xlim(0, 10); ax.set_yticks([]); ax.set_xticks([0, 10])
    capa(f"{OUT}/cover-{lang}.png", tit, sub, mini)
print("ok")
