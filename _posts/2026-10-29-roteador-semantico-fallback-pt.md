---
title: "Roteador semântico local com fallback"
lang: pt-BR
permalink: /pt/2026/10/29/roteador-semantico-fallback/
description: "Como configurei o llama-router no CT 301 para rotear entre a XTX e um modelo local de 14B no fallback."
---

*[Read in English]({{ "/en/2026/10/29/roteador-semantico-fallback/" | relative_url }})*

---

## O setup

Tenho dois recursos de inferência:

1. **XTX** (máquina remota, `192.168.88.248:8080`): Qwen3.6-35B-A3B-Q4_K_M — o modelo forte para raciocínio.
2. **CT 300** (Proxmox, GPU 0): qwen3-14b-Q4_K_M — o fallback local, sempre carregado.

O **llama-router** roda no CT 301 (10.0.0.30:8081) como proxy. Ele recebe um prompt, calcula o embedding e decide para qual backend enviar.

## config.yaml

```yaml
# Simplificado
routing:
  model: qwen3-embedding-0.6b
  endpoint: http://10.0.0.29:8084

routes:
  - name: xtx
    url: http://192.168.88.248:8080/v1/chat/completions
    priority: 1
  - name: ct300-local
    url: http://10.0.0.29:8080/v1/chat/completions
    priority: 2
```

A lógica é simples: se a XTX responde, usa ela. Se cair, fallback para o local. O embedding serve para calibrar a rota com base no dominio do prompt.

## Latência do fallback

Quando a XTX cai, o fallback carrega o modelo sob demanda:

```
Tempo total: ~19 segundos
- Handshake HTTP: <100ms
- Carregamento do modelo: ~18s
- Primeiro token: ~1s
```

A trade-off: manter o qwen3-14b sempre em memória gasta ~40W contínuos, mas elimina os 19s de loading. Decidi manter sempre carregado.

## O que quebrou

Durante o reboot do CT 301, o roteador ficou fora por alguns minutos. Os containers do llama-router (8 no total) não sobem automaticamente com o container host. Precisei:

1. Criar um timer systemd para cada container.
2. Verificar se o embedding (CT300:8084) está online antes de iniciar o roteador.

Agora sobe sozinho — mas o tempo de warm-up da XTX ainda é um ponto cego. Se a XTX "dormir" (timeout de inatividade), o primeiro pedido tem TTFT alto (~35-60s no benchmark).

## Decisões

| Decisão | Alternativa | Por que escolhi |
|---------|-------------|-----------------|
| Fallback quente (sempre carregado) | Cold start | 19s > 40W. O usuário espera resposta em segundos. |
| Embedding como sinal | Regras de keywords | Embedding generaliza melhor entre dominios. |
| Threshold dinâmico | Threshold fixo | Embeddings variam por lote (0.19 de swing num teste). |

## Próximos passos

- Monitorar a distribuição de distances ao vivo.
- Adicionar regra de palavra-chave para dominios críticos (segurança, injeção).
- Testar o fallback com a XTX derrubada em cenários reais.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
