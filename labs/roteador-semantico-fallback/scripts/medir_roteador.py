"""10 pedidos curtos pelo roteador, com caminho de rota e modelo registrados.
Uso: ROUTER_URL=http://<ROTEADOR>:<PORTA>/v1/chat/completions SAIDA=data/rota_medida.json python3 medir_roteador.py
"""
import json, os, time, urllib.request, statistics

ROUTER = os.environ["ROUTER_URL"]
SAIDA = os.environ.get("SAIDA", "rota_medida.json")
rows = []
for i in range(int(os.environ.get("REPETICOES", "10"))):
    body = json.dumps({"model": "vllm-sr/auto", "messages": [{"role": "user", "content": "Responda apenas: ok"}],
                       "max_tokens": 16, "temperature": 0}).encode()
    req = urllib.request.Request(ROUTER, body, {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
        h = {k.lower(): v for k, v in r.headers.items()}
    dt = time.perf_counter() - t0
    rows.append({"i": i, "s": round(dt, 3), "modelo": data.get("model"),
                 "tokens_saida": data.get("usage", {}).get("completion_tokens"),
                 "caminho": h.get("x-vsr-response-path"), "algoritmo": h.get("x-vsr-selected-algorithm")})
    print(rows[-1])
v = [r["s"] for r in rows]
print("mediana", round(statistics.median(v), 3), "min", min(v), "max", max(v))
json.dump(rows, open(SAIDA, "w"), ensure_ascii=False, indent=1)
