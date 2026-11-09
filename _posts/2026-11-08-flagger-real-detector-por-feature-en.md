---
title: "Real Flagger vs a per-feature detector: 0 of 30 vs 30 of 30"
lang: en
permalink: /en/2026/11/08/flagger-real-detector-por-feature/
description: "I installed Flagger on both lab clusters and injected the same partial dashboard fault 30 times. Flagger promoted all 30 faulty versions; the per-feature detector caught all 30. On heavy-reports, both detected."
resumo: "Flagger, with a relative per-version analysis, promoted 30 of 30 versions with a dashboard fault. The per-feature detector caught all 30, with no false alarm in 30 control runs."
image: /assets/img/flagger-real-detector-por-feature/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/08/flagger-real-detector-por-feature/" | relative_url }})*

<p class="status"><span class="pill">Ongoing study</span> <span>Pre-registration comparison v6 · November 8, 2026</span></p>

A fault in 10% of the `dashboard` requests of a canary version, adding 0.5 s to each, went through Flagger all 30 times I injected it: it promoted the faulty version every time. In the same runs, the per-feature detector fired 30 times. On `heavy-reports`, both detected.

This is a lab, not production. Flagger was configured with a **relative per-version** analysis, the strongest I would expect from a typical user, and not with a per-feature metric, which is the obvious way to cover the `dashboard`. That is in the limits, right after the summary.

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/execucoes-en.svg" | relative_url }}" alt="Grid of 60 runs in four rows (real Flagger, per-feature detector, emulated per-version analysis, emulated Flagger-style). On dashboard 10%, real Flagger has 0 of 30 filled squares and the per-feature detector 30 of 30. On heavy-reports 10%, Flagger 30 of 30, detector 28 of 30, emulations 30 and 29." loading="lazy">
<figcaption>Each square is one run, filled when the method detected inside the fault window. On <code>dashboard</code>, real Flagger (red) detected none of the 30; the per-feature detector (orange) detected all of them. On <code>heavy-reports</code>, everything detects; the detector's two misses are on cluster b.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">0/30</div><div class="tile-label">versions with a dashboard fault that Flagger rolled back (it promoted all 30)</div></div>
<div class="tile"><div class="tile-value">30/30</div><div class="tile-label">same runs detected by the per-feature detector</div></div>
<div class="tile"><div class="tile-value">0/30</div><div class="tile-label">false alarms in 30 control revisions, across all four methods</div></div>
<div class="tile"><div class="tile-value">59/60</div><div class="tile-label">runs where the previous round's Flagger emulation agreed with real Flagger</div></div>
</div>

## Summary

- **Dashboard (10% of requests with +0.5 s):** real Flagger promoted 30 of 30 versions with the fault active. The per-feature detector (rule D, fraction of requests above 250 ms) detected 30 of 30. Paired run by run, the difference is significant (exact McNemar with Holm correction, p < 0.0001).
- **Heavy-reports (10% with +1.5 s):** Flagger rolled back 30 of 30, a median of 6.2 minutes after the fault was turned on. The per-feature detector (rule B, relative p95) caught 28 of 30. The difference is not significant, and the direction favors Flagger. The two misses are not truncation by the rollback.
- **Control:** 30 full revisions without a fault. No method fired.
- **The emulation was faithful:** the "Flagger-style" analysis I had emulated in the previous round agreed with real Flagger in 30/30 (dashboard) and 29/30 (heavy-reports). The previous result, which used only the emulation, holds.
- **Main limit:** I only tested the per-version analysis. A per-feature MetricTemplate would probably let Flagger see the dashboard, at the cost of one metric written and maintained per feature. That was not measured.

## The question

In the [previous evaluation]({{ "/en/2026/10/28/gray-failure-canary-istio/" | relative_url }}) the per-feature detector caught faults the per-version analysis missed. But that per-version analysis was my own emulation. This round asks whether Flagger, actually installed and configured the way a user would, behaves like the emulation. The hypotheses, acceptance criteria and plan were committed to Git before any data (section v6 of the pre-registration [1]).

## Environment

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/ambiente-en.svg" | relative_url }}" alt="Diagram: one Proxmox host with two k0s clusters; each runs Flagger 1.45.0, the app-fl-primary and app-fl (canary) pair, a load generator with two pods and a Prometheus with 72 hours of retention. The runner and collector run outside the clusters." loading="lazy">
<figcaption>The same lab, built twice. Each cluster runs the same experiments in parallel, and the results are added up (15 + 15 per scenario).</figcaption>
</figure>

| Item | Value |
|---|---|
| Host | one Proxmox host, two VMs, one k0s node each |
| Nodes | Debian 12, kernel 6.1, 6 vCPU, 12 GB (a) and 16 GB (b) |
| Kubernetes | k0s v1.36.4, containerd 2.3.5, kube-router v2.10.0 |
| Service mesh | Istio 1.31.1, multi-primary |
| Metrics | Prometheus v2.55.0, 15 s scrape, 72 h retention |
| Flagger | 1.45.0 (chart 1.45.0, `meshProvider=istio`) |
| App | Python HTTP server, one replica per version; `dashboard` ~1 ms, `heavy-reports` 3 s with lognormal noise σ = 0.1 |
| Load | 2 pods × 8 workers, 1 request per second per worker, 30% on `heavy-reports`, half with the `x-canary` header |
| State | nothing else running in the test namespaces; two valid rounds between November 7 and 8 |

## How the test works

Flagger creates `app-fl-primary` (the stable version) and treats the `app-fl` Deployment as the canary. I used its A/B mode: requests with the `x-canary: insider` header go to the canary, the rest to the primary. The generator adds the header to half of the requests, which reproduces the 50/50 split of the original lab.

<pre class="mermaid">
flowchart LR
  G["generator (50% with x-canary)"] --> S["Envoy sidecar"]
  S -->|"no header"| P["app-fl-primary"]
  S -->|"x-canary"| C["app-fl (canary)"]
  P -. "destination metrics" .-> M["Prometheus"]
  C -. "destination metrics" .-> M
  S -. "client metrics, per feature" .-> M
  M --> F["Flagger: canary/primary p99 and success"]
  M --> D["per-feature detector"]
  F --> R["promote or roll back"]
</pre>

Flagger's analysis was frozen before the data:

```yaml
analysis:
  interval: 1m
  iterations: 16
  threshold: 5            # roll back after 5 failed checks
  match:
  - headers:
      x-canary:
        exact: "insider"
  metrics:
  - name: request-success-rate
    thresholdRange: { min: 99 }
    interval: 1m
  - name: p99-ratio       # MetricTemplate: canary p99 / primary p99
    templateRef: { name: p99-ratio, namespace: flagger-lab }
    thresholdRange: { max: 1.15 }
    interval: 1m
```

I picked the canary/primary p99 ratio because it compares both versions in the same minute, as my detector does. An absolute `request-duration` limit would be weaker here: 0.5 s more on a 1 ms feature does not move the p99 of a service where 30% of the requests take 3 s.

Each run is a new canary revision. The runner waits for the `Progressing` phase, aligns the start of collection to the minute, turns the fault on through the canary pod's admin endpoint 3 minutes later, turns it off 8 minutes after that and waits 3 more. Flagger decides on its own. My detector and the emulations read the same traffic, from the client side, with the feature label.

A run counts as a hit when the method acts during the fault: Flagger rolls back, or the detector fires, between the start of the fault and one minute after its end. Rolling back before the fault counts as a false alarm.

## Result 1: Flagger does not see a fault that stays inside one feature

On `dashboard`, Flagger went through the 16 analysis iterations with no failed check in 30 of 30 revisions, and promoted the version with the fault active. That was expected: its metric covers the whole version, and 7% of total traffic getting 0.5 s slower changes neither the success rate nor the p99, which is dominated by the 3 s of `heavy-reports`.

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/o-que-cada-um-viu-en.svg" | relative_url }}" alt="One real run, minute by minute. Top: the percentage of dashboard requests above 250 ms: v1 stays at 0% the whole time; v2 rises to 6 to 15% during the 8 fault minutes, and the alarm fires in minute 3. Bottom: the ratio between canary p99 and primary p99, the same math as Flagger's analysis, computed from client-side data: it moves between 0.95 and 1.07, never crosses the 1.15 limit, and the version is promoted." loading="lazy">
<figcaption>One real run, minute by minute. The per-feature detector's signal (top) leaves zero as soon as the fault turns on; the whole-version p99 ratio (bottom) stays near 1 and never reaches the limit. The bottom panel is the same math Flagger's analysis does, computed by me from the client-side data: Flagger records only the outcome, not the value of each check. Its outcome in this run: 0 failed checks, version promoted.</figcaption>
</figure>

The per-feature detector caught all 30, in a median of 3 minutes. The rule used on `dashboard` (rule D) compares the fraction of requests above 250 ms in v2 with that of v1 in the same minute, with a two-proportion test. It was chosen before the data, by simulation, because the relative p95 rule is blind here: its 1 s floor sits above the fault.

| Scenario | Real Flagger | Per-feature detector | Per version (emulated) | Flagger-style (emulated) |
|---|---|---|---|---|
| `dashboard`, 10%, +0.5 s | 0/30 | 30/30 | 0/30 | 0/30 |
| `heavy-reports`, 10%, +1.5 s | 30/30 | 28/30 | 30/30 | 29/30 |
| control (false alarm) | 0/30 | 0/30 | 0/30 | 0/30 |

How to read the table: the `dashboard` row is the argument of the study. The `heavy-reports` row shows that, when the fault is large enough to move the whole version, per-version analysis works and Flagger is even slightly better.

## Result 2: on heavy-reports both act, on different time scales

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/tempo-en.svg" | relative_url }}" alt="Dots per heavy-reports 10% run: the per-feature detector fires at 3 minutes in most runs (median 3), some between 4 and 8; Flagger rolls back between 5.7 and 8.7 minutes (median 6.2). Two runs without a detector hit." loading="lazy">
<figcaption>Minutes since the fault started. The per-feature detector (orange) needs 3 consecutive degraded minutes; Flagger (red) needs 5 failed checks. The times are not comparable one to one: Flagger rolls back the whole canary, while the detector only records.</figcaption>
</figure>

Flagger rolled back all 30 runs between 5.7 and 8.7 minutes after the fault was turned on. That matches 5 failed checks, one per minute, plus the delay until the first complete window. The per-feature detector fired at 3 minutes in 21 of its 28 detections.

The detector's two misses are on cluster b. I checked whether Flagger's rollback had cut collection before the detector had data: it had not. There were 8 and 10 usable windows before the rollback, and rule B never reached 3 consecutive windows above the threshold. That is consistent with what the simulation predicted for this scenario (about 97.5% per run, or 29 of 30), and with the design difference: Flagger adds failures up, rule B requires a streak.

## Result 3: the previous round's emulation was faithful

In the previous evaluation I had compared the detector with an emulation of Flagger's analysis, applied to the same data. Now real Flagger and the emulation ran side by side: they agreed in 30 of 30 runs on `dashboard` and in 29 of 30 on `heavy-reports`. The criterion committed beforehand was at least 28 of 30 per scenario. With that, the previous result, that per-version analysis does not see the `dashboard` fault, no longer depends on my emulation.

## What went wrong (before the data)

| Symptom | Cause | Fix |
|---|---|---|
| In the first pilot, `dashboard` (which answers in 2 ms) had a p95 of 9 to 25 s | Both clusters run multicluster with overlapping pod IP ranges; the Service Flagger created inherited an unreachable endpoint from the other cluster, and some requests waited for the 10 s connect timeout | `clusterLocal` for the test namespace in both clusters' MeshConfig, plus a latency check through the Service in the preflight. Details in [a separate post]({{ "/en/2026/11/08/istio-multicluster-endpoint-fantasma/" | relative_url }}) |
| The second pilot discarded every attempt within seconds | Right after a new revision, the Canary still shows the previous revision's phase, and my orchestrator took that as the end | Only the `Progressing` phase ends the wait; a test reproduces the defect |

Data from the two invalid pilots is not part of the analysis. It is in the reproduction material because it shows the defect.

## Limits

- **Per-feature MetricTemplate was not tested.** Istio exposes the feature label, and Flagger accepts any PromQL query. A per-feature metric would probably catch the `dashboard`. This post measures the per-version analysis, which is the default; the cost of the alternative is one metric, one threshold and one test per feature, maintained by whoever operates it.
- **Flagger acts; the detector only records.** Flagger's rollback takes down the whole canary. At this stage the per-feature detector mitigates nothing. Comparing per-feature mitigation with rollback is a different experiment.
- **One noise level** (σ = 0.1), one replica per version, synthetic traffic, two clusters on one host.
- **30 runs per scenario.** 30 of 30 gives a one-sided 95% lower bound of 0.905 for the true rate; 0 of 30 gives an upper bound of 0.095.
- **Argo Rollouts and Kayenta were not tested.** Kayenta runs statistical tests between canary and baseline and may behave differently.

## How to reproduce

Full material in [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio): runner and analysis code, Flagger manifests, the hash-frozen plan, raw data for the 90 runs and the figure script.

1. Without a cluster, recompute the numbers: `python3 scripts/extrair.py`. It should print `flagger: 90 ok, 0 descartes`.
2. The full analysis: `python3 eval_flagger.py <data>/flagger-v6 plans/FLAGGER-V6.json`. It should show Flagger 0/30 on `dashboard` and 30/30 on `heavy-reports`.
3. With a cluster: install Flagger (`helm upgrade -i flagger flagger/flagger --version 1.45.0 -n flagger-system --create-namespace --set meshProvider=istio --set metricsServer=http://prometheus.observability:9090`), apply the manifests in `code/triage/flagger/`, check with `python3 flagger_runner.py preflight plans/FLAGGER-V6.json --cluster <c>` (it should answer `pré-voo OK`) and run `run` with the `--confirm` that `dry-run` prints. Each cluster takes about 15 hours.
4. Variations that would change the result: an absolute `request-duration` limit (should see less), a per-feature metric (should see the `dashboard`), a smaller `threshold` (rolls back earlier, with more false-alarm risk).

## References

1. Experiment pre-registration, sections v6 and "Resultado da comparação com o Flagger real" (in Portuguese). [`code/triage/PRE-REGISTRO.md`](https://github.com/mariomenezes/mariomenezes.github.io/blob/main/labs/gray-failure-canary-istio/code/triage/PRE-REGISTRO.md). Supports: hypotheses and criteria committed before the data.
2. Flagger, "Istio A/B Testing". <https://docs.flagger.app/tutorials/istio-ab-testing>. Supports: header routing, `iterations` and `threshold`.
3. Flagger, "Metrics Analysis". <https://docs.flagger.app/usage/metrics>. Supports: MetricTemplate and `templateRef` with a custom PromQL query.
4. Istio, "Multicluster Traffic Management". <https://istio.io/latest/docs/ops/configuration/traffic-management/multicluster/>. Supports: `clusterLocal` via `MeshConfig.serviceSettings`.
5. Q. McNemar, "Note on the sampling error of the difference between correlated proportions or percentages", Psychometrika, 1947. Supports: the paired test used in the comparison.
6. S. Holm, "A simple sequentially rejective multiple test procedure", Scandinavian Journal of Statistics, 1979. Supports: the correction for multiple tests.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
