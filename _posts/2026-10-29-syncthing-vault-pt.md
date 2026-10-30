---
title: "Syncthing entre sub-redes: recriar do zero, endereço fixo e réplica somente leitura"
lang: pt-BR
permalink: /pt/2026/10/29/syncthing-vault-sincronizacao/
description: "Notas de laboratório: sincronizei uma pasta de notas entre um PC e um servidor em sub-redes diferentes, recriando a instalação do Syncthing do zero, com endereço fixo e uma réplica somente leitura para o indexador."
---

*[Read in English]({{ "/en/2026/10/29/syncthing-vault-sync/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>29 de outubro de 2026 · <a href="#o-que-deu-errado">o que deu errado</a></span></p>

Minhas notas de infraestrutura ficam num PC. Queria a mesma pasta num servidor sempre ligado, para o indexador do RAG, e nos meus outros dispositivos. O PC e o servidor estão em sub-redes diferentes, então a descoberta automática não resolvia.

## Resumo

- **Recriei a instalação do zero** em vez de corrigir a antiga, que tinha pastas duplicadas e um dispositivo sem nome.
- **Mantive a identidade do dispositivo** do servidor, para os outros dispositivos continuarem reconhecendo-o.
- **O PC conecta por endereço fixo**, porque a descoberta não atravessa as sub-redes.
- **Sincronização testada nos dois sentidos** com a pasta de notas.
- **Uma réplica somente leitura** no servidor do RAG: nada que chega ali volta para a origem.
- **Pendente:** adicionar os celulares e o outro notebook.

## Ambiente

| Item | Valor |
|---|---|
| Hub | container Debian 13 no Proxmox, Syncthing 2.1.2, painel na LAN com login |
| Réplica | container do serviço RAG, Syncthing 1.19.2, pasta em modo *receive-only* |
| PC de trabalho | Syncthing na mesma pasta, conectado ao hub por endereço fixo |
| Pasta | notas de infraestrutura, com planos, relatórios e documentação |

Endereços, identificadores de dispositivo e senhas ficaram fora deste texto.

## Desenho

<pre class="mermaid">
flowchart LR
  P["PC de trabalho"] <-->|"envio e recebimento"| H["hub (container)"]
  H -->|"envio"| R["réplica receive-only (RAG)"]
  M["outros dispositivos"] <-->|"pendente"| H
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

## Por que recriar

A configuração antiga tinha pastas duplicadas e um dispositivo sem nome. Corrigir cada peça era mais trabalhoso que refazer. Recriei a instalação e mantive a identidade do dispositivo do servidor, para não exigir nova aceitação em todos os outros lugares.

## Endereço fixo

A descoberta automática depende de estar na mesma rede local, e o PC e o servidor não estão. Configurei o PC para conectar ao hub pelo endereço fixo do servidor. Isso funciona enquanto o endereço for fixo.

## Réplica somente leitura

O indexador do RAG lê de uma réplica em modo *receive-only*. Assim, nada que o indexador ou o servidor escreva na pasta volta para o PC. O indexador só lê as notas.

## Teste

Criei e alterei arquivos nos dois lados e confirmei que as mudanças chegaram ao outro. Não medi o tempo de propagação; a conclusão é só de que a sincronização funciona nos dois sentidos.

## O que deu errado

| Sintoma | Causa | Correção |
|---|---|---|
| Pastas duplicadas na instalação antiga | configuração acumulada | recriação do zero |
| Dispositivo sem nome | configuração antiga | recriado com nome |
| PC não encontrava o servidor | sub-redes diferentes | endereço fixo |

## Limites

- Só o PC e o servidor estão conectados. Os celulares e o outro notebook ainda não.
- Não medi tempo de propagação nem o comportamento com arquivos grandes.
- A conexão depende de endereço fixo; uma mudança de rede exige ajuste manual.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
