---
title: "Two servers on the same AMD GPU kept the card at 100% with no work; one variable fixed it"
lang: en
permalink: /en/2026/10/29/multimodelo-duas-gpus/
description: "Lab notes: two llama.cpp (ROCm) processes on the same RX 9060 XT kept the GPU at 100% and ~37 W while idle. I isolated the cause in 4 experiments and measured the GPU_MAX_HW_QUEUES=1 workaround: 11 W idle, +2.6 ms per embedding."
image: /assets/img/multimodelo-duas-gpus/cover-en.png
---

*[Leia em português]({{ "/pt/2026/10/29/multimodelo-duas-gpus/" | relative_url }})*

<p class="status"><span class="pill">Lab</span> <span>Version 2 · October 30, 2026 · <a href="#what-changed">what changed</a></span></p>

<p class="lead">On a host with two 16 GB AMD GPUs, the second card sat at 100% busy all day with no requests. The cause was not a model or a stuck request: it took only <strong>two</strong> llama.cpp processes with ROCm on the same GPU. One HIP environment variable let the card rest again, at a cost of 2.6 ms per embedding.</p>

This is a personal lab, not production. The post shows how I isolated the cause, the workaround, what it costs and what I still don't know.

<div class="tiles">
<div class="tile foco"><div class="tile-value">100%</div><div class="tile-label">GPU busy with 2 idle processes: 11 of 11 windows with the default configuration, across 4 experiments</div></div>
<div class="tile"><div class="tile-value">37 → 11 W</div><div class="tile-label">idle GPU power before and after the workaround (median, 120 readings each)</div></div>
<div class="tile neutro"><div class="tile-value">+2.6 ms</div><div class="tile-label">cost per embedding request (7.6 → 10.2 ms, 60 requests each)</div></div>
</div>

<div class="key" markdown="1">
In short

- **Two processes on the same GPU are enough.** With one server, GPU 1 stayed at 2% and 11 to 12 W. With both, 100% and 35 to 39 W, with no requests at all.
- **It does not depend on the model or the card.** The pattern repeated in reverse order and also on GPU 0, when I started a second process next to the fallback model.
- **The power draw is real, not a reading error.** The clock rose from 31 MHz to about 3,450 MHz along with the power.
- **`GPU_MAX_HW_QUEUES=1` fixed it** here: 2% and 11 W with both servers running, after real requests. With `=2` it went back to 100%.
- **Measured cost:** +2.6 ms per embedding (+34%) and +5 ms per 64-token completion (+0.6%). The workaround stays applied.
- **Limit:** I don't know the mechanism inside the driver. Public reports [1][2][3] describe the same symptom on other AMD cards, with no confirmed cause.
</div>

<div class="toc-box" markdown="1">
<strong>In this post</strong>

* TOC
{:toc}
</div>

## What changed in this version {#what-changed}

<div class="callout" markdown="1">
The first version (Oct 29) said the cause was "outside the timer" and had not been investigated. It also said the backend was Vulkan. Three corrections:

- **Backend:** all three servers use **ROCm (HIP)**, not Vulkan. I checked the libraries loaded by each process.
- **Cause:** the timer was unrelated. The cause is having two HIP processes on the same GPU (see [Results](#results)).
- **English figure:** the English version used the Portuguese figure. Each language now has its own.
</div>

## Environment

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/ambiente-en.svg" | relative_url }}" alt="Host diagram: GPU 0 runs the Qwen3-14B fallback model (10.4 GB); GPU 1 runs two processes, Qwen2.5-Coder-3B code completion on port 8083 and Qwen3-Embedding-0.6B embeddings on port 8084." loading="lazy">
<figcaption>Model placement. GPU 0 has one process (the router fallback). GPU 1 has two independent processes, and that is where the problem showed up.</figcaption>
</figure>

| Item | Value |
|---|---|
| Host | AMD Ryzen 5 5600G (12 threads), 62 GB RAM, Proxmox VE 8.4.19, kernel 6.14.11 |
| GPUs | 2 × AMD Radeon RX 9060 XT (Navi 44, RDNA4), 16 GB each |
| Container | privileged LXC with both GPUs, Ubuntu 24.04 |
| ROCm | 7.2.3 |
| Server | llama.cpp `llama-server`, build 216 (`f12cc6d`), HIP backend |
| GPU 0 | Qwen3-14B Q4_K_M, 16k context, always loaded (semantic router fallback) |
| GPU 1 | Qwen2.5-Coder-3B Q4_K_M (code completion) and Qwen3-Embedding-0.6B Q8_0 (RAG embeddings), one `llama-server` each |
| State | no requests during the idle windows; the servers listen on the LAN but the logs showed no traffic |

Addresses, host names and keys are left out of the text and the data.

## How I measured

I read three values the `amdgpu` driver exposes in the host's sysfs, once per second:

- `gpu_busy_percent`: the power-management firmware (SMU) samples, every millisecond, whether any GPU block is busy, and reports the fraction [4][5];
- `power1_average`: average board power, in microwatts [5];
- `pp_dpm_sclk`: the current core clock.

To find **which processes** use each card, I read `/proc/<pid>/fdinfo`. For each open GPU descriptor the kernel publishes the card's PCI address and the memory the process uses [6]. Engine-time counters do not show up for ROCm compute work, so identification was by elimination: start and stop each server and watch the card.

Each experiment is a script that runs on the host, starts and stops the services inside the container and writes the readings to CSV. I dropped the first 10 seconds of each phase as transition.

| Experiment | What varies | Phases × length |
|---|---|---|
| A | stop one server at a time, then both; restart; send 1 request to each server | 7 × 90 s |
| B | the same in another order; then start a 2nd process on GPU 0 | 6 × 60 s |
| C | `GPU_MAX_HW_QUEUES` unset, `=1`, `=2`, unset again | 4 × 60 s |
| D | cost of the workaround: 30 embeddings and 10 completions per configuration, then 60 s idle | 2 rounds × 2 configurations |

## Results

### 1. The GPU is busy only when both servers are running

The figure below is all of experiment A. The orange band marks the phases with two processes on GPU 1.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/fases-en.svg" | relative_url }}" alt="650-second time series. GPU 1 busy at 100% with both servers running, drops to 2% when either one is stopped, 0% with both stopped, and returns to 100% as soon as both restart, before any request. Power follows: about 38 W, 12 W, 9 W and again 35 to 37 W." loading="lazy">
<figcaption>Experiment A, one reading per second. What to look at: busy returns to 100% at second 375, when both servers come back, <em>before</em> any request. The power spikes in phases 6 and 7 are the two requests.</figcaption>
</figure>

- **Either server alone sits at 2%.** It is not one specific server: stopping completion or embeddings gives the same result.
- **Requests change nothing.** The card was already at 100% before them (phase 5) and stayed there after (phases 6 and 7).
- **Power follows the indicator.** The clock went from 31 MHz (one process) to about 3,450 MHz (two processes), and power from 11–12 W to 35–39 W. This is not a `gpu_busy_percent` reading error: the card is actually active.

### 2. The rule holds in the other order and on the other GPU

In experiment B I reversed the order. Then, to separate "two processes" from "these two models", I temporarily started a second process on **GPU 0**, next to the fallback model, which had been at 2%.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/regra-en.svg" | relative_url }}" alt="Two dot plots. X axis: number of llama-server processes on the same GPU (0, 1, 2). With 0 processes, 0% and 9 W. With 1, about 2% and 11 to 12 W. With 2, 100% and 35 to 39 W. Points from experiment A, experiment B and the GPU 0 control land together in each group." loading="lazy">
<figcaption>Each point is the median of one phase. What to look at: the three markers (experiment A, experiment B and GPU 0) land in the same place. The number of processes explains the busy level; the model and the card do not.</figcaption>
<details><summary>Numbers per phase</summary>
<p>Experiment A: phases with 2 processes: 100% (min and max 100) and 35 to 39 W; with 1 process: 2% and 11 to 12 W; no processes: 0% and 9 W. Experiment B: 2 processes: 100%, 36 to 38 W; 1 process: 2%, 11 to 12 W. GPU 0 with the fallback plus a temporary process: 100% and 36 W; fallback only: 2% and 11 W. Full file: <code>resumo_fases.json</code> in <code>labs/</code>.</p>
</details>
</figure>

This matches two public reports. In the first, from 2023, an RX 7900 (RDNA3) running the same `llama-server` stayed at 100% while idle, and the author tied it to the HIP runtime creating hardware queues [1][2]. In the second, from 2026, a Ryzen AI MAX APU (gfx1151) sat at 100% and maximum clock **whenever two or more ROCm clients** had resident models, and rested with only one [3]. My card is a different generation (RDNA4). I found no official explanation of the mechanism.

### 3. The workaround: one hardware queue per process

By default each HIP process creates up to 4 hardware queues per GPU, controlled by `GPU_MAX_HW_QUEUES` [7]. One comment in the 2023 report mentions this variable as a workaround [1]. I tested `1` and `2`, with both servers running and after one request to each:

| Configuration (2 processes on GPU 1) | Median busy | Median power | Readings |
|---|---|---|---|
| default (4 queues) | 100% | 37 W | 50 |
| `GPU_MAX_HW_QUEUES=1` | **2%** | **12 W** | 50 |
| `GPU_MAX_HW_QUEUES=2` | 100% | 37 W | 50 |
| default again | 100% | 37 W | 50 |

Reading: with one queue per process, the card rests even with two processes. With two queues, it does not. Going back to the default brings the problem back, so the restart was not what fixed it.

### 4. What the workaround costs

A single queue serializes each process's work. To measure the cost I ran, in two rounds per configuration, 30 embedding requests with a 1,000-character text (the size of a chunk in my RAG index) and 10 completions of 64 tokens.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/contorno-en.svg" | relative_url }}" alt="Two dot plots. Left, idle GPU 1 power: 37 W by default and 11 W with GPU_MAX_HW_QUEUES=1. Right, time per embedding request: median 7.6 ms by default and 10.2 ms with the workaround." loading="lazy">
<figcaption>Experiment D. What to look at: idle power drops by 26 W, and embeddings get 2.6 ms slower. Dots are individual readings and requests; the black bar is the median.</figcaption>
</figure>

| Measure | Default | `GPU_MAX_HW_QUEUES=1` | Δ |
|---|---|---|---|
| Idle GPU 1, busy (120 readings) | 100% | 2% | −98 p.p. |
| Idle GPU 1, power | 37 W | 11 W | −26 W |
| Embedding, 1,000 characters (60 requests) | 7.6 ms | 10.2 ms | +2.6 ms (+34%) |
| Completion, 64 tokens (20 requests) | 912 ms | 918 ms | +5 ms (+0.6%) |
| HTTP errors | 0 | 0 | — |

- **For my use, the cost does not matter.** The RAG indexer produces a few hundred embeddings per hour; 2.6 ms more on each adds up to under a second. Completion, dominated by token generation, barely changes.
- **The saving is continuous.** 26 W less, 24 hours a day, is about 230 kWh per year. That is arithmetic on the power the card reports, not a wall-socket measurement.
- **I applied the workaround** to both GPU 1 services with a systemd override file. GPU 0 still has a single process and did not need it.

## What went wrong

| Symptom | Cause | Fix |
|---|---|---|
| GPU 1 at 100% and ~37 W with no requests | two HIP processes on the same GPU with the default queues | `GPU_MAX_HW_QUEUES=1` on both services |
| I blamed the unload timer | the timer only reaches the router, but that was unrelated to the symptom | measure by starting and stopping each process |
| Previous post said "Vulkan" | the services carry Vulkan environment variables, but the binary was built with HIP | check the libraries the process loads |
| 27B model did not fit | 30 GB in Q6 on a 16 GB card | removed; the host keeps models up to 14B |

## Limits

- **One machine, one driver.** I did not test another kernel, another ROCm version or Vulkan.
- **I don't know the mechanism.** The data shows the link between process count, queues and busy level, not what the firmware does inside.
- **Short windows.** Phases last 60 to 90 s. I have not measured the workaround over days; I will keep watching power.
- **Power reported by the card**, not measured at the wall.
- **Cost measured with sequential requests.** With many concurrent requests in the same process, a single queue may cost more.
- The old episode with llama.cpp sleep mode (which also left GPU 0 at 100%) may share this cause, but I did not test it.

## How to reproduce

Prerequisites: a Linux host with an AMD GPU and the `amdgpu` driver, ROCm, `llama-server` built with HIP, two small GGUF models and root access to read sysfs. Time: about 40 minutes.

1. **Start two `llama-server` instances on the same GPU**, for example one for embeddings and one for completion:

   ```bash
   ROCR_VISIBLE_DEVICES=1 llama-server -m <EMBED_MODEL>.gguf -ngl 99 --embeddings --port 8084 --api-key <KEY> &
   ROCR_VISIBLE_DEVICES=1 llama-server -m <FIM_MODEL>.gguf -ngl 99 --port 8083 --api-key <KEY> &
   ```

   *Works if* `curl http://<HOST>:8084/health` returns `{"status":"ok"}`.

2. **Read the card's busy level without sending requests:** `cat /sys/class/drm/card1/device/gpu_busy_percent`. *Reproduced if* it stays at 100 for more than a minute.
3. **Stop one of the two** and read again. *Reproduced if* it drops close to 0.
4. **Apply the workaround** and restart both:

   ```ini
   # /etc/systemd/system/<service>.service.d/gpu-max-hw-queues.conf
   [Service]
   Environment=GPU_MAX_HW_QUEUES=1
   ```

   *Works if* busy stays close to 0 with both running.
5. **Run the post's measurements:** `experimento_a.sh` to `experimento_d.sh` (on the Proxmox host, with `CT=<container id>`) write the CSVs; `make_figures.py` builds the figures and `resumo_fases.json`.

Known variation: the 2026 report [3] says that on an APU `GPU_MAX_HW_QUEUES=1` made the symptom worse with PyTorch. Test on your card before applying it.

## Reproduction material

Scripts, raw data (one CSV per experiment) and the figure generator: [`labs/multimodelo-duas-gpus/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/multimodelo-duas-gpus).

## References

1. Googulator, "100% GPU usage and high power draw when creating multiple HW queues with MES on RDNA3", ROCm/amdgpu, issue #153, Nov 2023, with comments through 2026. <https://github.com/ROCm/amdgpu/issues/153>. Supports: the same symptom with `llama-server` on RDNA3, tied to hardware-queue creation; the comment suggesting `GPU_MAX_HW_QUEUES` as a workaround; a report on RDNA4.
2. Googulator, "100% GPU usage and high power draw during idle after memcpy/memset with HIP streams on RDNA3", ROCm/ROCm, issue #2625, Nov 2023. <https://github.com/ROCm/ROCm/issues/2625>. Supports: the original report, with minimal HIP cases that reach 100% without running code on the GPU.
3. "gfx1151 (Strix Halo): GPU pinned at 100% busy / max sclk whenever ≥2 idle ROCm compute clients are resident", ROCm/TheRock, issue #7578, Aug 2026. <https://github.com/ROCm/TheRock/issues/7578>. Supports: the "one client rests, two clients stay at 100%" pattern on another card, and the caveat that `GPU_MAX_HW_QUEUES=1` made one PyTorch case worse.
4. Ubuntu, `rocm-smi(1)` manual page, Ubuntu 24.04. <https://manpages.ubuntu.com/manpages/noble/man1/rocm-smi.1.html>. Supports: how `gpu_busy_percent` is computed (SMU sampling of busy blocks).
5. The Linux Kernel documentation, "GPU Power/Thermal Controls and Monitoring" (amdgpu). <https://docs.kernel.org/gpu/amdgpu/thermal.html>. Supports: the meaning of `gpu_busy_percent` and `power1_average`.
6. The Linux Kernel documentation, "DRM client usage stats". <https://docs.kernel.org/gpu/drm-usage-stats.html>. Supports: the `fdinfo` fields (`drm-pdev`, memory per region) used to tell which process uses which card.
7. AMD, "HIP environment variables", HIP documentation (ROCm). <https://rocm.docs.amd.com/projects/HIP/en/latest/reference/env_variables.html>. Supports: `GPU_MAX_HW_QUEUES` sets the maximum number of hardware queues per process and per device (default 4).

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
