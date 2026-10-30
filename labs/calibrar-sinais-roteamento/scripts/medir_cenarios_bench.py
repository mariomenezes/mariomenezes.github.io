#!/usr/bin/env python3
"""P(deep) e P(attack) do roteador para os 8 cenarios do benchmark (prompts longos, com artefatos).
Rodar na raiz do lab (onde fica cenarios/). PREVIEW_URL = API de gestao do roteador.
Uso: python3 scripts/medir_cenarios_bench.py data/rotulos_cenarios_bench.json data/medida_cenarios_bench.json
Obs.: as 2a e 3a repeticoes de cada texto vem do cache do roteador (mesmo texto); nao medem variacao."""
import json, os, sys, time
import httpx
sys.path.insert(0, os.path.dirname(__file__))
from run_bench_v2 import build_prompt

P = os.environ["PREVIEW_URL"].rstrip("/")
rot = json.load(open(sys.argv[1]))["rotulos"]
res = []
with httpx.Client(timeout=120) as c:
    for slug, lab in rot.items():
        p = build_prompt(slug); runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            d = c.post(f"{P}/api/v1/routing/preview", json={"model": "vllm-sr/auto", "messages": [{"role": "user", "content": p}]}).json()
            sc = d.get("signal_confidences", {})
            runs.append({"p_deep": sc.get("decision:hard_choice:deep"), "p_attack": sc.get("decision:inj_choice:attack"),
                         "decisao": d.get("routing_decision"), "ms_cliente": (time.perf_counter() - t0) * 1000,
                         "ms_sinal_decision": d.get("metrics", {}).get("decision", {}).get("execution_time_ms")})
        res.append({"id": slug, "rotulo": lab, "chars": len(p), "corridas": runs})
        print(slug, lab, round(runs[0]["p_deep"] or 0, 3), runs[0]["decisao"])
json.dump(res, open(sys.argv[2], "w"), indent=1)
