#!/usr/bin/env python3
"""Servidor MCP (stdio) com uma ferramenta: buscar_vault. Busca semantica no Qdrant.
Cada consulta e registrada em $RAG_MCP_LOG_DIR/consultas.log (visibilidade do processo).
"""
import json, os, sys, time, urllib.request

ENV = {}
for line in open(os.environ.get("RAG_ENV", "rag.env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        ENV[k] = v

LOG_DIR = os.environ.get("RAG_MCP_LOG_DIR", "rag-mcp-log")
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg):
    with open(os.path.join(LOG_DIR, "consultas.log"), "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")

def post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(req, timeout=60))

def buscar(query, k=4):
    vec = post(ENV["EMB_URL"] + "/v1/embeddings", {"input": [query]},
               {"Authorization": "Bearer " + ENV["EMB_KEY"]})["data"][0]["embedding"]
    res = post(f"{ENV['QDRANT_URL']}/collections/vault/points/search",
               {"vector": vec, "limit": k * 4, "with_payload": True}, {"api-key": ENV["QDRANT_KEY"]})
    hits, vistos = [], set()
    for h in res["result"]:
        p = h["payload"]
        if p["path"] in vistos:
            continue
        vistos.add(p["path"])
        hits.append(f"[{h['score']:.2f}] {p['titulo']} ({p['path']}, trecho {p['chunk']})\n{p['texto']}")
        if len(hits) == k:
            break
    log(f"consulta={query!r} k={k} resultados={list(vistos)}")
    return "\n\n---\n\n".join(hits) if hits else "Nenhum trecho encontrado."

TOOLS = [{
    "name": "buscar_vault",
    "description": "Busca semantica na base de conhecimento pessoal (vault: planos, relatorios e documentacao de infraestrutura). Use antes de propor mudancas de infraestrutura ou quando o usuario perguntar sobre decisoes passadas.",
    "inputSchema": {"type": "object", "properties": {
        "query": {"type": "string", "description": "Pergunta ou termos a buscar"},
        "k": {"type": "integer", "description": "Quantidade de trechos (padrao 4)", "default": 4}},
        "required": ["query"]},
}]

def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                "serverInfo": {"name": "rag-vault", "version": "0.1"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        args = msg["params"].get("arguments", {})
        try:
            texto = buscar(args["query"], int(args.get("k", 4)))
            return {"content": [{"type": "text", "text": texto}]}
        except Exception as e:
            log(f"erro: {e}")
            return {"content": [{"type": "text", "text": f"Erro na busca: {e}"}], "isError": True}
    return None

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("id") is None:
        continue
    result = handle(msg)
    if result is None:
        out = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "metodo nao suportado"}}
    else:
        out = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()
