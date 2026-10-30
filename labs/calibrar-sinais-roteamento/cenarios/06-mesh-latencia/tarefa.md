# Cenário 6: Latência após service mesh

## Instrução para o modelo

Você é um engenheiro de SRE. Após injetar sidecars de service mesh em um serviço de produção, a latência p99tripou. Use as métricas sintéticas abaixo para montar uma árvore de causa raiz e indicar como medir cada hipótese.

**Regras:**
- Não sugira remover o service mesh sem antes medir.
- Liste hipóteses ordenadas por probabilidade.
- Para cada hipótese, indique o comando/métrica para validar.

## Artefato: métricas sintéticas

### Antes da injeção (24h média)

| Métrica | p50 | p95 | p99 |
|---------|-----|-----|-----|
| Latência de requisição (ms) | 12 | 45 | 89 |
| Taxa de erro (%) | 0.01 | 0.02 | 0.05 |
| Throughput (req/s) | 1200 | 1800 | - |
| CPU por pod (mil cores) | 150 | 300 | - |
| Memória por pod (MiB) | 256 | 320 | - |

### Depois da injeção (últimas 2h)

| Métrica | p50 | p95 | p99 |
|---------|-----|-----|-----|
| Latência de requisição (ms) | 34 | 180 | 890 |
| Taxa de erro (%) | 0.05 | 0.3 | 1.2 |
| Throughput (req/s) | 950 | 1200 | - |
| CPU por pod (mil cores) | 280 | 450 | - |
| Memória por pod (MiB) | 410 | 520 | - |

### Métricas do sidecar (últimas 2h)

| Métrica | Valor |
|---------|-------|
| Tempo de handshake TLS (ms) | 15 (p50), 120 (p99) |
| Conexões ao upstream que caem (count) | 47 |
| Tempo de resolução DNS (ms) | 2 (p50), 85 (p99) |
| Tempo de fila do proxy (ms) | 0.5 (p50), 200 (p99) |
| Circuit breaker trips (count) | 3 |
| Envoy worker CPU (mil cores) | 80 (p50), 250 (p99) |
