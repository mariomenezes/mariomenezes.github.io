---
title: "Gray failure in Istio canaries: why per-version p95 misleads, and what I measured by splitting per feature"
lang: en
permalink: /en/2026/10/28/gray-failure-canary-istio/
description: "Lab notes (study in progress): detecting one degraded feature inside a canary with Istio metrics, deterministic rules, and measurements under injected faults."
image: /assets/img/gray-failure-canary-istio/cover-en.png
---

*[Leia em português]({{ "/pt/2026/10/28/gray-failure-canary-istio/" | relative_url }})*

<p class="status"><span class="pill">Study in progress</span> <span>Version 2 · October 28, 2026 · <a href="#whats-changed">what changed</a></span></p>

A canary can be broken for **one** feature and healthy for everything else. The most common canary analysis looks at the whole version: error rate and p95 of v2 against v1. This post records a lab experiment that measures what that view misses, and what changes when detection is done per `(cluster, version, feature)`.

This is a lab, not production, and the study is still in progress. The numbers hold for the environment described below, and the limits are at the end.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/fault-noise-en.gif" | relative_url }}" alt="Animation: per-minute p95 of v1 and v2 heavy-reports. The fault on 10% of requests starts at minute 5, v2's p95 crosses the threshold and the alarm fires at minute 8, while the whole-version p95 barely moves." loading="lazy">
<figcaption>A real run from the lab. With 10% of v2's <code>heavy-reports</code> requests slowed down, the feature's p95 (orange) crosses the current threshold (dashed) and the alarm fires at minute 8. The whole version's p95 (gray) barely moves. The old 1.3× threshold (dotted) would not have fired.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">10/10</div><div class="tile-label">runs where the per-feature view caught a fault on 10% of one feature's requests, with noise</div></div>
<div class="tile"><div class="tile-value">0/10</div><div class="tile-label">runs where the whole-version view caught the same fault</div></div>
<div class="tile"><div class="tile-value">0</div><div class="tile-label">false alarms in about 16 cluster-hours of healthy traffic</div></div>
</div>

## Summary

- **A whole-version view misses a partial fault in one feature.** A fault on 10% of one feature's requests went unnoticed by the whole version in 16 of 16 runs (6 without noise, 10 with noise), whether it was compared with its own history or with v1 in the same window. The per-feature view caught 16 of 16.
- **A mix change fools a whole-version alarm that looks at its own history.** With no fault at all, changing only the share of `heavy-reports` fired that alarm in 10 of 10 runs. Compared with v1 in the same window it stayed quiet (0 of 10), and so did the per-feature view (0 of 10). I first published only the 10 of 10; the comparison is now complete.
- **Per feature, with p95 compared against v1 of the same feature in the same window**, the 10% and 20% partial faults were detected in 10 of 10 runs per fraction, even with variable latency. There were no alarms on any healthy feature.
- **The shape of the rule matters.** "p95 doubled" caught none of the faults below the timeout. The mean dilutes the partial fault (0 of 18). A relative threshold on p95 works, but my first value (1.3×) stopped detecting once noise came in. The fix to 1.15× was predicted by simulation before measuring, and the cluster confirmed it.
- **False alarms:** zero in about 16 cluster-hours of healthy traffic, with and without noise. The headroom is thin, though: healthy windows reach 1.12× against a 1.15× threshold.
- **No AI in the decision.** Everything is fixed rules over Prometheus metrics.

## What changed in this version {#whats-changed}

<div class="callout">
<p>I went back to the raw per-window data and reran every round. Three things changed:</p>
<ul>
<li><strong>Result 1 was incomplete.</strong> The whole-version alarm I showed compares the version with its own starting value. Against v1 in the same window it does not fire, because both versions get the same mix in this lab. The result is rewritten with the three views side by side.</li>
<li><strong>The baseline is now stated.</strong> The agent compares v2 with v1 of the same feature in the same window. Results 1 to 3 were first analyzed against v2's own first window. I reran them with both baselines: the per-feature counts are identical.</li>
<li><strong>New measurements:</strong> requests per window, the margin between healthy and faulty windows, and a sweep of the threshold. The sweep shows that 1.15× sits at the edge of a plateau, not at a tuned optimum.</li>
</ul>
</div>

## The lab

- One Proxmox host with two k0s clusters (one node each), Istio 1.24.2 in multi-primary, and Cilium ClusterMesh.
- A Python HTTP app with two features:
  - `dashboard`: fast, p95 of 1 to 5 ms;
  - `heavy-reports`: slow, about 3 s.
- Two versions, v1 (stable) and v2 (canary), split 50/50 in the VirtualService. The VirtualService has `perTryTimeout: 5s` and 2 attempts.
- One synthetic traffic generator per cluster, which sends an `X-Feature-Context` header with each request's feature. The generator sits in front of the 50/50 split, so both versions receive the same mix.
- Faults are injected through environment variables in the app, **on v2 only**. That way I know exactly what broke, when, and in what fraction.
- Volume per 60 s window, across 1,424 windows per version and feature: `heavy-reports` has a median of 75 to 85 requests (49 to 127), `dashboard` 128 to 173 (61 to 229). No window had fewer than 30.

<pre class="mermaid">
flowchart LR
  G["traffic generator (X-Feature-Context header)"] --> S["Envoy sidecar (feature label)"]
  S -->|50%| V1["app v1 (stable)"]
  S -->|50%| V2["app v2 (canary)"]
  S -. "metrics, reporter=source" .-> P["Prometheus (feature allow-list)"]
  P --> D["detector: v2 vs v1 of the same feature"]
  D --> E["recorded event (shadow mode)"]
</pre>

## Measuring per feature with Istio

Istio's standard metrics have no "feature" dimension. What I used to create it:

**1. A `Telemetry` resource that copies the header into a label**, client side only:

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: feature-dimension
  namespace: lab-apps
spec:
  metrics:
  - providers:
    - name: prometheus
    overrides:
    - match: { metric: REQUEST_DURATION, mode: CLIENT }
      tagOverrides:
        feature:
          operation: UPSERT
          value: "request.headers['x-feature-context']"
    # same for REQUEST_COUNT
```

**2. The `proxy.istio.io/config` annotation with `extraStatTags: [feature]`** on the pods that originate traffic. Without it, Envoy doesn't expose the label.

**3. An allow-list at Prometheus scrape time.** The header is free-form, and a free-form label blows up cardinality. So a `metric_relabel_configs` turns anything other than `dashboard` or `heavy-reports` into `other`.

**4. `reporter="source"`** in the queries. On the destination side, 504s generated by the caller's sidecar (timeout, retry) don't show up.

**5. Finer histogram buckets.** Istio's default buckets jump from 2500 to 5000 ms. With every `heavy-reports` sample (~3 s) in the same bucket, the interpolated p95 was stuck at 4875 ms, and any regression inside the bucket was invisible. The `sidecar.istio.io/statsHistogramBuckets` annotation with edges every 250 ms between 2500 and 4750 ms fixed this.

The p95 query looks like this:

```promql
histogram_quantile(0.95,
  sum by (destination_canonical_revision, feature, le) (
    rate(istio_request_duration_milliseconds_bucket{
      job="probe-generator",
      destination_service_name="app-service",
      reporter="source"
    }[1m])))
```

## The detection rule

- 60 s windows. A window only counts if it has at least 30 requests.
- Each feature's v2 is compared with **v1 of the same feature, in the same window**. That way, the 3 s p95 of `heavy-reports` is never compared with the 2 ms p95 of `dashboard`.
- A feature is considered degraded after **3 consecutive windows** where one of these holds:
  - error rate above 5%; or
  - latency above the threshold.
- I compared three latency rules:
  - **A:** p95 > 2× baseline (the initial rule);
  - **B:** p95 > 1.3× baseline (1.15× from Result 4 on) **and** p95 > baseline + 500 ms;
  - **C:** like B, but on the mean (`sum/count`), which doesn't depend on buckets.
- All three have a 1000 ms floor: below that, latency isn't evaluated.
- Rule A is a deliberately weak reference. With a 3 s baseline and a 5 s timeout it cannot fire before the timeout turns into an error. It shows the blind spot of a naive multiplier, not how a real canary tool behaves.

To see what the per-feature split adds, I compared three **views** of the same traffic, all with the same rule:

1. **Whole version vs its own history:** the p95 of all v2 requests against v2's value at the start of the run. This is what a static or history-based alarm does.
2. **Whole version vs v1:** the p95 of all v2 requests against all v1 requests in the same window.
3. **Per feature vs v1:** the p95 of each feature's v2 against the same feature's v1 in the same window.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/views-en.svg" | relative_url }}" alt="Grouped horizontal bars. With only a mix change, the whole version against its own history alarms in 10 of 10 runs; the other two views in 0 of 10. With faults, all three views catch the uniform regression and the 20% partial fault. At 10% partial, the whole-version views catch 0 of 6 and the per-feature view 6 of 6. At 5%, 0 of 6 against 3 of 6. With noise, the 20% fault is caught in 8, 7 and 10 of 10 runs, and the 10% fault in 0, 0 and 10 of 10." loading="lazy">
<figcaption>The same runs seen through three views. Only the per-feature view (purple) catches faults on 10% of a feature's requests, with or without noise.</figcaption>
<details>
<summary>Data table</summary>
<table class="data">
<thead><tr><th>Scenario</th><th>Runs</th><th>Whole vs own history</th><th>Whole vs v1</th><th>Per feature vs v1</th></tr></thead>
<tbody>
<tr><td>Mix 0% → 30% (false alarm)</td><td>10</td><td>10</td><td>0</td><td>0</td></tr>
<tr><td>Uniform regression 3 → 4.5 s</td><td>10</td><td>10</td><td>10</td><td>10</td></tr>
<tr><td>Partial, 20% of requests</td><td>6</td><td>6</td><td>6</td><td>6</td></tr>
<tr><td>Partial, 10%</td><td>6</td><td>0</td><td>0</td><td>6</td></tr>
<tr><td>Partial, 5%</td><td>6</td><td>0</td><td>0</td><td>3</td></tr>
<tr><td>Partial 20% with noise</td><td>10</td><td>8</td><td>7</td><td>10</td></tr>
<tr><td>Partial 10% with noise</td><td>10</td><td>0</td><td>0</td><td>10</td></tr>
</tbody>
</table>
</details>
</figure>

## Result 1: a mix change fools a whole-version alarm that looks at its own history

I kept each feature's latency constant and only changed the share of `heavy-reports` in the traffic, from 0% to 30%. No fault. Both versions receive the same mix, because the generator sits in front of the 50/50 split.

The p95 of the whole version went from 1–5 ms to about 3 s in **both** versions, because the mix now included slow requests. Both features stayed exactly the same.

| View (10 runs) | False alarm |
|---|---|
| Whole version vs its own history | 10/10 |
| Whole version vs v1, same window | 0/10 |
| Per feature vs v1, same window | 0/10 |
{: .data}

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/mix-en.svg" | relative_url }}" alt="Two stacked charts on a log scale. Top: the p95 of the whole v1 and v2 both jump from about 1 ms to about 3 s when heavy-reports enters; dashboard stays at 1 ms. Bottom: the ratio of the whole version to its own first window jumps to about 3,000 times, while the ratio of whole v2 to whole v1 and the ratio of v2 to v1 for heavy-reports stay at 1." loading="lazy">
<figcaption>Top: both versions' p95 jump together when the mix changes. Bottom: against its own first window the version looks 3,000× worse; against v1 in the same window nothing moves.</figcaption>
<details>
<summary>Data table</summary>
<table class="data">
<thead><tr><th>Minute</th><th>Whole v2 ÷ its first window</th><th>Whole v2 ÷ whole v1</th><th>heavy-reports v2 ÷ v1</th></tr></thead>
<tbody>
<tr><td>1 to 5</td><td>0.9 to 1.0×</td><td>0.99 to 1.00×</td><td>no traffic yet</td></tr>
<tr><td>6</td><td>3,038×</td><td>1.00×</td><td>1.00×</td></tr>
<tr><td>7 to 12</td><td>3,092 to 3,104×</td><td>1.00×</td><td>1.00×</td></tr>
</tbody>
</table>
</details>
</figure>

The first version of this post showed only the first row, and that is the weakest comparison: a version alarm that compares against v1 in the same window ignores a mix that changes for both. What stays true is narrower. Any alarm anchored on history or on a fixed value fires when the usage profile shifts during a canary.

What I did not test: a mix that differs between v1 and v2 (sticky sessions, header-based routing, a very small canary). There, a whole-version comparison against v1 would also be fooled, and I expect the per-feature view not to be. This lab can't show that.

## Result 2: "p95 doubled" misses real regressions below the timeout

On v2, `heavy-reports` went from 3 s to 4.5 s on every request.

| Rule | Detected (10 runs) |
|---|---|
| A (2×) | 0/10 |
| B (1.3× and +500 ms) | 10/10 |
| C (mean) | 10/10 |
| Whole version, rule B | 10/10 |
{: .data}

With a 3 s baseline, rule A would only fire above 6 s. But with a 5 s `perTryTimeout`, that's already an error. In practice, A detects no latency regression on this feature. A uniform regression this large also moves the whole-version p95, so all three views catch it.

## Result 3: partial failure, where p95 beats the mean

Real gray failure is usually partial: a fraction of requests gets slow. I injected +1.5 s into 20%, 10% and 5% of v2's `heavy-reports` requests, with 6 runs per fraction.

| Slow fraction | A | B per feature | C | Whole vs own history | Whole vs v1 |
|---|---|---|---|---|---|
| 20% | 0/6 | **6/6** | 0/6 | 6/6 | 6/6 |
| 10% | 0/6 | **6/6** | 0/6 | 0/6 | 0/6 |
| 5% | 0/6 | 3/6 | 0/6 | 0/6 | 0/6 |
{: .data}

- **The mean dilutes the fault.** With 20% of requests +1.5 s, the mean rose by at most 454 ms, below C's 500 ms delta. The p95 landed inside the slow group and rose to about 4.6 s.
- **The whole-version view only caught the 20% fault**, with either baseline.
- **5% is a limit of the p95 itself.** A window has about 75 `heavy-reports` requests, so the slowest 5% is about 4 requests. When the slow fraction is near 5%, the p95 sits on the boundary between the fast and slow groups and doesn't always stay above the threshold for 3 windows in a row. This is arithmetic, not tuning.
- **No alarms on v1 or on `dashboard`**, in any run.

## Result 4: with noise, the threshold had to come down, and the simulation called it first

Up to here the app had fixed latency (`sleep(3)`). The p95 of `heavy-reports` had a single value across 244 consecutive windows. That makes detection easy and hides the most important question: does the rule survive variable latency?

Before touching the cluster, I wrote a simulator that reproduces the buckets, `histogram_quantile` interpolation, the VirtualService retry, request volume per window, and the detector's real rules. Calibrated without noise, it reproduces what was measured. With lognormal noise (σ=0.1), it showed the problem:

- noise raises v1's normal p95;
- the 1.3× threshold rises with it and ends up above the slow requests of the fault;
- detection of the 10% fault dropped to about 4%.

Lowering it to **1.15×** restored detection with no false alarms in the simulation. I recorded that value **before** measuring, then ran it on the cluster: σ=0.1 noise on both versions, 10 runs per fraction, and 8 cluster-hours of noisy control.

| Rule | 20% fault | 10% fault | False alarms (8 h) | Simulation forecast |
|---|---|---|---|---|
| B (1.3×) | 7/10 | 1/10 | 0 | ~65% / ~4% |
| **B (1.15×)** | **10/10** | **10/10** | **0** | ~100% / ~97% |
| C (mean) | 0/10 | 0/10 | 0 | — |
| Whole version vs v1 (1.15×) | 7/10 | 0/10 | 0 | — |
{: .data}

- The noise was real: the p95 of `heavy-reports` ranged from 3384 to 3894 ms across windows.
- Detection came 3 to 5 minutes after the fault started.
- Against its own history, the whole version caught 8 of 10 at 20% and 0 of 10 at 10%.
- I re-analyzed the 56 earlier runs with 1.15×: the result was identical in all of them. Without noise, the 500 ms delta is what sets the threshold.

The rule that stayed: **p95 > 1.15× v1's p95 for the same feature and > +500 ms, for 3 windows.**

### How sensitive is the 1.15×?

I swept the ratio on the same noisy runs. Up to 1.15× nothing changes: with a baseline around 3.5 s, 500 ms is already 14%, so the delta is what binds, not the ratio. Above 1.15×, detection falls.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/sweep-en.svg" | relative_url }}" alt="Line chart of detection against the threshold ratio. From 1.05 to 1.15 both faults are detected in 10 of 10 runs. At 1.20 the 10% fault drops to 8 of 10, at 1.25 to 5 of 10, at 1.30 to 1 of 10 and at 1.40 to 0. The 20% fault holds at 10 of 10 up to 1.25, then 7 of 10 at 1.30 and 0 at 1.40. False alarms are zero at every ratio." loading="lazy">
<figcaption>Detection against threshold ratio, 10 noisy runs per fault. False alarms in the 8-hour control are zero at every ratio, because the +500 ms delta keeps the effective threshold above the healthy windows.</figcaption>
<details>
<summary>Data table</summary>
<table class="data">
<thead><tr><th>Ratio</th><th>Fault 20% (of 10)</th><th>Fault 10% (of 10)</th><th>False alarms (8 h)</th></tr></thead>
<tbody>
<tr><td>1.05 to 1.12</td><td>10</td><td>10</td><td>0</td></tr>
<tr><td>1.15</td><td>10</td><td>10</td><td>0</td></tr>
<tr><td>1.20</td><td>10</td><td>8</td><td>0</td></tr>
<tr><td>1.25</td><td>10</td><td>5</td><td>0</td></tr>
<tr><td>1.30</td><td>7</td><td>1</td><td>0</td></tr>
<tr><td>1.40</td><td>0</td><td>0</td><td>0</td></tr>
</tbody>
</table>
</details>
</figure>

So 1.15× is the edge of a plateau, not a tuned optimum. Two things follow. The ratio matters less than the +500 ms delta, and a fixed delta means something different for each feature: 500 ms is 14% of a 3.5 s baseline, 50% of a 1 s one and 5% of a 10 s one. The delta should be relative or per feature. And more noise would push detection down: in simulation, at σ=0.15 the 10% fault is detected in about 70% of runs (141 of 200) at 1.15×. I have not measured noise above σ=0.1 on the cluster.

## Result 5: false alarms on healthy traffic

| Control | Duration | Alarms (all rules) |
|---|---|---|
| No noise | ~8.2 cluster-hours | 0 |
| With noise (σ=0.1) | 8 cluster-hours | 0 |
{: .data}

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/margin-en.svg" | relative_url }}" alt="Overlaid histograms of the v2 over v1 p95 ratio. Healthy windows are centered on 1.0 and reach at most 1.12. Windows with a 10% fault center around 1.26 and with a 20% fault around 1.32. A dashed line marks the 1.15 threshold and a dotted line the old 1.3 threshold." loading="lazy">
<figcaption>Healthy windows (gray) against fault windows (orange) in the noisy runs. The 1.15× threshold separates them, with about 3 points of headroom on the healthy side.</figcaption>
<details>
<summary>Data table</summary>
<table class="data">
<thead><tr><th>Windows</th><th>Count</th><th>Median</th><th>Max</th><th>Above 1.15×</th></tr></thead>
<tbody>
<tr><td>Healthy (8 h control, 480)</td><td>480</td><td>1.00×</td><td>1.09×</td><td>0%</td></tr>
<tr><td>Healthy (control + 80 pre-fault windows)</td><td>560</td><td>1.00×</td><td>1.12×</td><td>0%</td></tr>
<tr><td>Fault on 10%</td><td>80</td><td>1.26×</td><td>1.39×</td><td>79%</td></tr>
<tr><td>Fault on 20%</td><td>80</td><td>1.32×</td><td>1.41×</td><td>88%</td></tr>
</tbody>
</table>
</details>
</figure>

In the 8-hour noisy control, the ratio between v2's and v1's p95 in each minute stayed between 0.91 and 1.09. Adding the 80 windows before each fault, the maximum is 1.12. That headroom to 1.15 is what keeps false alarms at zero. It is thin, and it only covers noise that is independent between pods.

Individual fault windows can still fall below the threshold (21% of the 10% fault windows did not exceed 1.15×). Detection needs 3 windows in a row, which is why it came 3 to 5 minutes after the fault began.

Zero alarms doesn't mean a zero rate. At this volume, the 95% upper bound is about 0.37 false alarms per cluster-hour in each condition.

## Environment gotchas

- **Identical pod CIDRs in both clusters.** In multi-primary, the sidecar started load-balancing half the requests to pod IPs in the other cluster, which were unreachable. Result: 32% errors and a 10 s p95. Mitigated with `clusterLocal` for the service. The right fix is distinct CIDRs.
- **`reporter="destination"` hides 504s.** Use `source` when you want to see what the client gets.
- **Histogram buckets** define what you can see. Check where your feature's latency falls before trusting a p95.
- **Retries turn tail into latency or errors.** With fault and noise together, requests over 5 s were retried, and the error rate reached 4.9%, close to the 5% limit of the error rule.

## Limits (read before generalizing)

- A lab with one host, one replica per version, and synthetic traffic.
- One noise level measured (σ=0.1), independent and identical on both versions. A single pod getting slow on its own, from CPU contention or bursts, was not tested. That's the most likely source of real false alarms, and the case closest to the original idea of gray failure.
- I use "gray failure" for partial, per-feature degradation inside a canary, in the spirit of [Huang et al. (HotOS 2017)](https://www.microsoft.com/en-us/research/publication/gray-failure-achilles-heel-cloud-scale-systems/): a system that looks healthy to its own checks while degraded for its users. The lab reproduces the partial degradation. It does not reproduce a single misbehaving pod hidden behind healthy checks.
- Small samples: 10 of 10 detections give a 95% lower bound of about 74% for the true rate (one-sided; 69% two-sided).
- The mix was the same for both versions. A mix that differs between versions was not tested.
- **Fast features still have no latency detection.** With `dashboard` slowed on 20% of requests (+0.5 s), p95 went to 447–909 ms. That's below the 1000 ms floor, and no rule fired. The floor needs to be per feature.
- **Faults below about 5% of a feature's requests are out of reach of a 60 s p95** at this volume.
- None of this has been compared with Flagger or another canary analysis tool yet. I'm not claiming this approach is better. Splitting by endpoint or feature isn't a new idea either. What this post adds is the measurements.

## Next steps

1. Per-feature floor and a relative delta, so `dashboard` can be detected too.
2. Degrade a single pod, with three or more replicas per version, and measure false alarms.
3. Measure noise above σ=0.1 and a mix that differs between versions.
4. Compare with Flagger on the same partial-failure scenario. Flagger rolls back the whole canary; the question here is whether you can isolate only the affected feature.
5. Try the share of requests above a fixed latency, instead of the p95, for faults below 5%.
6. Per-feature mitigation: route only the degraded feature back to v1 and block canary promotion. First in shadow mode, only recording what would be done.

About AI: it plays no part in detection or decision. If it comes in at all, it will only write the explanation after an event has been detected by rule, and only if it shows measured value.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
