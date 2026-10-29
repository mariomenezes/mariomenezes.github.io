---
title: "Calibrating routing signals with few examples"
lang: en
permalink: /en/2026/10/29/calibrate-routing-signals/
description: "What goes wrong when calibrating a semantic router with 22 prompts and how to interpret embedding scores when the model changes."
---

*[Leia em português]({{ "/pt/2026/10/29/calibrar-sinais-roteamento/" | relative_url }})*

---

## The problem

When calibrating a semantic router, I needed a reference set of prompts covering the domains the router would encounter day to day. I collected 22 prompts across 5 domains (Terraform, Kubernetes, Ansible, shell, security) and generated embeddings with Qwen3-Embedding-0.6B to see how they cluster.

The result: **signals that look strong in the embedding fail in practice**, and scores depend on the batch.

## The experiment

1. Took 22 prompts from real scenarios (DevOps benchmark pilot).
2. Generated embeddings via port 8084 endpoint (Qwen3-Embedding-0.6B, 1024 dim, cosine).
3. Computed each prompt's distance to domain centroids.
4. Compared with the router's actual choices (all to XTX in this test).

## What went wrong

### 1. Proximity false positives

```
Actual domain → largest distance to its own centroid
---------------------------------------------------------------
Terraform     → 0.702 (prompt p02-tf-sg)
K8s           → 0.956 (prompt p10-rca-mesh)
Shell         → 0.999 (prompt NOVO-hard-3)
Security      → 0.994 (prompt legit-ignore)
```

The `p02-tf-sg` prompt (Terraform security group) has distance 0.702 to the Terraform centroid — the largest of all. It mixes networking concepts (CIDR, ingress, egress) that pull the embedding toward the Kubernetes domain. A router relying only on embedding could send it to the code model.

### 2. Batch-dependent scores

```
Prompt        Embed-1   Embed-2   Difference
----------------------------------------
NOVO-hard-1   0.579     0.536     0.043
NOVO-hard-2   0.561     0.532     0.029
legit-seg     0.369     0.560     0.191
```

The `legit-seg` prompt (legitimate security) jumped from 0.369 to 0.560 between runs. Same question, different embedding. This means **you cannot use a fixed threshold** — the embedding shifts with the batch.

### 3. Weak signals that work

```
Prompt        Distance   Actual domain
--------------------------------------
p03-ansible   0.001       Ansible ✓
p07-shell-du  0.004       Shell ✓
p01-tf-s3     0.029       Terraform ✓
```

Prompts with explicit keywords (`` `ansible-lint` ``, `/var`, `terraform`) have near-zero distance to the centroid. The embedding works when the prompt is **self-referential** — talking about the tool itself.

## Conclusion

With 22 examples and a 1024-dim embedding, router calibration shows clear limits:

- **Fixed thresholds don't work** because the embedding varies per batch.
- **Mixed domains** (Terraform + networking) generate false positives.
- **Strong signals exist** for self-referential prompts, but don't generalize.

The practical solution: use embedding as **one signal among others**, never as a sole decision. Add keyword rules for critical domains, and monitor the distance distribution live.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
