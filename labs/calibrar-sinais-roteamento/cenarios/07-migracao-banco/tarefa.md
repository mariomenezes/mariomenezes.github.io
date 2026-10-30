# Cenário 7: Migração de banco com downtime máximo

## Instrução para o modelo

Você é um engenheiro de infraestrutura planejando a migração de um banco de dados PostgreSQL de 2 TB. A janela de downtime é de **5 minutos**.

## Contexto

- **Fonte:** PostgreSQL 14 em VM com 64 GB RAM, 1 TB SSD, 8 vCPUs
- **Destino:** PostgreSQL 16 gerenciado (RDS-like), 64 GB RAM, 2 TB SSD, 16 vCPUs
- **Tamanho:** 2 TB de dados, 15 GB/s de throughput de escrita máximo, 30 GB/s de leitura
- **SLA:** downtime máximo de 5 minutos
- **Horário da janela:** 03:00–05:00 UTC (menor tráfego)
- **Requisitos de rollback:** em caso de falha, voltar ao original em ≤ 3 minutos
- **Dados sensíveis:** os dados precisam permanecer criptografados em trânsito

## Instrução

Descreva o plano de migração detalhado, incluindo:

1. Estratégias possíveis (comparação de trade-offs)
2. O plano escolhido passo a passo
3. Como validar cada etapa
4. Plano de rollback
5. Riscos e mitigadores

**Regras:**
- Não sugira soluções que ignorem a janela de 5 minutos.
- Considere consistência dos dados.
- Mencione testes de dry-run.

## Verificação objetiva

- O plano respeita a janela de 5 minutos?
- Há menção de backup prévio?
- Há plano de rollback com tempo estimado?
- Os dados sensíveis são tratados (criptografia)?
