import json, os, time, urllib.request, statistics
ENV = {}
for line in open(os.environ.get("RAG_ENV", "rag.env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); ENV[k] = v

def post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(req, timeout=60))

Q = [(x["q"], x["esperado"]) for x in json.load(open(os.environ.get("QUERIES", "data/queries.json")))]
rows = []
for q, esp in Q:
    for rep in range(3):
        t0 = time.time()
        vec = post(ENV["EMB_URL"] + "/v1/embeddings", {"input": [q]}, {"Authorization": "Bearer " + ENV["EMB_KEY"]})["data"][0]["embedding"]
        t1 = time.time()
        res = post(f"{ENV['QDRANT_URL']}/collections/vault/points/search", {"vector": vec, "limit": 16, "with_payload": True}, {"api-key": ENV["QDRANT_KEY"]})["result"]
        t2 = time.time()
        if rep == 0:
            seen, top = [], []
            for h in res:
                p = h["payload"]["path"]
                if p not in seen:
                    seen.append(p); top.append((p, round(h["score"], 3)))
            rows.append({"q": q, "esperado": esp, "top": top[:4], "emb_ms": [], "qd_ms": []})
        rows[-1]["emb_ms"].append((t1 - t0) * 1000); rows[-1]["qd_ms"].append((t2 - t1) * 1000)

req = urllib.request.Request(f"{ENV['QDRANT_URL']}/collections/vault", headers={"api-key": ENV["QDRANT_KEY"]})
col = json.load(urllib.request.urlopen(req, timeout=30))["result"]
out = {"pontos": col.get("points_count"), "rows": rows}
json.dump(out, open(os.environ.get("SAIDA", "data/resultado_baseline.json"), "w"), ensure_ascii=False, indent=1)
print("pontos:", col.get("points_count"))
for r in rows:
    t1 = r["top"][0] if r["top"] else None
    ok = (t1 and t1[0] == r["esperado"]) if r["esperado"] else None
    pos = next((i + 1 for i, (p, s) in enumerate(r["top"]) if p == r["esperado"]), None)
    print(f"{r['q'][:48]:48} top1={t1[1] if t1 else None} ok={ok} pos={pos} emb={statistics.median(r['emb_ms']):.0f}ms qd={statistics.median(r['qd_ms']):.0f}ms")
