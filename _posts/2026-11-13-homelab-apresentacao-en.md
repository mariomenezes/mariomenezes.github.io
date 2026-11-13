---
title: "LAB-00: what fits in a DevOps homelab"
lang: en
permalink: /en/2026/11/13/homelab-apresentacao/
description: "22 services on 3 machines, two of them Celerons with 4 GB of RAM, plus 32 GB of VRAM for local models. The map of the lab behind this series."
resumo: "The map of my homelab: 22 services on 3 machines, two of them Celerons with 4 GB of RAM, plus 32 GB of VRAM for local models. Financially it makes no sense; I do it anyway."
image: /assets/img/homelab-apresentacao/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/13/homelab-apresentacao/" | relative_url }})*

<span class="pill">LAB series · post 00 of 11 · state as of 2026-11-13</span>

Financially, this lab makes no sense. No return closes the power and hardware bill. I keep it for four reasons: privacy (my data and my models stay at home), learning, fun and, now and then, a good dose of grey hair.

This post is the map. The next 11 show what I measured on it, including what went wrong. Nothing here is production: it is a lab.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-aberto-16x9.jpg' | relative_url }}" alt="The lab rack with the door open: chassis, patch panel with blue cables, router, Grandstream GWN7832 switch and the four-bay NAS." loading="lazy">
<figcaption>The rack, front view. Machine labels were blurred. What to look at: the 12-port SFP+ (10 Gb) Grandstream switch, just above the NAS, has no node connected to it.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">22</div><div class="tile-label">running services (20 LXC + 2 VMs)</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">Proxmox nodes, plus 1 guest workstation</div></div>
<div class="tile"><div class="tile-value">72 GB</div><div class="tile-label">of installed RAM across the 3 nodes</div></div>
<div class="tile"><div class="tile-value">32 GB</div><div class="tile-label">of VRAM in the rack (2 × 16 GB)</div></div>
</div>

## Summary

- The three nodes add up to 16 threads and 72 GB of installed RAM. Two of them are Celeron N4020 machines with 4 GB each: they run 16 light services and nothing else.
- All the heavy load sits on one node (Ryzen 5 5600G, 64 GB): two GPUs for local models, the semantic router, monitoring and the two Kubernetes cluster VMs. **That node is not always on.** The two smaller ones run 24 hours a day.
- The fastest GPU (RX 7900 XTX, 24 GB) is **not part of the lab**: it is my workstation. It joins the router when powered on.
- The network is gigabit, with a MikroTik RB3011 router and VLANs that split five networks: mobile devices, servers, administration, security and IoT. There is an idle 10 Gb switch (Grandstream GWN7832, 12 SFP+ ports), unused: the nodes have 1 Gb NICs, so nothing here would use the 10G.
- The NAS is a Ubiquiti UNVR, a 4-bay network video recorder, converted into a NAS: Linux with RAID 1 on two pools (two HDDs and two SSDs).
- A MacBook Air with a broken screen and no video output over its USB-C ports plays two roles: it runs Jellyfin (media server) and it is my remote workstation. It is where I centralize my work, reach in from outside, connect VS Code and use an AI assistant with many skills and MCPs, with read-only Kubernetes accounts for management. It and the NAS are not part of the 22-service count, which are Proxmox guests.
- The two Kubernetes "clusters" are single-node VMs on the same host. The Istio multicluster setup is real, the scale is not.
- Power draw is now measured with a smart plug: on 2026-11-13 at 8 pm the whole rack drew 172 W, of which 75 W was Node C. Monthly figures and cost come in post 10.

## Environment

| Item | Node A | Node B | Node C |
|---|---|---|---|
| CPU | Celeron N4020, 2 cores | Celeron N4020, 2 cores | Ryzen 5 5600G, 6 cores / 12 threads |
| Installed RAM | 4 GB (1 × DDR4) | 4 GB (1 × DDR4) | 64 GB (4 × 16 GB DDR4-2400) |
| Disk | 120 GB SSD | 480 GB SSD | 2 × 1 TB NVMe + 240 GB SSD |
| Proxmox VE | 8.4.21 (kernel 6.8.12) | 8.4.21 (kernel 6.8.12) | 8.4.19 (kernel 6.14.11) |
| Running | 9 LXC | 7 LXC | 4 LXC + 2 VMs |
| GPU | none | none | 2 × Radeon RX 9060 XT, 16 GB each |

The operating system sees less than the installed RAM: 3.65 GiB on nodes A and B and 62.7 GiB on Node C. The difference is memory reserved by the firmware and the kernel; on Node C, `dmesg` reports about 131 MiB from the firmware and 1.30 GiB reserved by the kernel.

### Network and supporting equipment

| Equipment | Role |
|---|---|
| MikroTik RB3011UiAS-RM | router and VLANs |
| Grandstream GWN7802P | managed switch |
| Grandstream GWN7832 | L3 aggregation switch, 12 × 10 Gb SFP+ ports, idle |
| Ubiquiti UNVR (converted) | 4-bay NAS: RAID 1 of 2 × 3 TB HDDs and RAID 1 of 2 × 960 GB SSDs |
| MacBook Air (Apple M1, 8 GB) | media server (Jellyfin) and remote workstation (VS Code, AI assistant with MCPs, read-only Kubernetes accounts); broken screen, no video over USB-C |
| Personal workstation (desktop) | 24 GB RX 7900 XTX; outside the lab |

Model software: llama.cpp build 216 (`f12cc6d`), ROCm 7.2.3 and the `amdgpu` driver that ships with the kernel. Extra storage over NFS from a NAS. Network: gigabit between all nodes.

Kubernetes cluster "a" (versions read on 2026-11-13): k0s 1.36.4 with one node, Cilium 1.16.5, Istio 1.31.1, Flagger 1.45.0, cert-manager 1.15.3, Prometheus 2.55.0, Jaeger 1.62.0 and OpenTelemetry Collector 0.160.0.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/ambiente-en.svg' | relative_url }}" alt="Environment diagram: three Proxmox nodes (two Celerons and one Ryzen with two GPUs), a NAS and, outside the lab, the personal workstation with the RX 7900 XTX.">
<figcaption>The three nodes and the guest workstation. What to look at: all the AI and cluster load is on Node C. The dashed box is outside the lab.</figcaption>
</figure>

### Inside

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/no-c-interior-16x9.jpg' | relative_url }}" alt="Top view inside the Node C chassis: Gigabyte motherboard with a Ryzen and stock cooler, four memory modules, an NVMe drive, a 650 W power supply and two Radeon cards, a Sapphire and a PowerColor." loading="lazy">
<figcaption>Node C inside: Ryzen 5 5600G, four RAM modules, one NVMe drive and two 16 GB Radeons. The cables are exactly as messy as they look.</figcaption>
</figure>

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/workstation-16x9.jpg' | relative_url }}" alt="White workstation case with the XFX Radeon RX 7900 XTX visible through the glass panel." loading="lazy">
<figcaption>The guest workstation, with the 24 GB RX 7900 XTX.</figcaption>
</figure>

## Four layers

1. **Local AI.** A 35-billion-parameter model (Qwen3.6-35B-A3B, Q4_K_M quantization) split across the two 16 GB GPUs, behind a semantic router that also uses the workstation when it is on.
2. **Operations.** Prometheus, Grafana and phone alerts.
3. **Data and sync.** Semantic search over my notes and sync across subnets.
4. **Experiments.** Two k0s clusters with multicluster Istio, where the failure-detection studies run.

## What has already gone wrong (the grey hair)

| Symptom | Cause | Post |
|---|---|---|
| 208 ffmpeg failures in one day | a network share unmounted and clients retried in a loop | 07 |
| 502 on long sessions | the fallback model had a real context of 16k tokens, far below what the router advertised | 05 |
| GPU at 100% with no requests | two llama.cpp processes on the same card | 03 |

## The series

Twelve posts, two per week, always in pt-BR and en: the per-feature detector, the lab that was dev and prod at once, the GPU stuck at 100%, Vulkan versus HIP, what happens when the main GPU drops, 128k tokens of context on 2 × 16 GB, the 208 share failures, Proxmox in read-only mode, the search index cleanup, the lab's energy use and, finally, where the router got it wrong.

Series rules: every number has a script and raw data; negative results go in the summary; no IPs, hostnames or personal services.

## Limits

- The count of 22 services is guests running on 2026-11-13, with Node C on. The 16 services on nodes A and B run 24 hours a day. The 6 on Node C only exist while it is on, and it is not always on: from plug consumption, in October it was on the equivalent of about a third of the month (estimate, at 75 W). Other guests are stopped and left out.
- RAM and disk figures are for the hosts, not the guests.
- Cluster "b" was not inspected on this date; the versions above are from cluster "a".
- I did not test isolation between the VLANs: I describe the separation, I did not verify it with tests.
- I did not measure temperature or availability over time. Power was measured only with a smart plug, with no inference load.

## References

- Proxmox VE: <https://www.proxmox.com/en/products/proxmox-virtual-environment/overview>
- k0s: <https://k0sproject.io/>
- Istio multicluster: <https://istio.io/latest/docs/setup/install/multicluster/>
- llama.cpp: <https://github.com/ggml-org/llama.cpp>

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
