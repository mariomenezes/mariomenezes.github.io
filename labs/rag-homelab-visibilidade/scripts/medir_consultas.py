"""Medicao 2: antes/depois de excluir dados/ (filtro no cliente), variacao de latencia (30 repeticoes) e erros.
Segredos vem do arquivo apontado por RAG_ENV (fora do repositorio)."""
import json, os, time, statistics, urllib.request

ENV = {}
for line in open(os.environ.get("RAG_ENV", "rag.env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v

def post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(req, timeout=60))

QUERIES = json.load(open(os.environ.get("QUERIES", "data/queries.json")))
ERR = 0

def embed(q):
    global ERR
    try:
        return post(ENV["EMB_URL"] + "/v1/embeddings", {"input": [q]}, {"Authorization": "Bearer " + ENV["EMB_KEY"]})["data"][0]["embedding"]
    except Exception:
        ERR += 1; raise

def search(vec, limit=64):
    return post(f"{ENV['QDRANT_URL']}/collections/vault/points/search",
                {"vector": vec, "limit": limit, "with_payload": ["path"]}, {"api-key": ENV["QDRANT_KEY"]})["result"]

def ranking(hits, excluir=None):
    seen, out = set(), []
    for h in hits:
        p = h["payload"]["path"]
        if excluir and excluir in p: continue
        if p in seen: continue
        seen.add(p); out.append((p, round(h["score"], 3)))
    return out

res = []
for q in QUERIES:
    vec = embed(q["q"]); hits = search(vec)
    antes, depois = ranking(hits), ranking(hits, "dados/")
    def pos(r):
        return next((i + 1 for i, (p, s) in enumerate(r) if p == q["esperado"]), None) if q["esperado"] else None
    res.append({"q": q["q"], "esperado": q["esperado"], "antes": antes[:4], "depois": depois[:4],
                "pos_antes": pos(antes), "pos_depois": pos(depois)})

# latencia: 30 repeticoes de 3 perguntas
lat = {"embed": [], "busca": [], "total": []}
for _ in range(10):
    for q in QUERIES[:3]:
        t0 = time.perf_counter(); vec = embed(q["q"]); t1 = time.perf_counter(); search(vec, 16); t2 = time.perf_counter()
        lat["embed"].append((t1 - t0) * 1000); lat["busca"].append((t2 - t1) * 1000); lat["total"].append((t2 - t0) * 1000)

def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))]
summ = {k: {"p50": round(statistics.median(v), 1), "p95": round(pct(v, 95), 1), "min": round(min(v), 1), "max": round(max(v), 1), "n": len(v)} for k, v in lat.items()}
json.dump({"consultas": res, "latencia_ms": summ, "erros": ERR, "lat_raw": lat}, open(os.environ.get("SAIDA", "data/resultado_consultas.json"), "w"), ensure_ascii=False, indent=1)
lab = [r for r in res if r["esperado"]]
for nome, key in (("antes", "pos_antes"), ("depois", "pos_depois")):
    t1 = sum(1 for r in lab if r[key] == 1); t3 = sum(1 for r in lab if r[key] and r[key] <= 3)
    print(nome, "top1", t1, "top3", t3, "de", len(lab))
for r in res:
    print(f"{r['q'][:44]:44} esp={r['pos_antes']}->{r['pos_depois']} top1_antes={r['antes'][0][1]} top1_depois={r['depois'][0][1] if r['depois'] else None}")
print(summ, "erros", ERR)
