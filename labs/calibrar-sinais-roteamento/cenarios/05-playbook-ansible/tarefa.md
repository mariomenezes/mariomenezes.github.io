# Cenário 5: Playbook Ansible - configuração de serviço

## Instrução para o modelo

Você é um engenheiro de automação. Escreva um playbook Ansible que configure o serviço `nginx` em um grupo de servidores, incluindo:

1. Instalar o nginx
2. Copiar um arquivo de configuração personalizado (template Jinja2)
3. Habilitar e iniciar o serviço
4. Verificar se o serviço está rodando antes de marcar como "changed"
5. Reiniciar o serviço quando a configuração mudar (handler)

**Regras:**
- O playbook deve ser idempotente.
- Use `--check` mode seguro.
- Inclua `ansible-lint` validação.

## Verificação objetiva

Após a resposta:
- Execute mentalmente `ansible-lint` e verifique se há warnings de:
  - `no-changed-when` (falta de `changed_when`)
  - `command-instead-of-module` (uso de `command` no lugar de `service`)
  - `var-naming` (nomes de variáveis)
- Verificar se há `handler` para reinício.
- Verificar se há `--check` no exemplo de execução.
