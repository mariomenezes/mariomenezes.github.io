---
title: "RAG in a homelab with visibility: what I measured, and why the embedding score is not a filter"
lang: en
permalink: /en/2026/10/29/rag-homelab-visibilidade/
description: "Lab notes: semantic search over my infrastructure notes (Qdrant, incremental indexer, MCP tool in OpenCode), with measured latency and a finding about scores that matters if you are thinking of using a threshold."
---

*[Leia em português]({{ "/pt/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

I wanted the coding assistant to query my infrastructure notes (plans, reports, homelab docs) **and I wanted to see every step** of the query, not just the final answer. This post describes the setup, shows what I measured, and records an uncomfortable finding: the embedding score does not separate a hit from a question that has nothing to do with the notes.

This is a personal lab with a small corpus. The numbers hold for this environment, and the limits are at the end.

<div class="tiles">
<div class="tile"><div class="tile-value">~12 ms</div><div class="tile-label">median time to embed the question (3 repetitions per question, 11 questions)</div></div>
<div class="tile"><div class="tile-value">~5 ms</div><div class="tile-label">median vector database search time</div></div>
<div class="tile"><div class="tile-value">5 of 9</div><div class="tile-label">questions with the expected file ranked 1st (6 of 9 in the top 3)</div></div>
</div>

## Summary

- **The setup is small and every step leaves a trace.** A vector database, an incremental indexer, an embedding server, and an MCP tool that logs every query.
- **Search is cheap.** About 17 ms for embedding plus search; the real cost of a query is the model that reads the result.
- **The absolute score is useless as a threshold.** Off-topic questions (cake recipe, weather forecast) scored 0.60 on the first result. Legitimate hits ranged from 0.57 to 0.87.
- **I accidentally indexed my own experiments.** 890 of the 972 chunks (92%) come from benchmark data stored in the vault, and a single one of those files shows up in the top 3 for 10 of 11 questions.

## The architecture

<pre class="mermaid">
flowchart LR
  subgraph PC["Work PC"]
    V["vault (Markdown)"]
    O["OpenCode"]
    M["MCP tool buscar_vault"]
  end
  subgraph LAB["Lab servers"]
    H["Syncthing hub"]
    R["read-only replica"]
    I["indexer (hourly)"]
    Q["Qdrant"]
    E["embedding server"]
  end
  V -->|Syncthing| H
  H -->|receive-only| R
  R --> I
  I -->|"chunk embeddings"| E
  I -->|"upsert"| Q
  O --> M
  M -->|"question embedding"| E
  M -->|"cosine search"| Q
  M -. "log of every query" .-> L["consultas.log"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

Decisions behind the design:

- **Index from a replica, not from the vault directly.** The vault lives on my PC; the indexer runs on a server that stays on. A *receive-only* replica guarantees nothing from the server flows back and alters the notes.
- **Vector database: Qdrant**, because it is the self-hosting default and needs nothing else.
- **MCP tool on the PC**, because that is where OpenCode runs.

## The indexer

| Parameter | Value |
|---|---|
| Change detection | file hash (incremental) |
| Chunking | by Markdown headings, 1000 characters, 150 overlap |
| Embeddings | Qwen3-Embedding-0.6B, 1024 dimensions, cosine distance |
| Exclusions | files matching a secret pattern and files starting with `_` |
| Schedule | hourly timer |

A second run with no changes skipped the 6 files that existed at the time. After restarting the server, the indexer reindexed only the 2 changed files.

## Visibility: the query log

The tool writes one line per query, with the question, the requested `k`, and the files returned. That log is what made me notice the problem in the next section: all it took was reading it and seeing data files show up for questions that had nothing to do with them.

An earlier fix also came from the log: search used to return several chunks from the same file. Now the tool fetches `4k` candidates and returns at most one chunk per file.

## What I measured

I asked 11 questions: 9 with a target file that I picked before looking at the result, and 2 unrelated to the vault. Each question ran 3 times for latency. The script is in the drafts repository, next to the raw data.

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/score-top1-en.svg" | relative_url }}" alt="Horizontal bars with the first-result score for 11 questions. Hits in green range from 0.57 to 0.87, misses in orange from 0.53 to 0.68, and the two off-topic questions in grey sit at 0.60." loading="lazy">
<figcaption>First-result score per question. The two questions unrelated to the vault (grey) scored 0.60, inside the range of the hits (green). Any threshold that cuts the off-topic questions also cuts legitimate hits.</figcaption>
</figure>

Three readings of the chart:

1. **There is no absolute threshold.** A cutoff at 0.60 would drop the 0.57 hit (sleeping/GPU) and let both off-topic questions through.
2. **The highest scores coincide with single-file topics.** "RDS" and "Grafana" reach 0.83 and 0.87, and each has a dedicated file; topics that appear in several files land between 0.53 and 0.68. My hypothesis is rare vocabulary, but I did not test it.
3. **Some of the "misses" are the corpus's doing.** For "how do I restart the router", first place (0.668) was a tie between the evaluation pack and a report that describes restarting the server; the file I had marked as the target was not even in the top 4. My labeling was a guess, and the index disagreed in a defensible way.

## The finding: I indexed my own benchmark

The index has 972 chunks from about 50 Markdown files. I counted by path: **890 chunks (92%) come from the benchmark data directory**, which I stored in the vault, and only 82 come from the actual notes. A single file, the pilot evaluation pack, accounts for 501 chunks (52% of the index) and appears in the top 3 for **10 of 11** questions, including both off-topic ones.

That file is huge and mixes prompts from many subjects (Terraform, Kubernetes, shell). It has so many chunks, and so varied, that one of them is almost always close to the question. Add the known hubness effect (documents that become neighbors of many things in embedding space) and it pollutes the ranking.

What I would do, not yet applied:

- **Exclude data and raw-output directories from the index**, by path rather than only by the `_` prefix.
- **Use relative rank, not the absolute score**, and show the score to the model as information only, never as a filter.
- **Measure recall on a fixed question set** after every corpus change. The script from this measurement does the job.

## Limits

- 11 questions, 9 of them with a target I picked: this is a smoke test, not a recall measurement.
- A single embedding model, with no comparison against another model or keyword search.
- Latency measured on the local network, with the embedding server already warm.
- The corpus changed during the experiment (the benchmark outputs were indexed by the hourly timer).
- Pending: testing the model servers coming back after a reboot; only the vector database server was tested.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
