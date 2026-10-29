---
title: "RAG in homelab with visibility"
lang: en
permalink: /en/2026/10/29/rag-homelab-visibility/
description: "Minimal RAG architecture in the homelab: Qdrant + incremental indexer + MCP tool in OpenCode, with visibility at every step."
---

*[Leia em português]({{ "/pt/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

---

## The problem

I needed to query my knowledge base (`~/vault/`) from within OpenCode, but I wanted to see what happened at each step — not just the final answer.

## The architecture

```
[PC] --MCP---> [rag-mcp/server.py] --HTTP---> [Qdrant CT301:6333]
                                              ^
                                              |
[CT300:8084] Qwen3-Embedding-0.6B embeddings
      ^
      | Syncthing (receive-only)
[CT128] vault-replica/
      ^
      | Syncthing (send-only)
[CT128] vault/ (hub)
```

### Qdrant (CT 301)

Vector database in a container, port 6333 on the LAN, API key in `/etc/qdrant.env`. I chose Qdrant as the self-hosting standard — no extra complexity.

### Indexer (CT 301)

Incremental script at `/usr/local/bin/rag-indexer.py`:
- File hashing to detect changes.
- Chunking by Markdown titles (1000 chars, 150 overlap).
- Skips files with secret patterns and files starting with `_`.
- Hourly timer via `rag-indexer.timer`.

### Embeddings (CT 300:8084)

Qwen3-Embedding-0.6B, 1024 dimensions, cosine distance. Ran separately because the embedding model is lightweight (~2GB) and doesn't compete for VRAM with large models.

### MCP Tool (local PC)

`buscar_vault` registered in `opencode.json` as `rag-vault`. Each query is logged in `~/.local/state/rag-mcp/consultas.log`.

## Tests

- Query "como reinicio o roteador": the right snippet came first (score 0.57).
- Repeated indexer run: skipped the 6 unchanged files.
- OpenCode called the tool and answered citing the source files.

## Fix: duplicate snippets

The initial search returned duplicate snippets from the same file. Fixed in both the MCP tool and `rag-search.py`: now returns at most one snippet per file.

## CT 301 reboot — test

Auto-started after reboot:
- vllm-sr (8 containers)
- Qdrant
- Replica Syncthing
- Indexer timer
- Proxies and Dashboard

After reboot: Qdrant search working, request routed to XTX (HTTP 200), incremental indexer (2 changed files reindexed), MCP tool responding.

## Observation: router unavailability

The router was down for several minutes during the reboot. llama-router containers don't auto-start with the host. This is a point to improve in the next iteration.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
