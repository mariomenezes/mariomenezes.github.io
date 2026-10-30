---
title: "RAG in a homelab: 92% of my index was noise, and the query log showed it"
lang: en
permalink: /en/2026/10/29/rag-homelab-visibilidade/
description: "Lab notes: semantic search over my infrastructure notes (Qdrant, incremental indexer, MCP tool in OpenCode), with measured latency, the full environment and step-by-step reproduction. The finding: benchmark data stored in the vault became 92% of the index, and excluding it rebuilt the ranking."
image: /assets/img/rag-homelab-visibilidade/cover-en.png
---

*[Leia em português]({{ "/pt/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

<p class="status"><span class="pill">Lab</span> <span>Version 2 · October 29, 2026 · <a href="#what-changed">what changed</a></span></p>

I built a semantic search over my infrastructure notes for the coding assistant to query, with a log of every query so I can see what happens. In the second hour of use the indexer went from **64 to 971 chunks in a single run**, because I had stored benchmark data in the vault. **92% of the index (890 of 972 chunks) stopped being notes and became raw data**, and one single file accounted for 52%. This post shows how I measured it, what changed in the ranking once I excluded those directories from the indexer (the fix is applied), and how to repeat the experiment.

This is a personal lab, not production, with a small corpus. The numbers hold for this environment; the limits come right after the summary.

<div class="tiles">
<div class="tile"><div class="tile-value">92%</div><div class="tile-label">of the 972 index chunks came from benchmark data, not notes (890 of 972)</div></div>
<div class="tile"><div class="tile-value">4 → 8</div><div class="tile-label">questions (of 9) with the expected file in the top 3, before and after rebuilding the index without that data (972 → 82 chunks)</div></div>
<div class="tile"><div class="tile-value">~20 ms</div><div class="tile-label">median of a full query (embedding + search): 20.6 ms with 972 chunks, 19.7 ms with 82; 30 repetitions each, 0 errors</div></div>
</div>

## Summary

- **The indexer only excluded files by prefix (`.` and `_`), not by directory.** The benchmark data entered at the next hourly run: 6 to 50 files, 64 to 971 chunks, 48 s.
- **I applied a directory exclusion and reindexed: 972 → 82 chunks.** The expected file was ranked 1st in 4 of 9 questions (before: 3) and in the top 3 in 8 of 9 (before: 4).
- **Off-topic questions dropped from 0.60 to 0.44 and 0.48 top-1 score**, below every question that has a target file (minimum 0.53). The margin is 0.05 and the sample has only 2 off-topic questions, so I do not recommend a threshold yet.
- **The simulation I ran before touching the index (filtering `dados/` on the client) gave the same result as the rebuilt index, on 11 of 11 questions**, with the same rank and the same score.
- **A query is cheap and does not depend on index size at this scale:** 19.7 ms median with 82 chunks and 20.6 ms with 972. The question embedding accounts for about 80% of the time. In both cases Qdrant does not use HNSW; it scans exactly.
- **The secret guard worked:** it skipped 2 synthetic files that contained fake tokens.

<div class="callout">
<p><strong>Before reading the numbers:</strong></p>
<ul>
<li>There are 11 questions, 9 with a target file that <strong>I</strong> picked before looking at the result. This is a smoke test, not a recall measurement.</li>
<li>After the cleanup the index has only <strong>7 files</strong>. Landing in the top 3 happens by chance about 43% of the time (≈ 4 of 9); ranking 1st, about 14% (≈ 1.3 of 9). Ranking 1st is the metric that matters here.</li>
<li>One embedding model, with no comparison against another model or keyword search.</li>
</ul>
</div>

## What changed in this version {#what-changed}

<div class="callout">
<p>The first version of this post, published and withdrawn on the same day, concluded that <strong>the embedding score is no good as a filter</strong>, because off-topic questions scored 0.60. I had not tested the ranking without the benchmark data. When I did, the conclusion changed:</p>
<ul>
<li>the main problem was the <strong>polluted corpus</strong>, not the score;</li>
<li>two questions from the first version were replaced by neutral questions about the homelab, so the before and after numbers changed (for example, the expected file in the top 3 went from 6 to 4 before the cleanup);</li>
<li>the first version also exposed container numbers and an internal path that should not have been published, and carried only a simple measurement, with no environment and no steps to repeat it. Everything was removed or redone.</li>
</ul>
</div>

## Environment

| Item | Value |
|---|---|
| Host | AMD Ryzen 5 5600G (12 threads), 62 GB RAM, Proxmox VE 8.4.19, kernel 6.14.11 |
| Host GPUs | two AMD cards with PCI ID 1002:7590, 16 GB each (the commercial name is not in the host's `pci.ids`) |
| Embedding server | llama.cpp build `b216-f12cc6d`, Vulkan on GPU 1, Qwen3-Embedding-0.6B quantized to Q8_0, context 4096, 4 slots, 2 threads |
| Vector database | Qdrant 1.20.0 in a container, named volume, API key |
| Collection | 1024 dimensions, cosine distance, default HNSW (m=16, ef_construct=100), 2 segments |
| Vault replica | Syncthing 1.19.2, folder in *receive-only* mode |
| Indexer | Python 3.11.2, run hourly by a systemd timer |
| Client | OpenCode v2.2.1, local MCP tool over stdio |
| Network | same LAN for the work PC, the embedding server and Qdrant |
| Index before / after | 50 files and 972 chunks / 7 files and 82 chunks |
| State during measurement | embedding server warmed by 11 earlier queries in the same script |

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/ambiente-en.svg" | relative_url }}" alt="Environment diagram: the work PC, with the vault, OpenCode and the MCP tool, connects over the LAN to a Proxmox host with three blocks: a services container with Qdrant, Syncthing and the indexer; GPU 0, with the router fallback model, outside the RAG; and GPU 1, with the Qwen3-Embedding-0.6B embedding server and code completion." loading="lazy">
<figcaption>Experiment environment. In blue, what takes part in the RAG; in grey, what runs on the same host but does not.</figcaption>
</figure>

GPUs 0 and 1 also serve other services (the router and code completion). Only GPU 1 takes part in the RAG, because of the embedding server.

## The architecture

Data flows one way from the PC to the server, and a query goes the other way only as far as Qdrant.

<pre class="mermaid">
flowchart LR
  V["vault on the PC"] -->|Syncthing| R["receive-only replica"]
  R --> I["indexer"]
  I -->|"chunks"| E["embedding server"]
  I -->|"upsert"| Q["Qdrant"]
  O["OpenCode"] --> M["MCP buscar_vault"]
  M -->|"question"| E
  M -->|"search"| Q
  M -.->|"log"| L["consultas.log"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

- **Index from a replica**, not from the vault directly: the vault lives on the PC, the indexer on an always-on server. The *receive-only* folder keeps anything on the server from flowing back and altering the notes.
- **Incremental indexer:** SHA-256 per file, 1000-character chunks with 150 overlap, split first by Markdown heading. It skips files that start with `.` or `_`, directories listed in `EXCLUDE_DIRS`, and files that match a secret pattern (AWS keys, GitHub tokens, private keys, `password`/`token` followed by a value).
- **MCP tool:** gets the question embedding, fetches 4k candidates from Qdrant and returns at most one chunk per file. Every query becomes a line in `consultas.log`, with the question, `k` and the files returned.

## How to reproduce

Prerequisites: Docker, Python 3.11 or newer, a llama.cpp `llama-server` (Vulkan, ROCm, CUDA or CPU) and the `Qwen3-Embedding-0.6B-Q8_0.gguf` file. Estimated time: 30 to 45 minutes. All the material is in [`labs/rag-homelab-visibilidade/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/rag-homelab-visibilidade); values in `<...>` are placeholders.

1. **Qdrant.** Run `config/qdrant.sh` with an API key of your own. *It worked if* `curl -H "api-key: <KEY>" http://<HOST>:6333/` returns JSON with `"version":"1.20.0"`.
2. **Embedding server.** Use `config/llama-embed.service` (or the equivalent command):

   ```bash
   llama-server -m Qwen3-Embedding-0.6B-Q8_0.gguf -ngl 99 -c 4096 \
     --embeddings --host 0.0.0.0 --port 8084 --api-key <KEY> -t 2
   ```

   *It worked if* `POST /v1/embeddings` with `{"input":["test"]}` returns a vector of 1024 numbers.
3. **Configuration.** Copy `config/rag.env.example` to `rag.env` and fill it in. None of this goes into a repository.
4. **First indexing** (leave `EXCLUDE_DIRS` empty if you want to reproduce the "before"):

   ```bash
   RAG_ENV=rag.env RAG_LOG=rag-indexer.log python3 scripts/rag-indexer.py
   ```

   *It worked if* it prints `resumo: arquivos=N alterados=N ... trechos_totais=M`.
5. **Second run, changing nothing.** *It worked if* `alterados=0` and `duracao` is close to 0 s. This confirms the incremental behavior.
6. **Measure the "before":**

   ```bash
   RAG_ENV=rag.env SAIDA=data/resultado_antes.json python3 scripts/medir_consultas.py
   ```

   Edit `data/queries.json` first, with questions and target files from **your** corpus.
7. **Exclude directories.** In `rag.env`, set `EXCLUDE_DIRS=dados,rascunhos` (directory names, at any level) and run the indexer again. *It worked if* the log shows `removido do indice (arquivo sumiu)` and `trechos_totais` drops.
8. **Measure the "after"** with `SAIDA=data/resultado_depois.json`. The output also includes the filter simulation (`dados/` removed on the client), so you can check whether it matches the rebuilt index.
9. **Timer (optional).** `config/rag-indexer.service` and `config/rag-indexer.timer`, with `systemctl enable --now rag-indexer.timer`.
10. **MCP tool.** Register `scripts/mcp_server.py` as a local MCP (`config/opencode-mcp.json`), with `RAG_ENV` pointing at your `rag.env` in the environment OpenCode is started from. *It worked if* a question asked through OpenCode creates a line in `consultas.log`.
11. **Figures:** `python3 scripts/make_figures.py data <output>` in an environment with matplotlib.

**Variations I did not test:** chunk and overlap size, another embedding model, hybrid search with keywords and a different quantization of the model.

## Results

### 1. What went into the index

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/indice-en.svg" | relative_url }}" alt="Left, a step chart of the number of chunks in the index between 21:28 and 01:49 UTC: 61 to 64 chunks until 22:36, 971 afterwards, 994 at 01:37 and 82 at the end, after the exclusion. Right, a stacked bar with the origin of the 972 chunks: 82 from actual notes, 389 from other benchmark data and 501 from a single file." loading="lazy">
<figcaption>Left: chunks in the index at each indexer run, from the log (UTC). Right: origin of the 972 chunks before the fix. A single file, the pilot benchmark's evaluation pack, has 501 chunks, more than twice all the notes combined. At 01:37 the timer indexed 2 of my draft files (994); at 01:49 I applied the exclusion.</figcaption>
</figure>

| Stage | Value |
|---|---|
| Eligible Markdown files | 50 |
| Skipped by the secret guard | 2 |
| Indexed | 48 |
| Chunks in the index | 972 |
| …from actual notes | 82 (8%) |
| …from the evaluation pack | 501 (52%) |
| …from other benchmark data | 389 (40%) |
| **After the exclusion** | **7 files, 82 chunks** |

The 22:36 UTC run (19:36 local time) reindexed 42 files in 48.1 s. Before that, the index had 6 files. The full history, including the times I toggled the exclusion to measure, is in `data/indexer_historico.csv`.

### 2. The ranking before and after

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/scores-en.svg" | relative_url }}" alt="Dumbbell chart with the first-result score for 11 questions, before (empty circle, 972-chunk index) and after (filled circle, 82-chunk index). Most do not change. Three do: client for the Claude arm goes from 0.68 to 0.56; cake recipe from 0.60 to 0.44; weather forecast from 0.60 to 0.48. A shaded band marks the 0.53 to 0.70 range of the questions that have a target file." loading="lazy">
<figcaption>Top-1 score per question, before (empty circle) and after (filled circle) rebuilding the index without <code>dados/</code>. Where the circles coincide, the top result was not from <code>dados/</code>. The two off-topic questions (grey) leave the range of the questions that have a target.</figcaption>
</figure>

| Metric (9 questions with a target) | Before (972) | After (82) | Δ |
|---|---|---|---|
| Expected file ranked 1st | 3 | 4 | +1 |
| Expected file in the top 3 | 4 | 8 | +4 |
| Top-1 score on the 2 off-topic questions | 0.60 and 0.60 | 0.44 and 0.48 | −0.16 and −0.12 |
| Lowest score among questions with a target | 0.53 | 0.53 | 0 |

Rank of the expected file where something changed:

| Question | Before | After |
|---|---|---|
| embedding model and dimensions | 41st | 5th |
| router routes and priority | 8th | 3rd |
| how do I restart the router | 5th | 3rd |
| how to test the router fallback | 5th | 3rd |
| client for the Claude arm | 4th | 1st |

Four readings:

1. **The cleanup helped where there was pollution, and the rest is the corpus.** Files from `dados/` held 1st place in 4 of the 11 questions before. Afterwards, what sits in front of the target is other notes on the same subject: for "how do I restart the router" and "how to test the fallback", the top result is the RAG report (0.67 and 0.70).
2. **The evaluation pack was a "hub", and the cleanup does not remove the effect, it only moves it.** Before, it appeared in the top 3 for 10 of 11 questions (and 1st for 3). Afterwards, the blog plan, a long note on a broad subject, appears in the top 3 for 10 of 11. With 7 files, that is hard to avoid.
3. **The separation of off-topic questions exists but is narrow:** 0.48 against 0.53. With 2 questions I cannot set a threshold. The next step is to build about 30 off-topic questions and see where the ceiling is.
4. **Part of the "misses" is my own guess.** I marked the targets before looking and kept the labels, even when another note answered the question in a defensible way.

### 3. Latency

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/latencia-en.svg" | relative_url }}" alt="Three strips of dots with 30 measurements each, on the 972-chunk index: question embedding, from 15 to 22 ms, median 16.2; Qdrant search, from 2.7 to 4.8 ms, median 4.3; total, from 17.6 to 27 ms, median 20.6. Vertical marks show the median and the p95." loading="lazy">
<figcaption>30 repetitions (10 of each of 3 questions), on the 972-chunk index. Black bar: median. Dashed red: p95. The question embedding accounts for about 80% of the total time.</figcaption>
</figure>

| Stage | Median (972) | p95 (972) | Median (82) | p95 (82) |
|---|---|---|---|---|
| Question embedding | 16.2 ms | 20.9 ms | 15.7 ms | 20.6 ms |
| Qdrant search | 4.3 ms | 4.7 ms | 4.0 ms | 4.3 ms |
| Total | 20.6 ms | 25.4 ms | 19.7 ms | 24.7 ms |
| Total, min–max | 17.6–27.0 ms | | 16.2–25.0 ms | |

The difference between the two indexes (about 0.3 ms on search) is within measurement variation. In both cases Qdrant did not build the HNSW index: the optimizer's `indexing_threshold` is 10,000 KB per segment, and 972 vectors of 1024 floats take about 3,900 KB. The search scans every vector. That changes at around 2,500 vectors; with a larger corpus, the search latency measured here no longer holds.

## What went wrong

| Symptom | Cause | Fix |
|---|---|---|
| Off-topic questions scoring 0.60; a data file in the top 3 for 10 of 11 queries | Benchmark data stored in the vault; the indexer excluded only by prefix | **Applied:** `EXCLUDE_DIRS=dados,rascunhos` in `rag.env`; the old script has a backup. 972 → 82 chunks |
| 994 chunks at 01:37 | This post's drafts entered the index | `rascunhos` added to the exclusion list |
| Several chunks from the same file in the results | Search returned the best chunks without grouping | Fetch 4k candidates and return one per file |
| 2 files left out of the index | The secret guard matched a fake token in each (`ghp_...` and `sk-dev-...`) | Expected behavior; both are synthetic scenarios |
| Wrong conclusion in the first version of this post | I had not tested the ranking without the benchmark data | Measurement redone and post rewritten |

## The seven verification questions

Based on Brendan Gregg's benchmarking checklist.

| Question | Answer |
|---|---|
| Why not double? | The question embedding is about 80% of the time. I did not investigate whether the bottleneck is HTTP, tokenization or the GPU |
| Was it tuned? | Everything at defaults (HNSW, llama.cpp, 4 slots). Nothing optimized |
| Did it break limits? | No. 4 KB per vector on a LAN, irrelevant to bandwidth or VRAM |
| Did it error? | 0 errors in every run |
| Does it reproduce? | Embedding medians of 15.7 to 16.4 ms across six runs of 30 repetitions. Ranking scores were identical across repeated runs |
| Does it matter? | Only for small corpora; from around 2,500 vectors Qdrant starts building HNSW and the latency changes. And with 7 files, chance explains a good part of "in the top 3" |
| Did it even happen? | Yes: confirmed by the point count in Qdrant, by the indexer log, and by the simulation, which matched the rebuilt index on 11 of 11 |

## Limits

- 11 questions, 9 with a target I picked; far too small a sample for recall.
- After the cleanup there are 7 files; chance explains about 43% of the "in the top 3".
- The "before" required recreating the 972-chunk state: the exclusion was off for a few minutes just to measure. The history is in `indexer_historico.csv`.
- One embedding model, no comparison.
- Latency measured on the LAN, with the embedding server warm.
- Pending: widen the off-topic questions (about 30) and test the model servers coming back after a reboot.

## Material to reproduce

[`labs/rag-homelab-visibilidade/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/rag-homelab-visibilidade): indexing, MCP, measurement and figure scripts; raw data from both measurements and the indexer history; configurations with placeholders.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
