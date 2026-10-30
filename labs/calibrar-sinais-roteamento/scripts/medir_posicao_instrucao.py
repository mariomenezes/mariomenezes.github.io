#!/usr/bin/env python3
"""Para os 4 cenarios rotulados deep: P(deep) com (a) so a instrucao, (b) o prompt original
(instrucao + artefatos) e (c) o original com a instrucao repetida no fim.
Rodar na raiz do lab. PREVIEW_URL = API de gestao do roteador.
Uso: python3 scripts/medir_posicao_instrucao.py data/medida_posicao_instrucao.json"""
import json, os, re, sys
import httpx
sys.path.insert(0, os.path.dirname(__file__))
from run_bench_v2 import build_prompt

P = os.environ["PREVIEW_URL"].rstrip("/")


def pdeep(c, txt):
    d = c.post(f"{P}/api/v1/routing/preview", json={"model": "vllm-sr/auto", "messages": [{"role": "user", "content": txt}]}).json()
    return d["signal_confidences"].get("decision:hard_choice:deep")


out = []
with httpx.Client(timeout=120) as c:
    for slug in ["01-k8s-crashloop", "04-terraform-recriacao", "06-mesh-latencia", "07-migracao-banco"]:
        full = build_prompt(slug)
        instr = re.search(r"## Instrução para o modelo\s*\n(.*?)(\n## |\n\*\*Regras)", full, re.S).group(1).strip()
        r = {"id": slug, "chars_instrucao": len(instr), "chars_total": len(full),
             "so_instrucao": pdeep(c, instr), "original": pdeep(c, full), "instrucao_no_fim": pdeep(c, full + "\n\n" + instr)}
        out.append(r); print(r)
json.dump(out, open(sys.argv[1], "w"), indent=1)
