---
title: "A simulator that gets the decision right and the level wrong"
lang: en
permalink: /en/2026/11/08/simulador-decisao-nivel/
description: "Before using a simulation to choose detection rules, I compared its predictions with what had already been measured in the cluster. The metrics that drive decisions fell inside the predicted range; the absolute-level ones did not. That removed one rule from the race, as written beforehand."
resumo: "The simulator predicted every decision correctly and got the mean latency wrong by about 50 ms. Per what I had written beforehand, that was enough to drop one rule, and the cluster later confirmed it was the weakest one there."
image: /assets/img/simulador-decisao-nivel/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/08/simulador-decisao-nivel/" | relative_url }})*

<p class="status"><span class="pill">Method notes</span> <span>November 8, 2026</span></p>

I used a simulation to choose which detection rule each feature would use in the cluster evaluation. Before trusting it, I compared its predictions with measurements I already had, at the same noise level. Nine metrics per cluster. The seven that drive decisions (ratios between versions, alarms, detections) fell inside the predicted interval. The two absolute-level ones (p95 and mean latency) fell outside, on both clusters.

What to do in that case was already written before running the comparison. The rule that depends on the absolute level was removed from the race for `heavy-reports`. Later, in the cluster, it was precisely the weakest one in that scenario (25 of 30, against 30 of 30 for the chosen rule).

<div class="tiles">
<div class="tile"><div class="tile-value">14/14</div><div class="tile-label">decision metrics inside the predicted interval (7 per cluster)</div></div>
<div class="tile"><div class="tile-value">0/4</div><div class="tile-label">level metrics inside the interval (p95 and mean, 2 per cluster)</div></div>
<div class="tile"><div class="tile-value">~50 ms</div><div class="tile-label">how much the simulator overestimates the 3 s mean latency</div></div>
</div>

## Summary

- **The simulator:** each `heavy-reports` request takes 3 s × lognormal noise + 50 ms, with a retry above 5 s; the p95 is computed with the real Istio histogram buckets. The `dashboard` has a base latency of about 1 ms. The rules are the real detector's.
- **The gate:** 200 simulated campaigns with the same design as the old measurements at σ = 0.1 (4 h of control and 5 runs per fraction on each cluster). A metric passes if the measured value falls inside the central 95% of the campaigns.
- **Result:** decisions inside, level outside. The measured mean was 3,016 and 3,012 ms against a predicted 3,059 to 3,071; the p95 was 3,468 and 3,552 ms against 3,605 to 3,632.
- **Consequence committed beforehand:** if only the level failed, the relative rules would remain selectable and rule D (which compares fractions above an absolute latency limit) could not be chosen for `heavy-reports`.
- **Resulting selection:** B for `heavy-reports` at σ = 0.1; no eligible rule at σ = 0.3 (a predicted false-alarm failure, and high noise left the cluster round); D for `dashboard`.
- **I do not know why the level differs.** The mean with noise came out *below* the mean without noise (3,049 ms), which the model does not explain. I did not investigate.

## The simulator, as a pipeline

<pre class="mermaid">
flowchart LR
  R["simulated request: 3 s × lognormal(σ) + 50 ms, retry > 5 s"] --> H["histogram with Istio's buckets"]
  H --> W["60 s window per version and feature"]
  W --> D["real detector rules (B, BF, D)"]
  D --> S["selection with the calibration seed only"]
  S --> A["evaluation with another seed"]
</pre>

The simulator serves one question: among the candidate rules, which one keeps false alarms below 0.1 per cluster-hour and detects the most on the worst cluster? The choice uses only the calibration seed; the evaluation seed is reported and never enters the decision (a test enforces that in the code).

## The gate

<figure class="fig">
<img src="{{ "/assets/img/simulador-decisao-nivel/portao-en.svg" | relative_url }}" alt="Nine metrics, two clusters. The seven decision metrics (v2/v1 ratio median and q99, control alarms, rule B detections at 1.15× and 1.30× for 20% and 10% faults) have the measured value inside the predicted interval. The two level metrics fall outside: v1 p95 3,468 and 3,552 ms against 3,605 to 3,632; mean 3,016 and 3,012 against 3,059 to 3,071." loading="lazy">
<figcaption>Position of the measured value inside the predicted interval (0 = low, 1 = high). Everything that decides is inside; the absolute level is below the interval on both clusters.</figcaption>
</figure>

The decision metrics compare v2 with v1 in the same minute, or count alarms and detections. A level error that is the same for both versions cancels out in them. That is why the simulator can get the level wrong and still get the decision right. But not every rule is immune: rule D counts requests above 3,750 ms, and the healthy fraction above that limit depends on the absolute level. With the level overestimated, the simulation would get rule D's false-alarm rate and detection wrong.

## The selection

<figure class="fig">
<img src="{{ "/assets/img/simulador-decisao-nivel/selecao-en.svg" | relative_url }}" alt="Matrix of 4 rows (heavy-reports and dashboard, σ 0.1 and 0.3) by 3 rules (B, BF, D) with false-alarm UB95 per cluster-hour and detection at 10%. heavy-reports σ=0.3: B and BF 1.22 per hour (ineligible), D 0.07 per hour with 4% detection. dashboard: B detects 0%, BF and D 99 to 100%. Outline on the chosen rule: B for heavy-reports, D for dashboard." loading="lazy">
<figcaption>Calibration, 72 simulated hours per cell. Red: false alarms above the target. On <code>heavy-reports</code> at σ = 0.3, the only eligible rule was D, and it fell at the gate; the committed result was "no eligible rule, H3 should fail".</figcaption>
</figure>

| Feature, noise | Eligible | Chosen | Note |
|---|---|---|---|
| heavy-reports, σ = 0.1 | B, BF (D removed by the gate) | B | B and BF are identical on this feature |
| heavy-reports, σ = 0.3 | none | B, with a predicted failure | B and BF at ~1.2 false alarms per hour |
| dashboard, σ = 0.1 and 0.3 | B, BF, D | D | D beats BF 57 to 55 in 200 simulated runs: a practical tie; B sees nothing |

## What the cluster said afterwards

In the cluster evaluation, at σ = 0.1, rule B detected 30 of 30 on `heavy-reports` and rule D, running only as a secondary, 25 of 30. On `dashboard`, D detected 30 of 30. The gate did not "get" anything right on its own; it applied a rule written beforehand. But in this case the excluded rule was indeed the one that fell behind.

## Limits

- **The `dashboard` model has no independent validation.** Its base latency was taken from the measurements themselves (below 1 ms on one cluster, above on the other), and the model has no healthy tail. The false-alarm rate of the `dashboard` variants was not exercised in simulation; the evidence is the 30 cluster-hours of control in the cluster.
- **The level error has no known cause.** It may be in the app's `sleep`, in Envoy's histogram precision or in my overhead model. An investigation would probably bring the model closer, but would not change this round's decision.
- **A 95% interval gate fails by chance on about 1 in 20 metrics.** Here the failures were systematic (all 4 level metrics, on both clusters, all on the same side), not random.

## How to reproduce

In [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. Measured: `data/gate-measured-sigma0.1.json`, generated by `code/triage/gate_measure.py` from `data/noise-sigma0.1.tar.gz`.
2. Predicted and verdict: `cd code/triage && python3 decision_curve.py --mode gate --seed 1 --replicates 200 --jobs 8 --measured ../../data/gate-measured-sigma0.1.json --out /tmp/gf`. Criterion: `decision_ok: true`, `level_ok: false`, the 4 level metrics in `failed`.
3. Selection: `python3 decision_curve.py --mode phase2 --seed 1 --eval-seed 2 --out /tmp/gf`. Criterion: the same `final_selection` as `data/phase2-cal1-eval2.json`.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
