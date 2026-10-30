---
title: "Multimodel on two 16 GB GPUs: what fits, what does not, and what kept the GPU busy"
lang: en
permalink: /en/2026/10/29/multimodelo-duas-gpus/
description: "Lab notes: how I split language and embedding models across two 16 GB GPUs in a Proxmox host, what did not fit, and why llama.cpp's sleep mode did not free the GPU."
---

*[Leia em português]({{ "/pt/2026/10/29/multimodelo-duas-gpus/" | relative_url }})*

<p class="status"><span class="pill">Lab</span> <span>October 29, 2026 · <a href="#what-went-wrong">what went wrong</a></span></p>

I wanted, on one host, an always-available fallback model, a small model for code completion and an embedding model for the RAG. The host has two 16 GB AMD cards. The question was what fits on each and how to keep the second one idle when it is not in use.

## Summary

- **Models above 14B do not fit on a 16 GB card** at the quantization I used. A 27B model in Q6 took 30 GB on disk and was removed.
- **Each card has a fixed role.** GPU 0 runs the router's fallback model. GPU 1 runs the code completion model and the embedding model.
- **llama.cpp's sleep mode did not free the GPU.** VRAM was released, but the child process kept the card at 100% utilization.
- **The timer only acts on GPU 0.** Every 2 minutes it unloads the sleeping models of the router. The embedding and completion servers on GPU 1 are outside it. In a 5-minute sample, GPU 1 sat at 100% use with no requests in the logs.

## Environment

| Item | Value |
|---|---|
| Host | Ryzen 5 5600G, 62 GB RAM, Proxmox VE 8.4.19 |
| GPU 0 | AMD, 16 GB, Vulkan, router fallback model |
| GPU 1 | AMD, 16 GB, Vulkan, code completion and embeddings |
| Server | llama.cpp, build `b216-f12cc6d` |

Addresses and keys are left out of this text.

## Layout

<pre class="mermaid">
flowchart TB
  H["host: 2 GPUs of 16 GB"]
  H --> G0["GPU 0: Qwen3-14B fallback, always loaded"]
  H --> G1["GPU 1: Qwen2.5-Coder-3B completion (port 8083)"]
  H --> G1b["GPU 1: Qwen3-Embedding-0.6B embeddings (port 8084)"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

Both servers on GPU 1 require an API key. The large models run on the 24 GB card in another machine.

## What did not fit

The 27B model in Q6 took 30 GB on disk. The 35B model in Q4_K_M takes 21.2 GB, a value the server's own API reports. So the host keeps models up to 14B, and heavy reasoning stays on the 24 GB card.

I removed the 27B file after confirming that no script or configuration still referenced it.

## The GPU that stayed busy

llama.cpp's sleep mode releases VRAM when a model is idle. In practice the child process kept the GPU at 100% utilization, and the card ran hot with no useful work. Running with `--poll 0` did not reduce that use.

A timer, every 2 minutes, asks the router to unload the models that are sleeping. That resolved the observed case on GPU 0 (the fallback). In today's sample, GPU 0 sat at 2%.

GPU 1 is different. It hosts two separate servers, for embeddings and completion, that do not go through the router. The timer does not see them. In today's sample GPU 1 sat at 100% for the 5 minutes, with 4.7 GB of VRAM in use, and the logs of both servers show no requests in the last 10 minutes. I did not investigate the cause inside llama.cpp, nor confirm whether the load comes from both servers or just one.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/gpu-en.svg" | relative_url }}" alt="Two panels. On the left, use of both GPUs over 5 minutes: GPU 1 at 100% the whole time and GPU 0 at 2%. On the right, memory in use: 10.4 GB on GPU 0 and 4.7 GB on GPU 1." loading="lazy">
<figcaption>60 readings, one every 5 seconds, over 5 minutes, with no requests in the logs of the GPU 1 servers. A single time window; not a long series.</figcaption>
</figure>

## Cost of keeping the fallback loaded

Keeping the 14B model loaded was a choice. The session report estimates about 40 W continuous, not measured here, in exchange for avoiding about 19 s of loading on the first fallback response.

## What went wrong

| Symptom | Cause | Fix |
|---|---|---|
| 27B model does not fit | 30 GB on a 16 GB card | removed; host kept to models up to 14B |
| GPU 0 busy while idle | child process of sleep mode | timer that unloads the router's models (resolved on GPU 0) |
| GPU 1 at 100% with no requests | embedding and completion servers outside the router, so outside the timer | not resolved; cause not investigated |
| `--poll 0` had no effect | it was not the cause | discarded |

## Limits

- One hardware configuration.
- The GPU sample covers 5 minutes at a single moment.
- The cause of the 100% use on GPU 1 is still open.
- Power draw and temperature were not measured.
- I did not test a full host reboot with every service.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
