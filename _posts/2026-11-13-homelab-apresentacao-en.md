---
title: "LAB-00: what runs in my DevOps homelab"
lang: en
permalink: /en/2026/11/13/homelab-apresentacao/
description: "The map of the lab: 22 services on 3 Proxmox nodes, 72 GB of RAM, 32 GB of VRAM, two Kubernetes clusters, local AI and cameras — including what is switched off and what I never measured."
resumo: "What runs in my homelab: photos, files, media, cameras (Frigate), local AI, monitoring and two Kubernetes clusters, on 3 Proxmox nodes, a NAS and a workstation. Financially it makes no sense; I do it anyway."
image: /assets/img/homelab-apresentacao/cover-en.png
---

*[Leia em português]({{ "/pt/2026/11/13/homelab-apresentacao/" | relative_url }})*

<p class="status"><span class="pill">LAB series · post 00 of 12</span> <span>State of the lab on 13 November 2026</span></p>

Financially, this lab makes no sense: nothing it produces pays for the electricity and the hardware. I keep it for four reasons — privacy (my data and my models stay at home), learning, fun and, every now and then, a solid dose of grey hair.

This post is the map: what exists, where it runs, what is switched off and what I have not measured yet. The next twelve posts cover the measurements, bad results included. Nothing here is production: it is a lab, and I only publish what I can reproduce.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-aberto-16x9.jpg' | relative_url }}" alt="The lab rack with the door open: chassis, patch panel with blue cables, router, Grandstream GWN7832 switch and the four-bay NAS." loading="lazy">
<figcaption>The rack, front view. Machine labels were blurred. What to look at: the 12-port SFP+ (10 Gb) Grandstream switch, just above the NAS, has no node connected to it.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">22</div><div class="tile-label">running services (20 LXC + 2 VMs)</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">Proxmox nodes, plus 1 workstation that joins as a guest</div></div>
<div class="tile"><div class="tile-value">72 GB</div><div class="tile-label">of installed RAM across the 3 nodes</div></div>
<div class="tile"><div class="tile-value">32 GB</div><div class="tile-label">of VRAM in the rack (2 × 16 GB)</div></div>
</div>

<div class="callout note" markdown="1">
**How I count a "service":** one Proxmox guest, LXC or VM, that was running on 2026-11-13. The NAS, the MacBook Air and the desktop workstation are not guests and stay out of the count of 22. Stopped guests are out too.
</div>

## Summary

- **The three nodes add up to 16 threads and 72 GB of installed RAM**, but the split is deliberately lopsided: two of them are Celeron N4020 machines with 4 GB each, running 16 light services, 24 hours a day.
- **All the heavy load sits on a single node** (Ryzen 5 5600G, 64 GB): two GPUs for local models, the semantic router, monitoring and the two Kubernetes cluster VMs. **That node is not always on** — it is the central trade-off of the lab, and it shows up in nearly every limit listed here.
- **What that costs me:** Frigate (an NVR with object detection) is one of the services I care about most, and it is off today for one reason only — it lives on that node.
- **The fastest GPU is not part of the lab.** The 24 GB RX 7900 XTX belongs to my workstation: it joins the model router when the machine is powered on, and the rest of the time it is the household game-streaming server.
- **Both Kubernetes "clusters" are single-node VMs on the same host.** The Istio multicluster setup is real; the scale is not. That caveat holds for the whole series.
- **Power is already measured:** a spot reading of 172 W for the whole rack, 75 W of it Node C, on 2026-11-13 at 8 pm. It is a single reading, not an average; monthly figures and cost come in post 10.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-frontal-alto.jpg' | relative_url }}" alt="The whole rack, front view, top to bottom: power strip, patch panel with blue cables, router, switches, the four-bay NAS, shelves with mini PCs and a laptop, and a 4U chassis with a lock." loading="lazy" style="max-width:420px;margin:0 auto">
<figcaption>The whole rack, front view. Top to bottom: power, network, NAS, shelves with mini PCs and a laptop, and a 4U chassis. Machine labels were blurred.</figcaption>
</figure>

## What runs here

These are the services I actually use, grouped by what they do. Frigate is in the table even though it is switched off, because it is one of the services that matter most to me.

| Layer | What runs | Where |
|---|---|---|
| Personal data | Immich (photos), Nextcloud (files) and Syncthing (syncing my notes), with the data on the NAS | Nodes A and B |
| Media | Jellyfin, and the library automation with Radarr, Sonarr, Prowlarr, Bazarr, Seerr and qBittorrent | Mac and nodes A and B |
| Surveillance | **Frigate**, an NVR with object detection and access to the node's GPU, for the security cameras | Node C (off today) |
| Local AI | llama.cpp serving a 35-billion-parameter model, vLLM Semantic Router (semantic routing with failover) and Qdrant (semantic search over my notes) | Node C and workstation |
| Network and access | Nginx Proxy Manager (reverse proxy), Pi-hole (ad-blocking DNS), Vaultwarden (password manager) and Homepage (landing dashboard) | Node A |
| Observability | Prometheus, Grafana (9 dashboards), Jaeger, OpenTelemetry Collector and ntfy (phone alerts) | Nodes B and C |
| Platform | two k0s clusters with Cilium, multicluster Istio, Flagger and cert-manager, plus a container registry | Node C (clusters) and Node A (registry) |
| Games | **Sunshine** (game-streaming server) and, on the clients, Moonlight | Workstation, **not** on the cluster nodes |

All of this runs locally, on my own hardware, inside the home network: **none of these services is published to the internet**. Access from outside goes over a VPN. Sunshine runs on the workstation, not on the nodes; the Moonlight clients are scattered around the house — one of them is a Celeron mini PC, identical to the nodes, that boots straight into a lightweight Wayland compositor dedicated to that job. It is the subject of post 12.

## Environment

| Item | Node A | Node B | Node C |
|---|---|---|---|
| CPU | Celeron N4020, 2 cores | Celeron N4020, 2 cores | Ryzen 5 5600G, 6 cores / 12 threads |
| Installed RAM | 4 GB (1 × DDR4-2133) | 4 GB (1 × DDR4-2133) | 64 GB (4 × 16 GB DDR4-2400) |
| Disk | 120 GB SSD | 480 GB SSD | 2 × 1 TB NVMe + 240 GB SSD |
| GPU | none | none | 2 × Radeon RX 9060 XT, 16 GB each |
| Hypervisor | Proxmox VE | Proxmox VE | Proxmox VE |
| Running guests | 9 LXC | 7 LXC | 4 LXC + 2 VMs |
| Availability | 24 × 7 | 24 × 7 | on demand |

The operating system sees less than the installed RAM: 3.65 GiB on nodes A and B and 62.7 GiB on Node C. The difference is memory reserved by the firmware and the kernel; on Node C, `dmesg` reports about 131 MiB from the firmware and 1.30 GiB reserved by the kernel. It is the kind of detail that changes the arithmetic when you size a guest.

### Network

The network is gigabit, with a MikroTik router and VLANs that carve it into five segments: mobile devices, servers, administration, security and IoT. The three nodes and the NAS sit on the servers VLAN.

| Equipment | Role |
|---|---|
| MikroTik RB3011UiAS-RM | router and VLANs |
| Grandstream GWN7802P | managed switch |
| Grandstream GWN7832 | L3 aggregation switch, 12 × 10 Gb SFP+ ports — **idle** |
| Ubiquiti UNVR (converted) | 4-bay NAS: RAID 1 of 2 × 3 TB HDDs (slow pool) and RAID 1 of 2 × 960 GB SSDs (fast pool), serving Samba and NFS |
| MacBook Air (Apple M1, 8 GB) | media server (Jellyfin) and my remote workstation: VS Code, an AI assistant with skills and MCPs, and read-only Kubernetes accounts for management; broken screen, no video over USB-C |
| Desktop workstation | Ryzen 7 7800X3D, MSI B650M board, 24 GB RX 7900 XTX, 1 TB NVMe, Ubuntu; runs Sunshine and lends its GPU to the model router — outside the lab |

The 10 Gb switch is the most visible bad purchase in the rack: the nodes have 1 Gb NICs, so **nothing here would use the 10G**. It sits there, powered on, without a single node plugged into it.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/ambiente-en.svg' | relative_url }}" alt="Environment diagram. The internet enters the MikroTik RB3011 router, which feeds two Grandstream switches, one of them an idle 10 Gb unit. Five VLANs leave the router: mobile devices, servers, administration, security and IoT. The servers VLAN holds nodes A, B and C and the Ubiquiti UNVR NAS. Outside the lab are the workstation with the RX 7900 XTX, the MacBook Air and the Celeron Moonlight client." loading="lazy">
<figcaption>Lab hardware and network. The router opens five VLANs and the three nodes and the NAS sit on the servers VLAN. Node C is the only one that is not always on, and the 10 Gb switch is idle. Dashed boxes are outside the lab.</figcaption>
</figure>

### Platform and local AI

The two Kubernetes clusters are single-node k0s installs, one per VM, both on Node C: Cilium, Istio in multi-primary mode, Flagger, cert-manager, Prometheus, Jaeger and OpenTelemetry Collector. They are where the canary and service mesh experiments in this series run.

On the model side: llama.cpp on ROCm and the `amdgpu` driver that ships with the kernel, with 128k tokens of context split across the two 16 GB Radeons, plus a small model for code completion and an embedding model for search over my notes. The semantic router picks the destination from the intent of the request and falls back to the local GPU when the workstation is off. Extra storage comes over NFS from the NAS.

### Inside

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/no-c-interior-16x9.jpg' | relative_url }}" alt="Top view inside the Node C chassis: Gigabyte motherboard with a Ryzen and stock cooler, four memory modules, an NVMe drive, a 650 W power supply and two Radeon cards, a Sapphire and a PowerColor." loading="lazy">
<figcaption>Node C inside: Ryzen 5 5600G, four RAM modules, one NVMe drive and two 16 GB Radeons. The cables are exactly as messy as they look.</figcaption>
</figure>

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/workstation-16x9.jpg' | relative_url }}" alt="White workstation case with the XFX Radeon RX 7900 XTX visible through the glass panel." loading="lazy">
<figcaption>The guest workstation, with the 24 GB RX 7900 XTX.</figcaption>
</figure>

## What has already gone wrong (the grey hair)

| Symptom | Cause | Post |
|---|---|---|
| 208 ffmpeg failures in one day | a network share unmounted and clients retried in a loop | 07 |
| 502s on long sessions | the fallback model had a real context of 16k tokens, far below what the router advertised | 05 |
| GPU at 100% with no requests | two llama.cpp processes on the same card | 03 |

## The series

Twelve posts after this one, two a week, always in pt-BR and en:

| Post | Topic |
|---|---|
| 01 | the per-feature detector versus Flagger |
| 02 | the lab that was dev and prod at the same time |
| 03 | the GPU stuck at 100% doing nothing |
| 04 | Vulkan versus HIP in llama.cpp |
| 05 | what happens when the main GPU drops |
| 06 | 128k tokens of context on 2 × 16 GB |
| 07 | the 208 network-share failures |
| 08 | Proxmox in read-only mode |
| 09 | cleaning up the search index |
| 10 | the lab's power draw, measured at the plug |
| 11 | where the semantic router got it wrong |
| 12 | the Celeron that became a game client |

Series rules: every number has a script and raw data; negative results go in the summary; no IPs, hostnames or personal services.

## Limits

- The count of 22 services is guests running on 2026-11-13, **with Node C powered on**. The 16 services on nodes A and B run 24 hours a day; the 6 on Node C only exist while it is up. From plug consumption, in October it was on for the equivalent of about a third of the month (estimate, at 75 W).
- RAM and disk figures are for the hosts, not the guests.
- Cluster "b" was not inspected on this date.
- For Frigate I only describe what is configured: I measured nothing about it (camera count, retention, load) and it is switched off.
- I did not test isolation between the VLANs: I describe the separation, I did not verify it with tests.
- I did not measure temperature or availability over time. Power was measured only with a smart plug, with no inference load, and the rack plug also covers the NAS, the Mac, the router and the switches.

## References

- Proxmox VE: <https://www.proxmox.com/en/products/proxmox-virtual-environment/overview>
- k0s: <https://k0sproject.io/>
- Istio multicluster: <https://istio.io/latest/docs/setup/install/multicluster/>
- llama.cpp: <https://github.com/ggml-org/llama.cpp>
- Frigate: <https://frigate.video/>
- Sunshine and Moonlight: <https://github.com/LizardByte/Sunshine> and <https://moonlight-stream.org/>

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
