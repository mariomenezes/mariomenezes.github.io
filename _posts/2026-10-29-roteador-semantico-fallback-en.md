---
title: "Local semantic router with fallback"
lang: en
permalink: /en/2026/10/29/semantic-router-fallback/
description: "How I configured llama-router on CT 301 to route between the XTX and a 14B local model on fallback."
---

*[Leia em português]({{ "/pt/2026/10/29/roteador-semantico-fallback/" | relative_url }})*

---

## The setup

I have two inference resources:

1. **XTX** (remote machine, `192.168.88.248:8080`): Qwen3.6-35B-A3B-Q4_K_M — the heavy-lifting model for reasoning.
2. **CT 300** (Proxmox, GPU 0): qwen3-14b-Q4_K_M — the local fallback, always loaded.

The **llama-router** runs on CT 301 (10.0.0.30:8081) as a proxy. It receives a prompt, computes the embedding, and decides which backend to route to.

## config.yaml

```yaml
# Simplified
routing:
  model: qwen3-embedding-0.6b
  endpoint: http://10.0.0.29:8084

routes:
  - name: xtx
    url: http://192.168.88.248:8080/v1/chat/completions
    priority: 1
  - name: ct300-local
    url: http://10.0.0.29:8080/v1/chat/completions
    priority: 2
```

The logic is simple: if XTX responds, use it. If it falls, fallback to local. The embedding is used to calibrate the route based on the prompt's domain.

## Fallback latency

When XTX goes down, the fallback loads the model on demand:

```
Total time: ~19 seconds
- HTTP handshake: <100ms
- Model loading: ~18s
- First token: ~1s
```

The trade-off: keeping qwen3-14b in memory continuously costs ~40W, but eliminates 19s of loading. I chose to keep it always loaded.

## What broke

During the CT 301 reboot, the router was down for several minutes. The llama-router containers (8 total) don't auto-start with the host container. I needed to:

1. Create systemd timers for each container.
2. Verify that the embedding server (CT300:8084) is online before starting the router.

Now it starts on its own — but the XTX warm-up time remains a blind spot. If the XTX "sleeps" (inactivity timeout), the first request has high TTFT (~35-60s in the benchmark).

## Decisions

| Decision | Alternative | Why I chose it |
|----------|-------------|----------------|
| Hot fallback (always loaded) | Cold start | 19s > 40W. Users expect response in seconds. |
| Embedding as signal | Keyword rules | Embedding generalizes better across domains. |
| Dynamic threshold | Fixed threshold | Embeddings vary per batch (0.19 swing in one test). |

## Next steps

- Monitor the distance distribution live.
- Add keyword rules for critical domains (security, injection).
- Test the fallback with XTX down in real scenarios.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
