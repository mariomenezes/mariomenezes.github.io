---
title: "Writing the criteria before the data: pre-registration in a Kubernetes lab"
lang: en
permalink: /en/2026/11/08/pre-registro-experimento-kubernetes/
description: "Six versions of a pre-registration, each committed to Git before the round it covers, across two cluster rounds with 212 valid runs. What it changed in the design, two predictions against my own detector that came true, and what a pre-registration does not protect."
resumo: "I committed to Git what would count as success before each round. It changed the acceptance criterion, removed one rule from the race, and kept two results that do not favor my detector in the report."
image: /assets/img/pre-registro-experimento-kubernetes/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/08/pre-registro-experimento-kubernetes/" | relative_url }})*

<p class="status"><span class="pill">Method notes</span> <span>November 8, 2026</span></p>

Before each round of the gray-failure canary experiment, I committed to Git a file with the hypotheses, the numbers that would count as success, the execution plan and the analysis. There were six versions in ten days and two cluster rounds, with 212 valid runs. The file changed three design decisions before any data came in. It also kept two results that do not favor the detector I was building in the report.

This is a personal lab, not a clinical trial. Pre-registration here is just a discipline: decide what counts before seeing the result, and do not edit that decision afterwards.

<div class="tiles">
<div class="tile"><div class="tile-value">6</div><div class="tile-label">pre-registration versions, each one before the data it covers</div></div>
<div class="tile"><div class="tile-value">212</div><div class="tile-label">valid cluster runs (122 in the evaluation, 90 against Flagger), 0 discarded</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">design decisions changed by the pre-registration before any data</div></div>
<div class="tile"><div class="tile-value">2</div><div class="tile-label">predictions against my own detector that came true and stayed in the report</div></div>
</div>

## Summary

- **What goes into the file:** hypotheses with numeric criteria, the decision rule for each feature, the execution plan frozen by hash (the runner refuses to run without that hash), the analysis already written and tested, the discard rules, and what to do if a gate fails.
- **Three decisions changed before the data:** the detection acceptance criterion (the original one would fail a good detector 52% of the time); one rule left the race because the simulator got the latency level wrong; and high noise was left out of the cluster round, with the reason written beforehand.
- **Two unfavorable predictions came true:** on `heavy-reports`, per-version analysis detects as well as per-feature analysis; and against real Flagger, the two runs only one side got right were Flagger's.
- **One of my mistakes showed up later:** I wrote "300 runs" in the evaluation result; it was 122. The correction is in the file itself, as a dated note, without deleting the original sentence.
- **What a pre-registration does not protect:** earlier versions used data I had already seen, the lab setup and the Flagger configuration were my choices, and the experiment repository is private, so commit dates cannot be checked by readers.

## Why do this in a lab

The first post in the series claimed "16 of 16 runs" with rules I had tuned looking at the same data. That is not fraud; it is the normal path of exploration. But the number is optimistic by construction. The question I wanted to answer next was a different one: with the rules fixed, on new data, does the detector work? For that question to have an honest answer, the rule and the criterion have to exist before the data [1].

## How the process turned out

<figure class="fig">
<img src="{{ "/assets/img/pre-registro-experimento-kubernetes/linha-do-tempo-en.svg" | relative_url }}" alt="Timeline from October 29 to November 8: pre-registration commits (v1 and v2 on 10/29, v3 on 11/4, v4 and v5 on 11/5, v6 on 11/7) and cluster data commits (v5 evaluation on the evening of 11/7, Flagger on 11/8), always after the version they belong to." loading="lazy">
<figcaption>Commits that changed the pre-registration (circles) and that stored cluster data (squares). Each data round comes after the version that defines it; results go into new sections without changing the text above.</figcaption>
</figure>

1. **Write the version.** Hypotheses (H1 to H8 across versions), each with a number: "one-sided 95% lower bound ≥ 0.80 over 30 runs", "false alarms below 0.1 per cluster-hour", "McNemar with Holm, α = 0.05".
2. **Write and test the analysis before the data.** `eval_v5.py` and `eval_flagger.py` were committed, with tests and mutation testing, before the first run they would analyze. That way the analysis cannot be fitted to the result.
3. **Freeze the plan.** Each round's plan is a JSON file with scenarios, repetitions and duration. Its hash, together with the runner's discard constants, goes into the pre-registration. The runner only runs with `--confirm <first 12 characters of the hash>`.
4. **Run and record.** The result goes into a new section, with the plan hash and the analyzer commit. Nothing above is rewritten. Corrections become dated notes.

## What changed because of it

**The acceptance criterion.** v4 asked for a lower bound ≥ 0.90 with 29 runs, which only passes with 29 of 29. Doing the math before running, with the rate the simulation predicted (97.5%), the chance of passing was 48%. v5 switched to 30 runs and a lower bound ≥ 0.80, with a 96% chance. The change was driven by the power calculation, not by a result, and it was recorded before the data. Details in [The 29 out of 29 criterion]({{ "/en/2026/11/08/criterio-29-de-29/" | relative_url }}).

**One rule left the race.** The consequences of the simulator's validity gate were written before running the gate: if only the level metrics failed, the rule that depends on the absolute level (D) could not be chosen for `heavy-reports`. That is what happened, and the rule was removed without discussion. Details in [A simulator that gets the decision right and the level wrong]({{ "/en/2026/11/08/simulador-decisao-nivel/" | relative_url }}).

**High noise stayed out of the cluster.** The simulation predicted about one false alarm per hour for rule B at σ = 0.3. Instead of running it and "discovering" the failure, v5 removed σ = 0.3 from the cluster round with the reason written down, and the limitation appears in every result.

## Predicted vs observed

<figure class="fig">
<img src="{{ "/assets/img/pre-registro-experimento-kubernetes/previsto-observado-en.svg" | relative_url }}" alt="Six hypotheses with the observed rate, a one-sided 95% interval and the criterion committed beforehand: H1 dash10 and heavy10 30/30 above 0.80; H6a Flagger 0/30 below 0.20; H6b Flagger 30/30 above 0.80; H8 agreement 30/30 and 29/30 above 0.80." loading="lazy">
<figcaption>Each bar is the one-sided 95% interval of the observed rate; the red line is the criterion committed before the data. Every hypothesis in this chart passed, including the ones saying Flagger sees <code>heavy-reports</code> as well as my detector.</figcaption>
</figure>

| Prediction committed beforehand | What came out | In whose favor |
|---|---|---|
| On `dashboard`, per-version analysis does not detect | 0 of 30 (emulated) and 0 of 30 (real Flagger) | the per-feature detector |
| On `heavy-reports`, per-version analysis detects as much as per-feature | 30 of 30 for both; no difference | nobody: the detector's case is limited to `dashboard` |
| Against real Flagger, on `heavy-reports`, no difference | 2 runs only Flagger caught, 0 only mine | Flagger, in direction |
| False alarms below 0.1 per cluster-hour | 0 in 30 cluster-hours, bound 0.0999 | passes, barely: one alarm would fail it |

How to read it: without the file, the `heavy-reports` row would be the easiest one to leave out of a post about "per-feature detection". With it, it is committed as a prediction, and the result has to show up.

## What did not work or stayed weak

- **v1 to v3 were not out of sample.** The controls that calibrated the threshold were the same ones I had already seen. v1 says so at the top. The first valid evaluation is v5.
- **Design choices are mine.** The lab, the injected faults and the Flagger configuration (I chose the relative analysis, the strongest a typical user would set up) were decided by me. The pre-registration only guarantees I did not change them afterwards.
- **I got a count wrong.** "300 runs" in the v5 result; it was 122 (120 fault runs and 2 long controls). No rate changes, because they are all per scenario, but the total was wrong in the file for about 17 hours, until I reprocessed the data for these posts.
- **Dates only I can verify.** The experiment repository is private. I publish the exported timeline, with hashes and dates, and the full file, but readers cannot check the commits.

## Environment

The same as the [Flagger post]({{ "/en/2026/11/08/flagger-real-detector-por-feature/" | relative_url }}): a Proxmox host with two k0s v1.36.4 clusters, Istio 1.31.1, Prometheus v2.55.0 and Flagger 1.45.0. The pre-registration is a Markdown file versioned with the code.

## How to reproduce

Material in [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio).

1. Read the file: `code/triage/PRE-REGISTRO.md` (in Portuguese). The "Resultado..." sections are at the end and cite the plan hash and the analyzer commit.
2. Check the order: `data/linha-do-tempo.json` lists every pre-registration and data commit, with its date. Criterion: every data commit comes after the version that defines it.
3. Check that the analysis already existed: running `python3 eval_v5.py` and `python3 eval_flagger.py` on the raw data gives the same numbers as the file (see the lab README).
4. To use this in your own experiment: one file, a plan with a hash, an analysis tested beforehand, results in new sections and corrections as dated notes. The rest is optional.

## References

1. B. A. Nosek, C. R. Ebersole, A. C. DeHaven, D. T. Mellor, "The preregistration revolution", PNAS, 2018. <https://doi.org/10.1073/pnas.1708274114>. Supports: the distinction between exploratory and confirmatory research, and pre-registration as a way to keep them apart.
2. This experiment's pre-registration (in Portuguese). [`code/triage/PRE-REGISTRO.md`](https://github.com/mariomenezes/mariomenezes.github.io/blob/main/labs/gray-failure-canary-istio/code/triage/PRE-REGISTRO.md). Supports: the versions, criteria and results cited.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
