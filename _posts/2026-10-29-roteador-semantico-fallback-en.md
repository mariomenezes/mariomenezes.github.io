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
- **Fallback tested once:** with the large model down, the request was served by the fallback in about 19 s, including loading the model. A single run, no repetitions.
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
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

The configuration has prioritized routes. One blocks requests with direct prompt-injection patterns aimed at the assistant, another sends requests with sensitive data to local models only, another sends investigation or design requests to the large model with reasoning, and the last is the default route: the main model, with the 14B model as the alternative.

An important limit: detection of indirect injection, from text the assistant reads, does not exist in this setup. It only covers the direct case.

## The fallback test

I stopped the proxy that links the router to the main model and sent a short request through the router. The request was served by the fallback. The total time was about 19 s, most of it loading the 14B model. Then I restarted the proxy.

What this does not show: steady-state latency, variation between repetitions, or behavior with long requests. It was one run.

## Decision: fallback always loaded or on demand

| Option | Cost | Effect |
|---|---|---|
| Always loaded | continuous consumption, estimated in the session report, not measured here | the first fallback request answers without the loading wait |
| On demand | idle memory held | about 19 s extra on the first fallback response |

The decision recorded in my notes is to keep the fallback loaded. The configuration still says the opposite, so its description needs fixing.

## Limits

- One failover test, one run. No repetitions and no quality measurement.
- The continuous consumption of the fallback was not measured here.
- Indirect injection is not detected by the router.
- I did not test automatic recovery after a full host reboot.

## Next

- Repeat the failover test five times and measure latency in each.
- Fix the fallback description in the configuration.
- Measure answer quality in the benchmark, with the blind protocol.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
