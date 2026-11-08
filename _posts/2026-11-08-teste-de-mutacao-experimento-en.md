---
title: "Tests that test the tests: mutation testing in an infrastructure experiment"
lang: en
permalink: /en/2026/11/08/teste-de-mutacao-experimento/
description: "Every new piece of statistical logic in the gray-failure experiment was checked with mutants: small, deliberate changes the tests must catch. 210 mutants across 22 commits, 206 killed. What the survivors revealed, and the day the mutation test itself lied because of a stale .pyc."
resumo: "My mutation test could lie: stale bytecode made Python run the mutant code with the correct source on disk. Before that, the survivors had pointed at about ten missing tests."
image: /assets/img/teste-de-mutacao-experimento/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/08/teste-de-mutacao-experimento/" | relative_url }})*

<p class="status"><span class="pill">Method notes</span> <span>November 8, 2026</span></p>

A passing test does not prove the code is right. It proves the test found nothing. To find out whether the tests in the gray-failure experiment would catch a real mistake, I changed the code on purpose, one line at a time (a `<` turned into `<=`, a constant swapped, a line deleted), and checked whether any test failed. There were 210 mutants across 22 commits. The tests caught 206; the 4 that survived were equivalent, meaning they did not change behavior.

The nice numbers would hide what matters: before reaching them, the surviving mutants pointed at about ten missing tests. And once, the mutation test itself lied.

<div class="tiles">
<div class="tile"><div class="tile-value">210</div><div class="tile-label">mutants recorded in the messages of 22 commits</div></div>
<div class="tile"><div class="tile-value">206</div><div class="tile-label">killed by the tests; the 4 survivors are equivalent</div></div>
<div class="tile"><div class="tile-value">1</div><div class="tile-label">round contaminated by stale bytecode, redone in full</div></div>
</div>

## Summary

- **Where I used it:** on every piece of logic that decides a result. Detection rules, window counting, the hit criterion, intervals, rule selection, the simulator gate, the runner's discard and restore logic, the hypothesis analyzers.
- **How:** a 40-line script applies each mutant, prints the diff as proof it went in, runs the tests and restores the file. No external tool.
- **What the survivors revealed:** tests that did not exist. For example, no test checked whether the aggregate analysis used the p99 and not the p95, whether a detection exactly at the start of the fault counted as a false alarm, or whether the control's false-alarm counters added anything up.
- **The mutation test lied once:** a stale `.pyc` from a same-size mutant, written in the same second, made Python run the wrong bytecode. It showed up as a test that failed only in the full suite. I fixed the script (clear the cache for every mutant) and redid every round.
- **Tests that reproduce real bugs:** when the Flagger orchestrator discarded runs within seconds, I first changed the fake cluster to reproduce the defect, watched the test fail, and only then fixed it.

## How it works

A mutant is a pair: a snippet of code and its altered version. The script requires the snippet to appear exactly once, applies the swap, prints the lines that changed and runs the chosen tests. If any test fails, the mutant is **killed**: the tests noticed. If none fails, it is **alive**: either a test is missing, or the change does not alter behavior (an equivalent mutant) [1].

```json
[["    hit = label is not None and t_on < label <= t_off + 60",
  "    hit = label is not None and t_on <= label <= t_off + 60"],
 ["AGG_QUANTILE = 0.99", "AGG_QUANTILE = 0.95"]]
```

The mutants are handwritten, one per decision that matters: every boundary comparison, every constant frozen in the pre-registration, every line that counts or filters something.

<figure class="fig">
<img src="{{ "/assets/img/teste-de-mutacao-experimento/mutantes-en.svg" | relative_url }}" alt="Bars per commit, in order: 2 to 35 mutants each, almost all killed (blue); equivalent survivors (orange) in three commits: one in the manifest commit, two in the Flagger orchestrator commit and one in the check-recording commit." loading="lazy">
<figcaption>Mutants per commit, as recorded in the messages. Some sets were rerun after changes and appear more than once. The four survivors (orange) were analyzed one by one and are equivalent.</figcaption>
</figure>

## What the survivors revealed

The numbers in the figure are the final ones. Along the way, several mutants survived the first round. Each one became a new test before the commit:

| Mutant that survived | What was missing | Test added |
|---|---|---|
| The per-version analysis using p95 instead of p99 | nothing checked the quantile | a window where only the p99 sees the fault |
| A detection exactly at the fault-start label counting as a hit | the lower limit had no edge case | a detection at the t_on label is a false alarm |
| The control's false-alarm counters always at zero | the test data had no alarm in the control | a control with 5 non-consecutive failures (only Flagger fires) and one with 3 consecutive |
| The Flagger emulation at 1.30× being the same as 1.15× | the test campaigns did not separate them | campaigns with a 10% fault, where 1.15× detects and 1.30× almost never does |
| The simulated dashboard fault starting too early | the tests only looked at heavy-reports | `dashboard` with the fault starting at window 5 |
| The runner's restore not writing to the rollout journal | the case was only covered together with another one | restore alone, checking the journal |
| Reading v2's σ from v1 | v1 and v2 always had the same σ in the tests | a different σ for each version |

How to read it: almost every gap was the same kind. The test data was "too clean" and did not tell the right code apart from a close variation.

## The day the mutation test lied

After a mutation round, one test started failing in the full suite and passing when run alone. The file was right. What was wrong was the bytecode.

Python keeps compiled code in `__pycache__` and decides whether it is up to date by comparing the source's modification time, in seconds, and its size [2]. A mutant that swaps `v2` for `v1` has the same size as the original. If it is written and restored within the same second, the `.pyc` built from the mutant still looks valid, and Python runs the mutant code with the correct source on disk.

The effect goes both ways: a mutant can look killed because of the previous mutant's bytecode, or alive because it ran the original's bytecode. The fix was to clear the cache before every mutant and run the tests without writing bytecode (`python3 -B`, `PYTHONDONTWRITEBYTECODE=1`). I redid all 19 rounds from that session. The results held, but I had no way of knowing that without redoing them.

## Tests that reproduce the defect before the fix

The runner for the Flagger test runs against a fake cluster that uses the app's real admin-endpoint code, with a fake clock. In the second cluster pilot, every attempt was discarded within seconds. The cause was that, right after a new revision, the Canary still shows the previous revision's phase. The fake cluster did not model that. I first changed the fake cluster to return the stale phase, watched 17 tests fail, and only then fixed the orchestrator. The test that now guards that case was born from the real defect.

## Limits

- **The mutants are mine.** I chose where to mutate; an operator I did not think of can hide a gap. A tool like mutmut would generate mutants systematically. I did not use one.
- **Equivalence is my judgment.** I explained each of the 4 in its commit (for example, a size check that is redundant with the prefix hash), but did not prove it formally.
- **The counts come from commit messages** and include repeated rounds. They measure effort and outcome, not code coverage.

## How to reproduce

In [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. The script: `scripts/mutar.py`. The mutant sets used: `scripts/mutantes/*.json`.
2. One example: `cd code/triage && python3 ../../scripts/mutar.py market_emul.py "test_market_emul" ../../scripts/mutantes/mme.json`. Criterion: `14/14 mortos` (14/14 killed).
3. The counts in the figure: `data/mutacao.json`, extracted from the commit messages of the experiment repository.

## References

1. Y. Jia, M. Harman, "An Analysis and Survey of the Development of Mutation Testing", IEEE Transactions on Software Engineering, 2011. <https://doi.org/10.1109/TSE.2010.62>. Supports: mutants, equivalent mutants and what mutation testing measures.
2. PEP 552, "Deterministic pycs". <https://peps.python.org/pep-0552/>. Supports: `.pyc` validation by source modification time and size.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
