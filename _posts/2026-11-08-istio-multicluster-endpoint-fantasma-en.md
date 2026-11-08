---
title: "Two clusters, the same IP range and a Service that waited 10 seconds"
lang: en
permalink: /en/2026/11/08/istio-multicluster-endpoint-fantasma/
description: "In an Istio multicluster mesh with overlapping pod IP ranges, a new Service inherited an endpoint that only exists in the other cluster. A 2 ms service started showing a 9 s p95. How I found it, the fix and the check that went into the preflight."
resumo: "An endpoint that only exists in the other cluster made a 2 ms service answer with a 9 to 25 s p95. Kubernetes showed one endpoint; Envoy had two."
image: /assets/img/istio-multicluster-endpoint-fantasma/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/08/istio-multicluster-endpoint-fantasma/" | relative_url }})*

<p class="status"><span class="pill">Lab notes</span> <span>November 8, 2026</span></p>

In the first pilot of the [Flagger test]({{ "/en/2026/11/08/flagger-real-detector-por-feature/" | relative_url }}), the `dashboard`, which answers in 1 to 2 ms, started showing a per-minute p95 of 9 to 25 seconds, before any fault was injected. The app was fine, the pod was fine, and Kubernetes showed a single endpoint behind the Service. The Envoy sidecar, however, had two: the local pod and an IP that only existed in the other cluster.

The cause is known: both clusters are in an Istio multicluster mesh and use the same pod IP range. Istio's documentation asks for non-overlapping ranges in that setup [1]. I had already hit this in October, but the mitigation only covered the old service, and Flagger's new namespace was left out.

<div class="tiles">
<div class="tile"><div class="tile-value">9.6 s</div><div class="tile-label">median per-minute dashboard p95 with the broken path (before the fault)</div></div>
<div class="tile"><div class="tile-value">10 s</div><div class="tile-label">how long some requests waited, even with no load</div></div>
<div class="tile"><div class="tile-value">2 ms</div><div class="tile-label">the same request after <code>clusterLocal</code></div></div>
</div>

## Summary

- **Symptom:** a per-minute `dashboard` p95 of 9 to 25 s (median 9.6 s), against 1 to 5 ms in the fixed pilot.
- **Isolation:** inside the container, 0 to 8 ms; straight to the pod IP, 1 to 57 ms; through the old lab's Service, 2 to 24 ms; through the new Service, some requests took about 10 s, **even with no load at all**.
- **Cause:** the client's Envoy had two endpoints for the Service: the local pod and a pod IP from the other cluster, unreachable from here but marked healthy. Requests balanced to it waited for the 10 s connect timeout.
- **Fix:** `clusterLocal` for `*.flagger-lab.svc.cluster.local` in both clusters' MeshConfig (and in the infrastructure-as-code module). Latency went back to 2 ms.
- **Prevention:** the runner's preflight now sends 10 requests to `dashboard` through the Service and fails if any takes more than 1 s or errors.
- **The real fix, not done yet:** distinct pod IP ranges on the two clusters.

## The environment

Two k0s v1.36.4 clusters on the same Proxmox host, one node each, Istio 1.31.1 in multi-primary (each istiod discovers the other cluster's services). Both installs use the default pod range, the same on both sides. The old lab (`app-service`) had `clusterLocal` since October; Flagger's namespace (`flagger-lab`) was created now.

## The cause, in one drawing

<pre class="mermaid">
flowchart LR
  C["client in cluster A"] --> E["client Envoy"]
  E -->|"endpoint 1: local pod IP"| A["app in cluster A (answers in 2 ms)"]
  E -->|"endpoint 2: pod IP from cluster B"| X["same IP does not exist in cluster A"]
  X -. "connection hangs until the 10 s timeout" .-> E
  I["cluster A istiod"] -->|"discovers cluster B pods (multi-primary)"| E
</pre>

In multi-primary, each istiod reads the Services and endpoints of both clusters and hands Envoy every endpoint of a host with the same name. With different IP ranges and routing between clusters, that is what makes cross-cluster load balancing work. With the same range and no routing, the remote pod IP points nowhere from here. Since no outlier detection was configured, Envoy kept considering that endpoint healthy.

## How I found it

<figure class="fig">
<img src="{{ "/assets/img/istio-multicluster-endpoint-fantasma/p95-caminho-en.svg" | relative_url }}" alt="Per-minute dashboard p95 on a log scale: in the pilot with the broken path, between 9 and 25 seconds (median 9,589 ms); in the fixed pilot, between 0.9 and 4.8 ms (median 4.5 ms)." loading="lazy">
<figcaption>Per-minute <code>dashboard</code> p95, only in the minutes before the fault was turned on. The gap is three to four orders of magnitude, with no fault injected.</figcaption>
</figure>

1. **Rule out the app.** Inside the container, a local `curl`: 0 to 8 ms. The app container's CPU: 3 mCPU. The app was not the problem.
2. **Rule out pod networking.** From the generator straight to the pod IP: 1 to 57 ms. The network path to the pod was fine.
3. **Rule out load.** I turned off the generator and tested from a fresh pod, with no load: through Flagger's Service, two of eight requests took 10,025 ms. Through the old lab's Service, from the same pod, none went above 24 ms.
4. **Compare what Kubernetes and Envoy see.** `kubectl get endpoints` showed one IP. The test pod's Envoy stats showed two: the local one, with 8 successful requests, and another, with 2 connect failures, 0 successes and `health_flags: healthy`.
5. **Find where the extra IP came from.** istiod's debug endpoint (`/debug/endpointShardz`) showed the extra IP with the hostname label of the other cluster's node.

<figure class="fig">
<img src="{{ "/assets/img/istio-multicluster-endpoint-fantasma/requisicoes-en.svg" | relative_url }}" alt="Individual request times on a log scale per path: inside the container and straight to the pod IP, all below 60 ms; through the old lab's Service, below 25 ms; through Flagger's Service with no load, six fast and two at 10 seconds; with load, most between 1 and 10 seconds; after the fix, 2 ms, with the first request of each series at about 110 ms." loading="lazy">
<figcaption>Each dot is one request. Only the path through Flagger's Service was slow (red), and with no load the slow ones sat right at the 10 s connect timeout. The first request of each series after the fix includes connection setup.</figcaption>
</figure>

## The fix

```yaml
# MeshConfig (the istio ConfigMap in istio-system), on both clusters
serviceSettings:
- hosts:
  - app-service.lab-apps.svc.cluster.local
  - "*.flagger-lab.svc.cluster.local"
  settings:
    clusterLocal: true
```

`clusterLocal` makes istiod hand Envoy only the endpoints from its own cluster for those hosts [2]. After istiod pushed the change (under a minute), the test pod's Envoy had a single endpoint, and requests went back to 2 ms on both clusters. The same line went into the infrastructure-as-code module, so it does not get lost on a reinstall.

| Path | Before | After |
|---|---|---|
| Test pod, no load, Flagger's Service | 2 to 10,025 ms | 2 ms (112 ms on the 1st request) |
| Generator, `app-fl` Service, cluster a | 2 to 10,000 ms, with one 504 | 2 ms (12 ms on the 1st) |
| Per-minute `dashboard` p95 | 9.2 to 25 s | 0.9 to 4.8 ms |

## What goes into the preflight

The runner now measures the path before starting: 10 requests to `dashboard` through the Service, from the generator pod. It fails if any takes more than 1 s or errors, and says so in the message. It would have caught this case in seconds instead of a whole pilot.

## Limits

- **`clusterLocal` is a mitigation, not a fix.** It turns off cross-cluster balancing for those hosts. The fix is to use distinct pod and Service IP ranges on each cluster, as the documentation asks for single-network meshes.
- **Outlier detection in the DestinationRule** would have reduced the damage by ejecting the endpoint after a few failures. I did not test it.
- **I do not know why some slow requests ended in 200 and others in 504.** The connect timeout and the route timeout are both 10 s, and there is a retry. I did not investigate the combination.

## How to reproduce

In [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. The per-minute p95: `data/pilot-flagger-caminho-quebrado.tar.gz` and `data/pilot-flagger-caminho-ok.tar.gz`; `python3 scripts/extrair.py` builds the `path` section of `data/figuras.json`.
2. The individual requests and the Envoy stats: `data/caminho-medicoes.json` (copied from the terminal output during the diagnosis).
3. On your cluster: `kubectl exec <pod> -c istio-proxy -- pilot-agent request GET clusters | grep <host>` lists the endpoints Envoy actually uses. Criterion: the number of endpoints should match `kubectl get endpointslices`.

## References

1. Istio, "Before you begin" (multicluster installation). <https://istio.io/latest/docs/setup/install/multicluster/before-you-begin/>. Supports: in single-network meshes, pod and Service ranges must not overlap.
2. Istio, "Multicluster Traffic Management". <https://istio.io/latest/docs/ops/configuration/traffic-management/multicluster/>. Supports: `clusterLocal` via `MeshConfig.serviceSettings`, per host or wildcard.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
