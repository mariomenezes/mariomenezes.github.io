---
title: "LAB-00: o que roda no meu homelab de DevOps"
lang: pt-BR
permalink: /pt/2026/11/13/homelab-apresentacao/
description: "O mapa do laboratório: 22 serviços em 3 nós Proxmox, 72 GB de RAM, 32 GB de VRAM, dois clusters Kubernetes, IA local e câmeras — com o que está desligado e o que não foi medido."
resumo: "O que roda no meu homelab: fotos, arquivos, mídia, câmeras (Frigate), IA local, monitoramento e dois clusters Kubernetes, em 3 nós Proxmox, um NAS e uma workstation. Financeiramente não faz sentido; faço mesmo assim."
image: /assets/img/homelab-apresentacao/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/13/homelab-apresentacao/" | relative_url }})*

<p class="status"><span class="pill">Série LAB · post 00 de 12</span> <span>Estado do laboratório em 13 de novembro de 2026</span></p>

Financeiramente, este laboratório não faz sentido: não existe retorno que pague a energia e o hardware. Eu o mantenho por quatro motivos — privacidade (meus dados e meus modelos ficam em casa), estudo, diversão e, de vez em quando, uma boa dose de cabelo branco.

Este post é o mapa: o que existe, onde roda, o que está desligado e o que eu ainda não medi. Os próximos doze mostram as medições, incluindo os resultados ruins. Nada aqui é produção: é um laboratório, e o que eu publico é o que eu consigo reproduzir.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-aberto-16x9.jpg' | relative_url }}" alt="O rack do laboratório com a porta aberta: chassi, patch panel com cabos azuis, roteador, switch Grandstream GWN7832 e o NAS de quatro baias." loading="lazy">
<figcaption>O rack, de frente. Os rótulos de máquina foram borrados. O que olhar: o switch Grandstream de 12 portas SFP+ (10 Gb), logo acima do NAS, não tem nenhum nó ligado a ele.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">22</div><div class="tile-label">serviços ligados (20 LXC + 2 VMs)</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">nós Proxmox, mais 1 workstation que entra como convidada</div></div>
<div class="tile"><div class="tile-value">72 GB</div><div class="tile-label">de RAM instalada nos 3 nós</div></div>
<div class="tile"><div class="tile-value">32 GB</div><div class="tile-label">de VRAM no rack (2 × 16 GB)</div></div>
</div>

<div class="callout note" markdown="1">
**Como eu conto "serviço":** um guest do Proxmox, LXC ou VM, que estava ligado em 13/11/2026. O NAS, o MacBook Air e a workstation de desktop não são guests e ficam fora da conta de 22. Guests parados também ficam fora.
</div>

## Resumo

- **Os três nós somam 16 threads e 72 GB de RAM instalada**, mas a distribuição é desigual de propósito: dois são Celeron N4020 com 4 GB cada e rodam 16 serviços leves, 24 horas por dia.
- **Toda a carga pesada está em um nó só** (Ryzen 5 5600G, 64 GB): duas GPUs para modelos locais, o roteador semântico, o monitoramento e as duas VMs dos clusters Kubernetes. **Esse nó nem sempre fica ligado** — é o compromisso central do laboratório, e ele aparece em quase todos os limites deste post.
- **O custo disso:** o Frigate (NVR com detecção de objetos) é um dos serviços que mais me importam e está desligado hoje, só porque mora nesse nó.
- **A GPU mais rápida não faz parte do laboratório.** A RX 7900 XTX de 24 GB é da minha workstation: ela entra no roteador de modelos quando está ligada e, no resto do tempo, é o servidor de streaming de jogos da casa.
- **Os dois "clusters" Kubernetes são VMs de nó único no mesmo host.** O multicluster do Istio é real; a escala não é. Isso vale para toda a série.
- **Energia já medida:** leitura instantânea de 172 W no rack inteiro, dos quais 75 W eram do Nó C, em 13/11 às 20h. É uma leitura pontual, não uma média; os números mensais e o custo saem no post 10.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/rack-frontal-alto.jpg' | relative_url }}" alt="O rack inteiro, de frente, do topo à base: régua de energia, painel de patch com cabos azuis, roteador, switches, o NAS de quatro baias, prateleiras com mini PCs e um notebook, e um chassi de 4U com chave." loading="lazy" style="max-width:420px;margin:0 auto">
<figcaption>O rack inteiro, de frente. De cima para baixo: energia, rede, NAS, prateleiras de mini PCs e notebook, e um chassi de 4U. Os rótulos de máquina foram borrados.</figcaption>
</figure>

## O que roda aqui

Estes são os serviços que eu uso de verdade, agrupados pelo que fazem. O Frigate está na tabela, apesar de estar desligado, porque é um dos mais importantes para mim.

| Camada | O que roda | Onde |
|---|---|---|
| Dados pessoais | Immich (fotos), Nextcloud (arquivos) e Syncthing (sincronização das minhas notas), com os dados no NAS | Nós A e B |
| Mídia | Jellyfin, e a automação da biblioteca com Radarr, Sonarr, Prowlarr, Bazarr, Seerr e qBittorrent | Mac e nós A e B |
| Vigilância | **Frigate**, um NVR com detecção de objetos e acesso à GPU do nó, para as câmeras de segurança | Nó C (hoje desligado) |
| IA local | llama.cpp servindo um modelo de 35 bilhões de parâmetros, vLLM Semantic Router (roteamento semântico com failover) e Qdrant (busca semântica sobre as minhas notas) | Nó C e workstation |
| Rede e acesso | Nginx Proxy Manager (proxy reverso), Pi-hole (DNS com bloqueio de anúncios), Vaultwarden (gerenciador de senhas) e Homepage (painel de entrada) | Nó A |
| Observabilidade | Prometheus, Grafana (9 dashboards), Jaeger, OpenTelemetry Collector e ntfy (avisos no celular) | Nós B e C |
| Plataforma | dois clusters k0s com Cilium, Istio multicluster, Flagger e cert-manager, mais um registro de contêineres | Nó C (clusters) e Nó A (registro) |
| Jogos | **Sunshine** (servidor de streaming de jogos) e, nos clientes, o Moonlight | Workstation, **não** nos nós do cluster |

Tudo isso roda localmente, em hardware meu, dentro da rede de casa: **nenhum desses serviços é publicado na internet**. O acesso de fora é por VPN. O Sunshine roda na workstation, não nos nós; os clientes Moonlight ficam espalhados pela casa — um deles é um mini PC com Celeron, igual aos nós, que dá boot direto num compositor Wayland leve e dedicado a isso. Ele é o assunto do post 12.

## Ambiente

| Item | Nó A | Nó B | Nó C |
|---|---|---|---|
| CPU | Celeron N4020, 2 núcleos | Celeron N4020, 2 núcleos | Ryzen 5 5600G, 6 núcleos / 12 threads |
| RAM instalada | 4 GB (1 × DDR4-2133) | 4 GB (1 × DDR4-2133) | 64 GB (4 × 16 GB DDR4-2400) |
| Disco | SSD 120 GB | SSD 480 GB | 2 × NVMe 1 TB + SSD 240 GB |
| GPU | nenhuma | nenhuma | 2 × Radeon RX 9060 XT, 16 GB cada |
| Hipervisor | Proxmox VE | Proxmox VE | Proxmox VE |
| Guests ligados | 9 LXC | 7 LXC | 4 LXC + 2 VMs |
| Disponibilidade | 24 × 7 | 24 × 7 | sob demanda |

O sistema enxerga menos do que a RAM instalada: 3,65 GiB nos nós A e B e 62,7 GiB no Nó C. A diferença é memória reservada pelo firmware e pelo kernel; no Nó C, o `dmesg` informa cerca de 131 MiB do firmware e 1,30 GiB reservados pelo kernel. É o tipo de detalhe que muda a conta quando se dimensiona um guest.

### Rede

A rede é gigabit, com um roteador MikroTik e VLANs que separam cinco redes: dispositivos móveis, servidores, administração, segurança e IoT. Os três nós e o NAS ficam na VLAN de servidores.

| Equipamento | Papel |
|---|---|
| MikroTik RB3011UiAS-RM | roteador e VLANs |
| Grandstream GWN7802P | switch gerenciável |
| Grandstream GWN7832 | switch L3 de agregação, 12 portas SFP+ de 10 Gb — **parado** |
| Ubiquiti UNVR (convertido) | NAS de 4 baias: RAID 1 de 2 HDs de 3 TB (pool lento) e RAID 1 de 2 SSDs de 960 GB (pool rápido), com Samba e NFS |
| MacBook Air (Apple M1, 8 GB) | servidor de mídia (Jellyfin) e minha workstation remota: VS Code, assistente de IA com skills e MCPs, e contas somente leitura no Kubernetes para a gerência; tela quebrada e sem vídeo pelas portas USB-C |
| Workstation de desktop | Ryzen 7 7800X3D, placa MSI B650M, RX 7900 XTX de 24 GB, NVMe de 1 TB, Ubuntu; roda o Sunshine e empresta a GPU ao roteador de modelos — fora do laboratório |

O switch de 10 Gb é o erro de compra mais visível do rack: os nós têm placas de 1 Gb, então **nada aqui aproveitaria o 10G**. Ele fica ali, ligado, sem um único nó conectado.

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/ambiente-pt.svg' | relative_url }}" alt="Diagrama do ambiente. A internet entra no roteador MikroTik RB3011, que alimenta dois switches Grandstream, um deles de 10 Gb parado. Do roteador saem cinco VLANs: dispositivos móveis, servidores, administração, segurança e IoT. Na VLAN de servidores ficam os nós A, B e C e o NAS Ubiquiti UNVR. Fora do laboratório estão a workstation com a RX 7900 XTX, o MacBook Air e o cliente Moonlight em Celeron." loading="lazy">
<figcaption>Hardware e rede do laboratório. O roteador abre cinco VLANs e os três nós e o NAS ficam na VLAN de servidores. O Nó C é o único que nem sempre fica ligado, e o switch de 10 Gb está parado. As caixas tracejadas ficam fora do laboratório.</figcaption>
</figure>

### Plataforma e IA local

Os dois clusters Kubernetes são k0s de nó único, um por VM, no Nó C: Cilium, Istio em multi-primary, Flagger, cert-manager, Prometheus, Jaeger e OpenTelemetry Collector. São eles que recebem os experimentos de canary e de service mesh da série.

Do lado dos modelos: llama.cpp sobre ROCm e o driver `amdgpu` do próprio kernel, com 128 mil tokens de contexto divididos entre as duas Radeon de 16 GB, mais um modelo pequeno para completar código e um de embeddings para a busca nas minhas notas. O roteador semântico escolhe o destino por intenção do pedido e cai para a GPU local quando a workstation está desligada. Armazenamento extra por NFS, do NAS.

### Por dentro

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/no-c-interior-16x9.jpg' | relative_url }}" alt="Interior do chassi do Nó C visto de cima: placa-mãe Gigabyte com Ryzen e cooler de fábrica, quatro módulos de memória, NVMe, fonte de 650 W e duas placas Radeon, uma Sapphire e uma PowerColor." loading="lazy">
<figcaption>O Nó C por dentro: Ryzen 5 5600G, quatro módulos de RAM, um NVMe e duas Radeon de 16 GB. Os cabos são exatamente como parecem.</figcaption>
</figure>

<figure class="fig">
<img src="{{ '/assets/img/homelab-apresentacao/workstation-16x9.jpg' | relative_url }}" alt="Gabinete branco da workstation com a placa XFX Radeon RX 7900 XTX visível pelo painel de vidro." loading="lazy">
<figcaption>A workstation convidada, com a RX 7900 XTX de 24 GB.</figcaption>
</figure>

## O que já deu errado (os cabelos brancos)

| Sintoma | Causa | Post |
|---|---|---|
| 208 falhas do ffmpeg em um dia | um compartilhamento de rede desmontou e os clientes repetiram o pedido em laço | 07 |
| 502 em sessões longas | o modelo de reserva tinha contexto real de 16 mil tokens, bem abaixo do que o roteador anunciava | 05 |
| GPU a 100% sem nenhum pedido | dois processos do llama.cpp na mesma placa | 03 |

## A série

Doze posts depois deste, dois por semana, sempre em pt-BR e en:

| Post | Tema |
|---|---|
| 01 | o detector por feature contra o Flagger |
| 02 | o laboratório que era dev e prod ao mesmo tempo |
| 03 | a GPU a 100% sem fazer nada |
| 04 | Vulkan contra HIP no llama.cpp |
| 05 | o que acontece quando a GPU principal cai |
| 06 | 128 mil tokens de contexto em 2 × 16 GB |
| 07 | as 208 falhas do compartilhamento de rede |
| 08 | o Proxmox em modo somente leitura |
| 09 | a limpeza do índice de busca |
| 10 | a energia do laboratório, medida na tomada |
| 11 | onde o roteador semântico errou |
| 12 | o Celeron que virou cliente de jogos |

Regras da série: todo número tem script e dado bruto; resultado negativo entra no resumo; nada de IPs, hostnames ou serviços pessoais.

## Limites

- A contagem de 22 serviços considera guests ligados em 13/11/2026, **com o Nó C ligado**. Os 16 serviços dos nós A e B ficam ligados 24 horas por dia; os 6 do Nó C só existem quando ele está. Pelo consumo na tomada, em outubro ele ficou ligado o equivalente a cerca de um terço do mês (estimativa, a 75 W).
- Os números de RAM e disco são dos hospedeiros, não dos guests.
- O cluster "b" não foi inspecionado nesta data.
- Sobre o Frigate, só descrevo o que está configurado: não medi nada dele (número de câmeras, retenção, carga) e ele está desligado.
- Não testei o isolamento entre as VLANs: descrevo a separação, não a verifiquei com testes.
- Não medi temperatura nem disponibilidade ao longo do tempo. O consumo foi medido só em tomada inteligente, sem carga de inferência, e a tomada do rack inclui o NAS, o Mac, o roteador e os switches.

## Referências

- Proxmox VE: <https://www.proxmox.com/en/products/proxmox-virtual-environment/overview>
- k0s: <https://k0sproject.io/>
- Istio multicluster: <https://istio.io/latest/docs/setup/install/multicluster/>
- llama.cpp: <https://github.com/ggml-org/llama.cpp>
- Frigate: <https://frigate.video/>
- Sunshine e Moonlight: <https://github.com/LizardByte/Sunshine> e <https://moonlight-stream.org/>

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
