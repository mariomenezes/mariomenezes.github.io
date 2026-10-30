---
title: "Syncthing across subnets: rebuilding from scratch, a fixed address and a read-only replica"
lang: en
permalink: /en/2026/10/29/syncthing-vault-sync/
description: "Lab notes: I synced a notes folder between a PC and a server on different subnets, rebuilding the Syncthing install from scratch, with a fixed address and a read-only replica for the indexer."
resumo: "Notes synced across subnets with Syncthing rebuilt from scratch, a fixed address and a read-only replica. A note reaches the server in about 9 s."
image: /assets/img/syncthing-vault-sincronizacao/cover-en.png
---

*[Leia em português]({{ "/pt/2026/10/29/syncthing-vault-sincronizacao/" | relative_url }})*

<p class="status"><span class="pill">Lab</span> <span>October 29, 2026 · <a href="#what-went-wrong">what went wrong</a></span></p>

My infrastructure notes live on a PC. I wanted the same folder on an always-on server, for the RAG indexer, and on my other devices. The PC and the server are on different subnets, so automatic discovery did not work.

## Summary

- **I rebuilt the install from scratch** instead of fixing the old one, which had duplicate folders and a device with no name.
- **I kept the server's device identity**, so the other devices still recognize it.
- **The PC connects by fixed address**, because discovery does not cross subnets.
- **Sync tested in both directions** on the notes folder.
- **A read-only replica** on the RAG server: nothing that arrives there flows back to the source.
- **Pending:** adding the phones and the other laptop.

## Environment

| Item | Value |
|---|---|
| Hub | Debian 13 container on Proxmox, Syncthing 2.1.2, panel on the LAN with login |
| Replica | RAG service container, Syncthing 1.19.2, folder in *receive-only* mode |
| Work PC | Syncthing on the same folder, connected to the hub by fixed address |
| Folder | infrastructure notes, with plans, reports and documentation |

Addresses, device identifiers and passwords are left out of this text.

## Layout

<pre class="mermaid">
flowchart LR
  P["work PC"] <-->|"send and receive"| H["hub (container)"]
  H -->|"send"| R["receive-only replica (RAG)"]
  M["other devices"] <-->|"pending"| H
</pre>

## Why rebuild

The old configuration had duplicate folders and a device with no name. Fixing each piece took more work than starting again. I rebuilt the install and kept the server's device identity, so the other devices would not need to accept it again.

## Fixed address

Automatic discovery depends on being on the same local network, and the PC and the server are not. I configured the PC to connect to the hub at the server's fixed address. That works as long as the address stays fixed.

## Read-only replica

The RAG indexer reads from a replica in *receive-only* mode. So nothing the indexer or the server writes to the folder flows back to the PC. The indexer only reads the notes.

## Test

In the session report, I created and changed files on both sides and confirmed the changes arrived on the other.

I then measured the propagation of a new file, from the PC to the hub and to the replica, over 10 runs. Each run creates a file in a drafts folder, which the indexer ignores, and records when it appears at each destination.

<figure class="fig">
<img src="{{ "/assets/img/syncthing-vault-sincronizacao/sync-en.svg" | relative_url }}" alt="Dots showing the time until a new file appears on the hub and on the replica, over 10 runs. Almost all sit at 9 seconds; the first run takes 13 seconds." loading="lazy">
<figcaption>Time until the file appears. Median of 9.0 s on the hub and on the replica, which show it at almost the same instant. The first run took 13.3 s. I did not measure each stage separately.</figcaption>
</figure>

Both destinations show the file at almost the same instant, so nearly all the time is spent before the hub. My hypothesis is that the delay is the change-detection interval on the source PC, close to Syncthing's 10 s default. I did not check the configuration to confirm it.

## What went wrong

| Symptom | Cause | Fix |
|---|---|---|
| Duplicate folders in the old install | accumulated configuration | rebuilt from scratch |
| Device with no name | old configuration | recreated with a name |
| PC could not find the server | different subnets | fixed address |

## Limits

- Only the PC and the server are connected. The phones and the other laptop are not yet.
- I measured propagation only for small files, in one direction, over 10 runs.
- I did not measure behavior with large files or with several changes at the same time.
- The connection depends on a fixed address; a network change needs a manual update.

---

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
