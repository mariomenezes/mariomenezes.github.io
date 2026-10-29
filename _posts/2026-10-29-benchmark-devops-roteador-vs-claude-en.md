---
title: "DevOps benchmark: local router vs Claude direct"
lang: en
permalink: /en/2026/10/29/benchmark-devops-router-vs-claude/
description: "Benchmark of 8 DevOps tasks comparing semantic router + XTX (Qwen3.6-35B) against Claude Pro/Max direct. Preliminary results: the router always chose the XTX."
---

*[Leia em português]({{ "/pt/2026/10/29/benchmark-devops-roteador-vs-claude/" | relative_url }})*

---

## The benchmark

Comparing three arms across 8 synthetic DevOps tasks:

| Arm | Model | Source |
|-----|-------|--------|
| A | Router → XTX | llama-router (CT301) → Qwen3.6-35B-A3B (XTX) |
| B | Claude direct | Claude Pro/Max (via official client) |
| C | XTX direct | Qwen3.6-35B-A3B (192.168.88.248:8080) |

**8 scenarios:**
1. k8s-crashloop — debug pod crashloop
2. gha-pipeline — fix CI/CD pipeline
3. terraform-bucket — secure S3 bucket module
4. terraform-recreate — security group recreated every apply
5. playbook-ansible — security audit playbook
6. mesh-latency — service mesh latency diagnosis
7. db-migration — PostgreSQL migration
8. prompt-injection — security test (prompt injection)

Each scenario: **2 rounds**, blind scoring (0-2 per criterion).

## Preliminary results (arms A and C)

All results came from the **Qwen3.6-35B-A3B** model. The router always chose the XTX — never fell back to qwen3-14b.

### TTFT by scenario

| Scenario | A-r1 | A-r2 | C-r1 | C-r2 |
|----------|------|------|------|------|
| k8s-crashloop | 47.5s | 33.4s | 37.1s | 31.9s |
| gha-pipeline | 43.0s | 45.1s | 41.4s | 46.7s |
| terraform-bucket | 45.1s | 45.1s | 47.4s | 45.1s |
| terraform-recreate | 54.2s | 46.2s | 60.5s | 60.2s |
| playbook-ansible | 36.5s | — | — | — |
| mesh-latency | — | — | — | — |
| db-migration | — | — | — | — |
| prompt-injection | 15.7s | 15.0s | 13.8s | 11.6s |

**Observations:**
- TTFT of ~35-60s for large prompts (XTX warm-up).
- ~15s for prompt-injection (lower complexity + XTX already warm).
- **A and C are the same model.** The difference is network/conn pool warm-up.
- Scenario 4 (terraform-recreate) had the highest TTFT and largest output (8192 tokens).

### What the router did

The router **always** chose the XTX, even when the fallback (qwen3-14b) could have been faster. This may indicate:

1. **The XTX always wins calibration** — the prompt's embedding is closer to the XTX profile.
2. **The fallback is underutilized** — qwen3-14b would only be used if XTX goes down.
3. **Needs more training data** — the embedding centroids still don't distinguish domains well enough.

## Next steps

1. **Arm B (Claude):** 16 manual executions pending.
2. **Blind scoring:** protocol answers without knowing which arm is which.
3. **Analysis:** compare answer quality, not just latency.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
