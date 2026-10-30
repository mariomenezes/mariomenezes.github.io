#!/usr/bin/env python3
"""Mede, para cada texto do conjunto rotulado, as probabilidades que o roteador atribui
(P(deep) do sinal hard_choice e P(attack) do sinal inj_choice), a decisao final e o tempo
da chamada; e o embedding do texto (para o classificador alternativo por vizinhanca).

Variaveis de ambiente:
  PREVIEW_URL  URL da API de gestao do roteador, ex.: http://127.0.0.1:<PORTA>  (POST /api/v1/routing/preview)
  EMBED_URL    URL do servidor de embeddings (OpenAI /v1/embeddings), ex.: http://<HOST_EMBED>:8084
  EMBED_KEY    chave do servidor de embeddings (lida do ambiente, nunca gravada)
Uso: python3 medir_calibracao.py conjunto.json medida.json [repeticoes=3]
"""
import json, os, sys, time
import httpx

src, out = sys.argv[1], sys.argv[2]
reps = int(sys.argv[3]) if len(sys.argv) > 3 else 3
cj = json.load(open(src))
itens = [dict(x, tarefa="dificuldade") for x in cj["dificuldade"]] + [dict(x, tarefa="ataque") for x in cj["ataque"]]
P, E, K = os.environ["PREVIEW_URL"].rstrip("/"), os.environ["EMBED_URL"].rstrip("/"), os.environ["EMBED_KEY"]
res = []
with httpx.Client(timeout=60) as c:
    for it in itens:
        corridas = []
        for _ in range(reps):
            t0 = time.perf_counter()
            r = c.post(f"{P}/api/v1/routing/preview", json={"model": "vllm-sr/auto", "messages": [{"role": "user", "content": it["texto"]}]})
            dt = time.perf_counter() - t0
            r.raise_for_status(); d = r.json(); sc = d.get("signal_confidences", {})
            corridas.append({"p_deep": sc.get("decision:hard_choice:deep"), "p_attack": sc.get("decision:inj_choice:attack"),
                             "decisao": d.get("routing_decision"), "ms_cliente": dt * 1000,
                             "ms_sinal_decision": d.get("metrics", {}).get("decision", {}).get("execution_time_ms")})
        e = c.post(f"{E}/v1/embeddings", headers={"Authorization": f"Bearer {K}"}, json={"input": it["texto"]})
        e.raise_for_status()
        res.append({k: it[k] for k in ("id", "tarefa", "rotulo") } | {"grupo": it.get("dominio", it.get("tipo")),
                    "chars": len(it["texto"]), "corridas": corridas, "embedding": e.json()["data"][0]["embedding"]})
        print(it["id"], [round(x["p_deep"] or 0, 3) for x in corridas], [round(x["p_attack"] or 0, 3) for x in corridas], corridas[0]["decisao"], flush=True)
json.dump({"repeticoes": reps, "itens": res}, open(out, "w"))
print("ok", len(res))
