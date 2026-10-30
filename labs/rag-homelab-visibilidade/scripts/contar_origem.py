"""Conta trechos do indice por origem (notas x dados do benchmark). Le segredos do arquivo apontado por RAG_ENV."""
import json, os, urllib.request, collections
ENV = {}
for l in open(os.environ.get("RAG_ENV", "rag.env")):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); ENV[k] = v
c, off = collections.Counter(), None
while True:
    b = {"limit": 256, "with_payload": ["path"]}
    if off is not None: b["offset"] = off
    r = urllib.request.Request(ENV["QDRANT_URL"] + "/collections/vault/points/scroll", json.dumps(b).encode(),
                               {"Content-Type": "application/json", "api-key": ENV["QDRANT_KEY"]})
    d = json.load(urllib.request.urlopen(r))["result"]
    for p in d["points"]:
        path = p["payload"]["path"]
        if "PACOTE-CEGO" in path: c["pacote_cego"] += 1
        elif "/dados/" in path: c["outros_dados"] += 1
        else: c["notas"] += 1
    off = d.get("next_page_offset")
    if off is None: break
print(json.dumps(c)); json.dump(c, open("composicao.json", "w"))
