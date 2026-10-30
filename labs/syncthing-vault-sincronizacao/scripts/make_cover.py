"""Capa 1200x627 do post (pt e en), a partir de data/sync_medida.json (10 execuções).
Uso: python3 make_cover.py <sync_medida.json> <pasta_saida>"""
import json, sys
from estilo import *
D = json.load(open(sys.argv[1])); OUT = sys.argv[2]
for lang, tit, sub in (
    ("pt", "Syncthing entre sub-redes:\ndo zero, com réplica só leitura", "Uma nota chega ao servidor em ~9 s\n(10 execuções)."),
    ("en", "Syncthing across subnets:\nfrom scratch, read-only replica", "A note reaches the server in ~9 s\n(10 runs).")):
    def mini(ax):
        ax.plot([d["run"] + 1 for d in D], [d["replica_s"] for d in D], "o-", color=FOCO, lw=2, ms=7)
        ax.set_ylim(0, 15); ax.set_yticks([0, 9, 15]); ax.set_xticks([1, 10])
    capa(f"{OUT}/cover-{lang}.png", tit, sub, mini)
print("ok")
