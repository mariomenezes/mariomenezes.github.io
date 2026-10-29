---
title: "RAG em homelab com visibilidade"
lang: pt-BR
permalink: /pt/2026/10/29/rag-homelab-visibilidade/
description: "Arquitetura mínima de RAG no homelab: Qdrant + indexador incremental + ferramenta MCP no OpenCode, com visibilidade de cada etapa."
---

*[Read in English]({{ "/en/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

---

## O problema

Eu precisava consultar a base de conhecimento (`~/vault/`) de dentro do OpenCode, mas queria ver o que acontecia em cada etapa — não apenas a resposta final.

## A arquitetura

```
[PC] --MCP---> [rag-mcp/server.py] --HTTP---> [Qdrant CT301:6333]
                                              ^
                                              |
[CT301:8084] embeddings Qwen3-Embedding-0.6B
      ^
      | Syncthing (receive-only)
[CT128] vault-replica/
      ^
      | Syncthing (send-only)
[CT128] vault/ (hub)
```

### Qdrant (CT 301)

Banco vetorial no container, porta 6333 na LAN, chave de API em `/etc/qdrant.env`. Escolhi Qdrant por ser o padrão de self-hosting — sem complexidade extra.

### Indexador (CT 301)

Script incremental em `/usr/local/bin/rag-indexer.py`:
- Hash de arquivo para detectar mudanças.
- Chunking por titulos Markdown (1000 chars, 150 de sobreposição).
- Pula arquivos com padrao de segredo e arquivos que comecam com `_`.
- Timer a cada hora via `rag-indexer.timer`.

### Embeddings (CT 300:8084)

Qwen3-Embedding-0.6B, 1024 dimensões, distancia cosseno. Rodei separado porque o modelo de embedding é leve (~2GB) e não compete por VRAM com os modelos grandes.

### Ferramenta MCP (PC local)

`buscar_vault` registrada no `opencode.json` como `rag-vault`. Cada consulta fica em `~/.local/state/rag-mcp/consultas.log`.

## Testes

- Pergunta "como reinicio o roteador": o trecho certo ficou em primeiro lugar (score 0,57).
- Execucao repetida do indexador: pulou os 6 arquivos sem mudanca.
- OpenCode chamou a ferramenta e respondeu citando os arquivos de origem.

## Ajuste: trechos repetidos

A busca inicial devolvia trechos duplicados do mesmo arquivo. Corrigido na ferramenta MCP e no `rag-search.py`: agora devolve no maximo um trecho por arquivo.

## Reboot do CT 301 — teste

Subiram sozinhos após o reboot:
- vllm-sr (8 containers)
- Qdrant
- Syncthing da replica
- Timer do indexador
- Proxies e Dashboard

Apos o reboot: busca no Qdrant funcionando, pedido roteado para a XTX (HTTP 200), indexador incremental (2 arquivos alterados reindexados) e ferramenta MCP respondendo.

## Observação: indisponibilidade do roteador

O roteador ficou fora por alguns minutos durante o reboot. Os containers do llama-router nao sobem automaticamente com o host. Isso é um ponto a melhorar para a próxima iteracao.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
