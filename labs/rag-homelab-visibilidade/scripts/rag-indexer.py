#!/usr/bin/env python3
"""Indexador do vault para o Qdrant. Incremental: reindexa so arquivos com hash alterado.

Config em rag.env (variavel RAG_ENV): QDRANT_URL, QDRANT_KEY, EMB_URL, EMB_KEY, VAULT_DIR, COLLECTION, EXCLUDE_DIRS (opcional, lista separada por virgula).
Log em rag-indexer.log (variavel RAG_LOG) (uma linha por arquivo alterado, resumo no fim).
"""
import hashlib, json, logging, os, re, sys, time, urllib.request, uuid

ENV = {}
for line in open(os.environ.get("RAG_ENV", "rag.env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        ENV[k] = v

QDRANT, QKEY = ENV["QDRANT_URL"], ENV["QDRANT_KEY"]
EMB, EKEY = ENV["EMB_URL"], ENV["EMB_KEY"]
VAULT, COL = ENV["VAULT_DIR"], ENV.get("COLLECTION", "vault")
DIM = 1024
EXCLUDE = {d for d in ENV.get("EXCLUDE_DIRS", "").split(",") if d}  # nomes de diretorio a ignorar, em qualquer nivel
CHUNK, OVERLAP, BATCH = 1000, 150, 16
SEGREDO = re.compile(r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:password|senha|api[_-]?key|token)\s*[=:]\s*\S{8,}")

logging.basicConfig(filename=os.environ.get("RAG_LOG", "rag-indexer.log"), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rag")

def http(method, url, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def qdrant(method, path, body=None):
    return http(method, QDRANT + path, body, {"api-key": QKEY})

def embed(texts):
    d = http("POST", EMB + "/v1/embeddings", {"input": texts}, {"Authorization": "Bearer " + EKEY})
    return [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]

def ensure_collection():
    try:
        qdrant("GET", f"/collections/{COL}")
    except urllib.error.HTTPError:
        qdrant("PUT", f"/collections/{COL}", {"vectors": {"size": DIM, "distance": "Cosine"}})
        log.info("colecao %s criada (dim %d, cosine)", COL, DIM)

def parse(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    meta = {"titulo": os.path.splitext(os.path.basename(path))[0], "tags": []}
    body = raw
    if raw.startswith("---\n"):
        head, _, rest = raw[4:].partition("\n---\n")
        body = rest
        for line in head.splitlines():
            if line.startswith("titulo:"):
                meta["titulo"] = line.split(":", 1)[1].strip() or meta["titulo"]
            if line.startswith("tags:"):
                meta["tags"] = re.findall(r"[\w-]+", line.split(":", 1)[1])
    return meta, body

def chunks(body):
    sections, current = [], []
    for line in body.splitlines():
        if line.startswith("#") and current:
            sections.append("\n".join(current)); current = []
        current.append(line)
    if current:
        sections.append("\n".join(current))
    out = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        i = 0
        while i < len(sec):
            out.append(sec[i:i + CHUNK])
            if i + CHUNK >= len(sec):
                break
            i += CHUNK - OVERLAP
    return out

def existing():
    seen, offset = {}, None
    while True:
        body = {"limit": 256, "with_payload": ["path", "sha"], "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        res = qdrant("POST", f"/collections/{COL}/points/scroll", body)["result"]
        for p in res["points"]:
            seen[p["payload"]["path"]] = p["payload"]["sha"]
        offset = res.get("next_page_offset")
        if offset is None:
            return seen

def delete_path(path):
    qdrant("POST", f"/collections/{COL}/points/delete?wait=true",
           {"filter": {"must": [{"key": "path", "match": {"value": path}}]}})

def main():
    t0 = time.time()
    ensure_collection()
    known = existing()
    files = {}
    for root, dirs, names in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in EXCLUDE]
        for n in names:
            if n.endswith(".md") and not n.startswith((".", "_")):
                p = os.path.join(root, n)
                files[os.path.relpath(p, VAULT)] = p
    changed = skipped = failed = 0
    for rel, full in sorted(files.items()):
        raw_bytes = open(full, "rb").read()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        if known.get(rel) == sha:
            skipped += 1
            continue
        try:
            meta, body = parse(full)
            if SEGREDO.search(body):
                log.warning("PULADO (padrao de segredo): %s", rel)
                delete_path(rel)
                failed += 1
                continue
            delete_path(rel)
            parts = chunks(body)
            points = []
            for i in range(0, len(parts), BATCH):
                vecs = embed(parts[i:i + BATCH])
                for j, (txt, v) in enumerate(zip(parts[i:i + BATCH], vecs)):
                    idx = i + j
                    points.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{rel}#{idx}")),
                                   "vector": v,
                                   "payload": {"path": rel, "sha": sha, "titulo": meta["titulo"],
                                               "tags": meta["tags"], "chunk": idx, "texto": txt}})
            if points:
                qdrant("PUT", f"/collections/{COL}/points?wait=true", {"points": points})
            changed += 1
            log.info("indexado %s (%d trechos)", rel, len(parts))
        except Exception as e:
            failed += 1
            log.error("falha em %s: %s", rel, e)
    for rel in set(known) - set(files):
        delete_path(rel)
        log.info("removido do indice (arquivo sumiu): %s", rel)
    total = qdrant("GET", f"/collections/{COL}")["result"]["points_count"]
    msg = (f"resumo: arquivos={len(files)} alterados={changed} sem_mudanca={skipped} "
           f"falhas_ou_pulados={failed} trechos_totais={total} duracao={time.time() - t0:.1f}s")
    log.info(msg)
    print(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("execucao abortada: %s", e)
        print("erro:", e, file=sys.stderr)
        sys.exit(1)
