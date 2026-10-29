---
title: "Syncthing from scratch: syncing the vault across devices"
lang: en
permalink: /en/2026/10/29/syncthing-vault-sync/
description: "Set up Syncthing on Proxmox CT 128 to sync the ~/vault/ knowledge base between devices, with a central hub and receive-only replica on CT 301."
---

*[Leia em português]({{ "/pt/2026/10/29/syncthing-vault-sincronizacao/" | relative_url }})*

---

## The problem

I have the knowledge base at `~/vault/` on my PC. Needed to mirror it to CT 301 (where Qdrant and the RAG indexer run). Didn't want NFS — wanted something that works offline and syncs only changes.

## The choice: Syncthing

Syncthing is open source, P2P, no intermediate cloud. Perfect for a homelab.

## The setup

### CT 128 — Hub (send-only)

```bash
# Installation on CT 128 (Debian LXC)
apt install syncthing
syncthing config --listen-addresses 0.0.0.0:22000
```

- **Folder:** `~/vault/` (type: Send Only)
- **Device:** unique ID registered on CT 301
- **Remote device:** CT 301 (device ID)
- **Remote device:** personal PC (device ID)

### CT 301 — Replica (receive-only)

```bash
# Folder at /root/vault-replica/
# Type: Receive Only
# Source device: CT 128
```

- `vault-replica/` folder on CT 301 receives everything from the hub.
- **Receive Only** prevents changes on CT 301 from affecting the hub.

### CT 128 + PC — Devices

- PC: Syncthing GUI on port 8384, `~/vault/` folder as Send-Receive.
- CT 128: Syncthing CLI, `~/vault/` folder as Send-Only.

## Data flow

```
PC (~/vault/)  ←Send-Receive→  CT 128 (~/vault/)  →Send-Only→  CT 301 (/root/vault-replica/)
                                                                                     ^
                                                                                     |
                                                                            [Qdrant Indexer]
                                                                            [rag-indexer.py]
```

The RAG indexer reads from `/root/vault-replica/`, never the original folder. This isolates Qdrant from accidental vault changes.

## Tests

- Created a file on PC → appeared on CT 301 in ~3 seconds.
- Deleted on PC → removed from CT 301.
- Modified on CT 128 → propagated to PC and CT 301.

## Observations

- CT 128 is a Debian container. Syncthing runs in user mode. No systemctl — used `syncthing serve --no-browser --log-level info`.
- Didn't configure TLS: on the internal network (10.0.0.0/24) it's not needed. For production, add STN or TLS via certbot.
- CT 301's Syncthing (receive-only) doesn't need a GUI. Runs in background.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
