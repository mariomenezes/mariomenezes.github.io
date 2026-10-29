---
title: "Syncthing do zero: sincronizando o vault entre dispositivos"
lang: pt-BR
permalink: /pt/2026/10/29/syncthing-vault-sincronizacao/
description: "Configurei Syncthing no Proxmox CT 128 para sincronizar a base de conhecimento ~/vault/ entre dispositivos, com hub central e réplica receive-only no CT 301."
---

*[Read in English]({{ "/en/2026/10/29/syncthing-vault-sincronizacao/" | relative_url }})*

---

## O problema

Tenho a base de conhecimento em `~/vault/` no PC. Precisei espelhar isso para o CT 301 (onde roda o Qdrant e o indexador RAG). Não queria montar NFS — queria algo que funcionasse offline e sincronizasse apenas mudanças.

## A escolha: Syncthing

Syncthing é open source, P2P, sem nuvem intermediária. Perfeito para um homelab.

## O setup

### CT 128 — Hub (send-only)

```bash
# Instalação no CT 128 (Debian LXC)
apt install syncthing
syncthing config --listen-addresses 0.0.0.0:22000
```

- **Pasta:** `~/vault/` (tipo: Send Only)
- **Dispositivo:** ID único registrado no CT 301
- **Dispositivo remoto:** CT 301 (ID do device)
- **Dispositivo remoto:** PC pessoal (ID do device)

### CT 301 — Réplica (receive-only)

```bash
# Pasta em /root/vault-replica/
# Tipo: Receive Only
# Dispositivo source: CT 128
```

- Pasta `vault-replica/` no CT 301 recebe tudo do hub.
- **Receive Only** impede que mudanças no CT 301 afetem o hub.

### CT 128 + PC — Dispositivos

- PC: Syncthing GUI na porta 8384, pasta `~/vault/` como Send-Receive.
- CT 128: Syncthing CLI, pasta `~/vault/` como Send-Only.

## Fluxo de dados

```
PC (~/vault/)  ←Send-Receive→  CT 128 (~/vault/)  →Send-Only→  CT 301 (/root/vault-replica/)
                                                                                     ^
                                                                                     |
                                                                            [Qdrant Indexer]
                                                                            [rag-indexer.py]
```

O indexador RAG lê de `/root/vault-replica/`, nunca da pasta original. Isso isola o Qdrant de mudanças acidentais no vault.

## Testes

- Criei um arquivo no PC → apareceu no CT 301 em ~3 segundos.
- Apaguei no PC → removido do CT 301.
- Modifiquei em CT 128 → propagado para o PC e CT 301.

## Observações

- O CT 128 é um container Debian. Syncthing roda em modo user. Sem systemctl — usei `syncthing serve --no-browser --log-level info`.
- Não configurei TLS: na rede interna (10.0.0.0/24) não é necessário. Para produção, adicionar STN ou TLS via certbot.
- O Syncthing do CT 301 (receive-only) não precisa de GUI. Roda em background.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
