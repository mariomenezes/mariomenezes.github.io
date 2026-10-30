---
title: "A model router with fallback in my homelab: what I configured and what I tested"
lang: en
permalink: /en/2026/10/29/roteador-semantico-fallback/
description: "Lab notes: a model router in front of two inference sources, with priority order, a local fallback and a test that takes the main source down. Includes what has not been tested yet."
---

*[Leia em português]({{ "/pt/2026/10/29/roteador-semantico-fallback/" | relative_url }})*

<p class="status"><span class="pill">Lab</span> <span>October 29, 2026 · <a href="#limits">limits</a></span></p>

I had two inference sources: a 35B model on a 24 GB AMD card, and a 14B model on a 16 GB card in the services host. I wanted the client (OpenCode) to talk to a single address, requests to go to the large model when it is available, and the 14B model to answer when it goes down.

This post describes the setup, a fallback test I ran and what has not been measured yet. There is no quality benchmark here; it is an account of the setup and one availability test.

## Summary

- **One address for the client.** The router exposes an OpenAI-compatible API and picks the route by request type.
- **Fixed priority order.** The default route is the large model; if it fails, the request goes to the 14B model.
- **Real outage measured:** with the main source down, 10 of 10 requests went to the fallback (0.15 s median). When it came back, 10 of 10 went to the main source (0.11 s).
- **Inconsistency found:** the fallback's description in the configuration says the model loads on demand; the decision recorded in my notes is to keep it always loaded. One of the two is out of date.

## Environment

| Item | Value |
|---|---|
| Main source | Qwen3.6-35B-A3B, Q4_K_M quantization, AMD RX 7900 XTX with 24 GB, Vulkan, separate work machine |
| Fallback | Qwen3-14B, AMD RX 9060 XT with 16 GB, GPU 0 of the host |
| Router | vllm-sr in a container, API on port 8899, `priority` strategy |
| Host | Ryzen 5 5600G, 62 GB RAM, Proxmox VE 8.4.19 |
| Client | OpenCode v2.2.1 |

Network addresses are left out of this text.

## How the router chooses

<pre class="mermaid">
flowchart LR
  C["OpenCode"] --> R["router :8899"]
  R -->|"priority 1"| X["main model (24 GB)"]
  R -->|"on failure"| F["14B fallback (16 GB)"]
</pre>

The configuration has prioritized routes. One blocks requests with direct prompt-injection patterns aimed at the assistant, another sends requests with sensitive data to local models only, another sends investigation or design requests to the large model with reasoning, and the last is the default route: the main model, with the 14B model as the alternative.

An important limit: detection of indirect injection, from text the assistant reads, does not exist in this setup. It only covers the direct case.

## Real outage of the main source

On a day of measurements, the main source went offline without any action from me. The router started answering through the fallback. I measured 10 short requests (16 tokens at most, temperature 0) while it was down, and 10 more after it came back. I did not investigate the cause of the outage.

| State | Route (header) | Model that answered | Median | Min–max |
|---|---|---|---|---|
| Main source down | `fallback` | qwen3-14b | 0.15 s | 0.12–0.15 s |
| Main source up | `upstream` | Qwen3.6-35B-A3B | 0.11 s | 0.10–0.13 s |

Short requests with 2 output tokens mostly measure the router's response time, not generation. I did not repeat with long requests.

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/painel-roteador.png" | relative_url }}" alt="Router dashboard showing 2 models, 4 decisions, 4 signals, 3 of 3 services healthy and status ready." loading="lazy">
<figcaption>Router dashboard during the measurements: two registered models, four decisions, three of three services healthy.</figcaption>
</figure>

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/topologia-roteador.png" | relative_url }}" alt="Routing map: the user query goes through keyword and decision signals, then five decisions, and reaches the qwen3-14b and qwen3.6-35b models, with the default route to the large model." loading="lazy">
<figcaption>Routing topology in the active configuration. From left to right: signals, decisions (injection blocking, sensitive data, deep reasoning and default route) and models.</figcaption>
</figure>

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/monitoramento-roteador.png" | relative_url }}" alt="Router monitoring page with the Grafana panel: 33 completed inference requests, 87.9% success rate, none in flight, and charts of outcomes and latency over time." loading="lazy">
<figcaption>Monitoring embedded in the router panel at capture time: 33 completed requests, 87.9% success, none in flight. It shows operational metrics, not the quality of the answers.</figcaption>
</figure>

## Decision: fallback always loaded or on demand

| Option | Cost | Effect |
|---|---|---|
| Always loaded | continuous consumption, estimated in the session report, not measured here | the first fallback request answers without the loading wait |
| On demand | idle memory held | about 19 s extra on the first fallback response |

The decision recorded in my notes is to keep the fallback loaded. The configuration still says the opposite, so its description needs fixing.

## Limits

- Short requests only; no latency measurement with long requests and no answer-quality measurement.
- The 19 s loading time for the fallback comes from the session report, from an earlier test that I have not repeated.
- The continuous consumption of the fallback was not measured here.
- Indirect injection is not detected by the router.
- I did not test automatic recovery after a full host reboot.

## Next

- Repeat the failover test five times and measure latency in each.
- Fix the fallback description in the configuration.
- Measure answer quality in the benchmark, with the blind protocol.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
