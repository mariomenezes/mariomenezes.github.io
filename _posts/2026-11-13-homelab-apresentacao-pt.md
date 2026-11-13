---
title: "LAB-00: o que cabe num homelab de DevOps"
lang: pt-BR
permalink: /pt/2026/11/13/homelab-apresentacao/
description: "22 serviços em 3 máquinas, duas delas com Celeron e 4 GB de RAM, mais 32 GB de VRAM para modelos locais. O mapa do laboratório que alimenta esta série."
resumo: "O mapa do meu homelab: 22 serviços em 3 máquinas, duas delas com Celeron e 4 GB de RAM, mais 32 GB de VRAM para modelos locais. Financeiramente não faz sentido; faço mesmo assim."
image: /assets/img/homelab-apresentacao/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/13/homelab-apresentacao/" | relative_url }})*

<span class="pill">Série LAB · post 00 de 12 · estado em 13/11/2026</span>

Financeiramente, este laboratório não faz sentido. Não há retorno que feche a conta de energia e de hardware. Eu o mantenho por quatro motivos: privacidade (meus dados e meus modelos ficam em casa), estudo, diversão e, de vez em quando, uma boa dose de cabelo branco.

Este post é o mapa. Os próximos 12 mostram o que medi nele, incluindo o que deu errado. Nada aqui é produção: é um laboratório.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-aberto-16x9.jpg' | relative_url }}" alt="O rack do laboratório com a porta aberta: chassi, patch panel com cabos azuis, roteador, switch Grandstream GWN7832 e o NAS de quatro baias." loading="lazy">
<figcaption>O rack, de frente. Os rótulos de máquina foram borrados. O que olhar: o switch Grandstream de 12 portas SFP+ (10 Gb), logo acima do NAS, não tem nenhum nó ligado a ele.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">22</div><div class="tile-label">serviços ligados (20 LXC + 2 VMs)</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">nós Proxmox, mais 1 workstation convidada</div></div>
<div class="tile"><div class="tile-value">72 GB</div><div class="tile-label">de RAM instalada nos 3 nós</div></div>
<div class="tile"><div class="tile-value">32 GB</div><div class="tile-label">de VRAM no rack (2 × 16 GB)</div></div>
</div>

## Resumo

- Os três nós somam 16 threads e 72 GB de RAM instalada. Dois deles são Celeron N4020 com 4 GB cada: rodam 16 serviços leves e nada mais.
- Toda a carga pesada está em um nó (Ryzen 5 5600G, 64 GB): duas GPUs para modelos locais, o roteador semântico, o monitoramento e as duas VMs dos clusters Kubernetes. **Esse nó nem sempre fica ligado.** Os dois menores ficam ligados 24 horas por dia.
- A GPU mais rápida (RX 7900 XTX, 24 GB) **não faz parte do laboratório**: é a minha workstation. Ela entra no roteador quando está ligada e também é o meu servidor de streaming de jogos: roda o Sunshine, e eu jogo de qualquer ponto da casa com o Moonlight. Um dos clientes é um mini PC com Celeron, igual aos nós, que dá boot direto num compositor Wayland leve e dedicado a isso. Ele merece um post só dele.
- A rede é gigabit, com um roteador MikroTik RB3011 e VLANs que separam cinco redes: dispositivos móveis, servidores, administração, segurança e IoT. Existe um switch de 10 Gb (Grandstream GWN7832, 12 portas SFP+) parado, sem uso: os nós têm placas de 1 Gb, então nada aqui aproveitaria o 10G.
- O NAS é um Ubiquiti UNVR, um gravador de vídeo de rede de 4 baias, convertido em NAS: Linux com dois pools, um de armazenamento lento (dois HDs) e um rápido (dois SSDs), ambos em RAID 1.
- Um MacBook Air com a tela quebrada e sem saída de vídeo pelas portas USB-C faz dois papéis: roda o Jellyfin (servidor de mídia) e é a minha workstation remota. É nele que eu centralizo o trabalho, acesso de fora, conecto o VS Code e uso um assistente de IA com várias skills e MCPs, com contas somente leitura no Kubernetes para a gerência. Ele e o NAS não entram na contagem de 22 serviços, que são guests do Proxmox.
- Os dois "clusters" Kubernetes são VMs de nó único no mesmo host. O multicluster do Istio é real, a escala não.
- O consumo de energia já está medido por tomada inteligente: em 13/11, às 20h, o rack inteiro gastava 172 W, dos quais 75 W eram do Nó C. Os números mensais e o custo saem no post 10.

## Ambiente

| Item | Nó A | Nó B | Nó C |
|---|---|---|---|
| CPU | Celeron N4020, 2 núcleos | Celeron N4020, 2 núcleos | Ryzen 5 5600G, 6 núcleos / 12 threads |
| RAM instalada | 4 GB (1 × DDR4) | 4 GB (1 × DDR4) | 64 GB (4 × 16 GB DDR4-2400) |
| Disco | SSD 120 GB | SSD 480 GB | 2 × NVMe 1 TB + SSD 240 GB |
| Proxmox VE | 8.4.21 (kernel 6.8.12) | 8.4.21 (kernel 6.8.12) | 8.4.19 (kernel 6.14.11) |
| Ligados | 9 LXC | 7 LXC | 4 LXC + 2 VMs |
| GPU | nenhuma | nenhuma | 2 × Radeon RX 9060 XT, 16 GB cada |

O sistema enxerga menos do que a RAM instalada: 3,65 GiB nos nós A e B e 62,7 GiB no Nó C. A diferença é memória reservada pelo firmware e pelo kernel; no Nó C, o `dmesg` informa cerca de 131 MiB do firmware e 1,30 GiB reservados pelo kernel.

### Rede e equipamentos de apoio

| Equipamento | Papel |
|---|---|
| MikroTik RB3011UiAS-RM | roteador e VLANs |
| Grandstream GWN7802P | switch gerenciável |
| Grandstream GWN7832 | switch L3 de agregação, 12 portas SFP+ de 10 Gb, parado |
| Ubiquiti UNVR (convertido) | NAS de 4 baias: RAID 1 de 2 HDs de 3 TB e RAID 1 de 2 SSDs de 960 GB |
| MacBook Air (Apple M1, 8 GB) | servidor de mídia (Jellyfin) e workstation remota (VS Code, assistente de IA com MCPs, contas somente leitura no Kubernetes); tela quebrada e sem vídeo pelas portas USB-C |
| Workstation pessoal (desktop) | Ryzen 7 7800X3D, placa MSI B650M, RX 7900 XTX de 24 GB, NVMe de 1 TB, Ubuntu 26.04; servidor de streaming de jogos (Sunshine); fora do laboratório |

Software dos modelos: llama.cpp build 216 (`f12cc6d`), ROCm 7.2.3 e driver `amdgpu` do próprio kernel. Armazenamento extra por NFS, de um NAS. Rede: gigabit entre todos os nós.

Cluster Kubernetes "a" (versões lidas em 13/11/2026): k0s 1.36.4 com um nó, Cilium 1.16.5, Istio 1.31.1, Flagger 1.45.0, cert-manager 1.15.3, Prometheus 2.55.0, Jaeger 1.62.0 e OpenTelemetry Collector 0.160.0.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/ambiente-pt.svg' | relative_url }}" alt="Diagrama do ambiente: três nós Proxmox (dois Celeron e um Ryzen com duas GPUs), um NAS e, fora do laboratório, a workstation pessoal com a RX 7900 XTX.">
<figcaption>Os três nós e a workstation convidada. O que olhar: toda a carga de IA e dos clusters está no Nó C. A caixa tracejada está fora do laboratório.</figcaption>
</figure>

### Por dentro

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/no-c-interior-16x9.jpg' | relative_url }}" alt="Interior do chassi do Nó C visto de cima: placa-mãe Gigabyte com Ryzen e cooler de fábrica, quatro módulos de memória, NVMe, fonte de 650 W e duas placas Radeon, uma Sapphire e uma PowerColor." loading="lazy">
<figcaption>O Nó C por dentro: Ryzen 5 5600G, quatro módulos de RAM, um NVMe e duas Radeon de 16 GB. Os cabos são exatamente como parecem.</figcaption>
</figure>

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/workstation-16x9.jpg' | relative_url }}" alt="Gabinete branco da workstation com a placa XFX Radeon RX 7900 XTX visível pelo painel de vidro." loading="lazy">
<figcaption>A workstation convidada, com a RX 7900 XTX de 24 GB.</figcaption>
</figure>

## Quatro camadas

1. **IA local.** Um modelo de 35 bilhões de parâmetros (Qwen3.6-35B-A3B, quantização Q4_K_M) dividido nas duas GPUs de 16 GB, atrás de um roteador semântico que também usa a workstation quando ela está ligada.
2. **Operação.** Prometheus, Grafana e avisos no celular.
3. **Dados e sincronização.** Busca semântica sobre as minhas notas e sincronização entre sub-redes.
4. **Experimentos.** Dois clusters k0s com Istio multicluster, onde rodam os estudos de detecção de falha.

## O que já deu errado (os cabelos brancos)

| Sintoma | Causa | Post |
|---|---|---|
| 208 falhas do ffmpeg em um dia | um compartilhamento de rede desmontou e os clientes repetiram o pedido em laço | 07 |
| 502 em sessões longas | o modelo de reserva tinha contexto real de 16 mil tokens, bem abaixo do que o roteador anunciava | 05 |
| GPU a 100% sem nenhum pedido | dois processos do llama.cpp na mesma placa | 03 |

## A série

Treze posts, dois por semana, sempre em pt-BR e en: o detector por feature, o lab que era dev e prod ao mesmo tempo, a GPU a 100% parada, Vulkan contra HIP, o que acontece quando a GPU principal cai, 128 mil tokens de contexto em 2 × 16 GB, as 208 falhas do compartilhamento, o Proxmox em modo somente leitura, a limpeza do índice de busca, a energia do laboratório, onde o roteador errou e, por fim, o Celeron que virou cliente de jogos.

Regras da série: todo número tem script e dado bruto; resultado negativo entra no resumo; nada de IPs, hostnames ou serviços pessoais.

## Limites

- A contagem de 22 serviços considera guests ligados em 13/11/2026, com o Nó C ligado. Os 16 serviços dos nós A e B ficam ligados 24 horas por dia. Os 6 do Nó C só existem quando ele está ligado, e ele nem sempre está: pelo consumo na tomada, em outubro ele ficou ligado o equivalente a cerca de um terço do mês (estimativa, a 75 W). Outros guests estão parados e ficam fora.
- Os números de RAM e disco são dos hospedeiros, não dos guests.
- O cluster "b" não foi inspecionado nesta data; as versões acima são do cluster "a".
- Não testei o isolamento entre as VLANs: descrevo a separação, não a verifiquei com testes.
- Não medi temperatura nem disponibilidade ao longo do tempo. O consumo de energia foi medido só em tomada inteligente, sem carga de inferência.

## Referências

- Proxmox VE: <https://www.proxmox.com/en/products/proxmox-virtual-environment/overview>
- k0s: <https://k0sproject.io/>
- Istio multicluster: <https://istio.io/latest/docs/setup/install/multicluster/>
- llama.cpp: <https://github.com/ggml-org/llama.cpp>

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
