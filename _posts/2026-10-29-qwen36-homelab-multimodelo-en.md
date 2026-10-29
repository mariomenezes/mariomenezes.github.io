---
title: "Qwen3.6 in homelab: multimodel with one GPU"
lang: en
permalink: /en/2026/10/29/qwen36-homelab-multimodel/
description: "How to squeeze the most from one GPU in Proxmox: hot model, warm fallback pool, small code model separate, dedicated embedding server."
---

*[Leia em português]({{ "/pt/2026/10/29/qwen36-homelab-multimodelo/" | relative_url }})*

---

## The hardware

- Proxmox host, GPU 0: older generation card, limited VRAM.
- Proxmox host, GPU 1: secondary card for smaller models.
- Two containers: CT 300 (models), CT 301 (router + Qdrant).

## The strategy: one model per GPU, no VRAM splitting

Instead of trying to load multiple models on the same GPU (which causes OOM or swapping), I put **one server per GPU**:

### GPU 0 — Heavy model (always loaded)

```
Port: 8080
Model: Qwen3.6-35B-A3B-Q4_K_M
Mode: sleeping disabled (always in memory)
VRAM: ~20 GB continuously occupied
```

### GPU 1 — Code + Embedding

```
GPU 1a: FIM + Qwen2.5-Coder-3B (port 8083)
GPU 1b: Embeddings + Qwen3-Embedding-0.6B (port 8084)
```

The separation makes sense: the code model is lightweight (~6GB) and the embedding is even smaller (~2GB). Both run in parallel on GPU 1 without competing with the 35B.

## What I did with Qwen3.8-27B

The Qwen3.8-27B-Q6_K.gguf took 30 GB and was already superseded by Qwen3.6-35B-A3B. Deleted the file and confirmed nothing else referenced it. GPU 0 now has a larger model (35B) with the same quantization (Q4) — more parameters, same VRAM footprint.

## Hot vs cold decision

Keeping qwen3-14b always loaded on GPU 0 costs ~40W continuously, but eliminates ~19s of loading on fallback. Chose hot. Alternative would be:

- **Sleeping mode:** frees VRAM when idle, but the child process keeps GPUs at 100% usage.
- **Unload timer:** unloads sleeping models via API every 2 min. GPU returns to normal.

## What I learned

1. **Don't split GPUs for large models:** one per GPU is more stable than trying to split.
2. **Q4 > Q6 for VRAM:** Qwen3.6-35B at Q4 uses ~20GB; Qwen3.8-27B at Q6 used 30GB. Fewer bits = more room for other models.
3. **Always-loaded has a cost:** 40W is cheap compared to 19s of loading for a user.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
