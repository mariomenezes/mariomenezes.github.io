---
title: "Dois clusters, a mesma faixa de IP e um Service que esperava 10 segundos"
lang: pt-BR
permalink: /pt/2026/11/08/istio-multicluster-endpoint-fantasma/
description: "Num Istio multicluster com faixas de IP de pods sobrepostas, um Service novo herdou um endpoint que só existe no outro cluster. Um serviço de 2 ms passou a ter p95 de 9 s. Como achei, a correção e a checagem que foi para o pré-voo."
resumo: "Um endpoint que só existe no outro cluster fez um serviço de 2 ms responder com p95 de 9 a 25 s. O Kubernetes mostrava um endpoint só; o Envoy tinha dois."
image: /assets/img/istio-multicluster-endpoint-fantasma/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/08/istio-multicluster-endpoint-fantasma/" | relative_url }})*

<p class="status"><span class="pill">Notas de laboratório</span> <span>8 de novembro de 2026</span></p>

No primeiro piloto do [teste com o Flagger]({{ "/pt/2026/11/08/flagger-real-detector-por-feature/" | relative_url }}), o `dashboard`, que responde em 1 a 2 ms, passou a ter p95 de 9 a 25 segundos por minuto, antes de qualquer falha injetada. O app estava bem, o pod estava bem, e o Kubernetes mostrava um único endpoint no Service. O sidecar Envoy, porém, tinha dois: o pod local e um IP que só existia no outro cluster.

A causa é conhecida: os dois clusters estão num Istio multicluster e usam a mesma faixa de IP para pods. A documentação do Istio pede faixas sem sobreposição nesse caso [1]. Eu já tinha esbarrado nisso em outubro, mas a mitigação cobria só o serviço antigo, e o namespace novo do Flagger ficou de fora.

<div class="tiles">
<div class="tile"><div class="tile-value">9,6 s</div><div class="tile-label">p95 mediano do dashboard por minuto, com o caminho quebrado (antes da falha)</div></div>
<div class="tile"><div class="tile-value">10 s</div><div class="tile-label">o tempo que parte das requisições esperava, mesmo sem carga</div></div>
<div class="tile"><div class="tile-value">2 ms</div><div class="tile-label">a mesma requisição depois do <code>clusterLocal</code></div></div>
</div>

## Resumo

- **Sintoma:** p95 do `dashboard` de 9 a 25 s por minuto (mediana 9,6 s), contra 1 a 5 ms no piloto corrigido.
- **Isolamento:** dentro do contêiner, 0 a 8 ms; direto no IP do pod, 1 a 57 ms; pelo Service do lab antigo, 2 a 24 ms; pelo Service novo, parte das requisições levava cerca de 10 s, **mesmo sem carga nenhuma**.
- **Causa:** o Envoy do cliente tinha dois endpoints para o Service: o pod local e um IP de pod do outro cluster, inalcançável daqui, mas marcado como saudável. As requisições balanceadas para ele esperavam o timeout de conexão de 10 s.
- **Correção:** `clusterLocal` para `*.flagger-lab.svc.cluster.local` no MeshConfig dos dois clusters (e no módulo de infraestrutura como código). A latência voltou a 2 ms.
- **Prevenção:** o pré-voo do runner agora faz 10 requisições ao `dashboard` pelo Service e reprova se alguma passar de 1 s ou der erro.
- **Correção certa, ainda não feita:** faixas de IP de pods distintas nos dois clusters.

## O ambiente

Dois clusters k0s v1.36.4 num mesmo host Proxmox, um nó cada, Istio 1.31.1 em multi-primary (cada istiod descobre os serviços do outro cluster). As duas instalações usam a faixa padrão de pods, a mesma nos dois lados. O laboratório antigo (`app-service`) tinha `clusterLocal` desde outubro; o namespace do Flagger (`flagger-lab`) foi criado agora.

## A causa, em um desenho

<pre class="mermaid">
flowchart LR
  C["cliente no cluster A"] --> E["Envoy do cliente"]
  E -->|"endpoint 1: IP do pod local"| A["app no cluster A (responde em 2 ms)"]
  E -->|"endpoint 2: IP de pod do cluster B"| X["mesmo IP não existe no cluster A"]
  X -. "conexão pendura até o timeout de 10 s" .-> E
  I["istiod do cluster A"] -->|"descobre os pods do cluster B (multi-primary)"| E
</pre>

Em multi-primary, cada istiod lê os Services e endpoints dos dois clusters e entrega ao Envoy todos os endpoints de um host com o mesmo nome. Com faixas de IP diferentes e roteamento entre os clusters, isso é o que faz o balanceamento entre clusters funcionar. Com a mesma faixa e sem roteamento, o IP do pod remoto aponta para lugar nenhum daqui. Como não havia detecção de outliers configurada, o Envoy continuava considerando esse endpoint saudável.

## Como achei

<figure class="fig">
<img src="{{ "/assets/img/istio-multicluster-endpoint-fantasma/p95-caminho-pt.svg" | relative_url }}" alt="p95 do dashboard por minuto, em escala log: no piloto com o caminho quebrado, entre 9 e 25 segundos (mediana 9.589 ms); no piloto corrigido, entre 0,9 e 4,8 ms (mediana 4,5 ms)." loading="lazy">
<figcaption>p95 do <code>dashboard</code> por minuto, só nos minutos antes de ligar a falha. A diferença é de três a quatro ordens de grandeza, sem nenhuma falha injetada.</figcaption>
</figure>

1. **Descartar o app.** Dentro do contêiner, `curl` local: 0 a 8 ms. Uso de CPU do contêiner do app: 3 mCPU. O app não era o problema.
2. **Descartar a rede do pod.** Do gerador direto no IP do pod: 1 a 57 ms. O caminho de rede até o pod estava bem.
3. **Descartar a carga.** Desliguei o gerador e testei de um pod novo, sem carga: pelo Service do Flagger, duas de oito requisições levaram 10.025 ms. Pelo Service do lab antigo, a partir do mesmo pod, nenhuma passou de 24 ms.
4. **Comparar o que o Kubernetes e o Envoy veem.** `kubectl get endpoints` mostrava um IP. As estatísticas do Envoy do pod de teste mostravam dois: o local, com 8 requisições bem-sucedidas, e outro, com 2 falhas de conexão, 0 sucessos e `health_flags: healthy`.
5. **Achar a origem do IP extra.** O endpoint de depuração do istiod (`/debug/endpointShardz`) mostrou o IP extra com o rótulo de hostname do nó do outro cluster.

<figure class="fig">
<img src="{{ "/assets/img/istio-multicluster-endpoint-fantasma/requisicoes-pt.svg" | relative_url }}" alt="Tempo de requisições individuais em escala log por caminho: dentro do contêiner e direto no IP do pod, todas abaixo de 60 ms; pelo Service do lab antigo, abaixo de 25 ms; pelo Service do Flagger sem carga, seis rápidas e duas em 10 segundos; com carga, a maioria entre 1 e 10 segundos; depois da correção, 2 ms, com a primeira requisição de cada série em cerca de 110 ms." loading="lazy">
<figcaption>Cada ponto é uma requisição. Só o caminho pelo Service do Flagger ficava lento (vermelho), e sem carga os lentos ficavam encostados no timeout de conexão de 10 s. A primeira requisição de cada série, depois da correção, inclui o estabelecimento da conexão.</figcaption>
</figure>

## A correção

```yaml
# MeshConfig (ConfigMap istio no istio-system), nos dois clusters
serviceSettings:
- hosts:
  - app-service.lab-apps.svc.cluster.local
  - "*.flagger-lab.svc.cluster.local"
  settings:
    clusterLocal: true
```

O `clusterLocal` faz o istiod entregar ao Envoy só os endpoints do próprio cluster para esses hosts [2]. Depois de o istiod propagar a mudança (menos de um minuto), o Envoy do pod de teste passou a ter um endpoint só, e as requisições voltaram a 2 ms nos dois clusters. A mesma linha entrou no módulo de infraestrutura como código, para não se perder numa reinstalação.

| Caminho | Antes | Depois |
|---|---|---|
| Pod de teste, sem carga, Service do Flagger | 2 a 10.025 ms | 2 ms (112 ms na 1ª requisição) |
| Gerador, Service `app-fl`, cluster a | 2 a 10.000 ms, com um 504 | 2 ms (12 ms na 1ª) |
| p95 do `dashboard` por minuto | 9,2 a 25 s | 0,9 a 4,8 ms |

## O que vai para o pré-voo

O runner agora mede o caminho antes de começar: 10 requisições ao `dashboard` pelo Service, do pod do gerador. Reprova se alguma passar de 1 s ou der erro, e diz isso na mensagem. Teria pego este caso em segundos, em vez de um piloto inteiro.

## Limites

- **`clusterLocal` é mitigação, não correção.** Desliga o balanceamento entre clusters para esses hosts. A correção é usar faixas de IP de pods e de Services distintas em cada cluster, como pede a documentação para malhas de rede única.
- **Detecção de outliers no DestinationRule** teria reduzido o estrago, ejetando o endpoint depois de algumas falhas. Não testei.
- **Não sei por que algumas requisições lentas terminavam em 200 e outras em 504.** O timeout de conexão e o da rota são ambos de 10 s, e há retry. Não investiguei a combinação.

## Como reproduzir

Em [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. Os p95 por minuto: `data/pilot-flagger-caminho-quebrado.tar.gz` e `data/pilot-flagger-caminho-ok.tar.gz`; `python3 scripts/extrair.py` gera a seção `path` de `data/figuras.json`.
2. As requisições individuais e as estatísticas do Envoy: `data/caminho-medicoes.json` (copiadas da saída do terminal durante o diagnóstico).
3. No seu cluster: `kubectl exec <pod> -c istio-proxy -- pilot-agent request GET clusters | grep <host>` lista os endpoints que o Envoy realmente usa. Critério: o número de endpoints deve bater com o de `kubectl get endpointslices`.

## Referências

1. Istio, "Before you begin" (instalação multicluster). <https://istio.io/latest/docs/setup/install/multicluster/before-you-begin/>. Sustenta: em malhas de rede única, as faixas de pods e Services precisam ser distintas.
2. Istio, "Multicluster Traffic Management". <https://istio.io/latest/docs/ops/configuration/traffic-management/multicluster/>. Sustenta: `clusterLocal` via `MeshConfig.serviceSettings`, por host ou curinga.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
