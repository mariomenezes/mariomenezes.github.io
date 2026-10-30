# Roteador com fallback: material para reproduzir

Acompanha o post "Roteador de modelos com fallback no homelab" (pt-BR e en).

- `scripts/medir_roteador.py`: 10 pedidos curtos pelo roteador, com caminho de rota (`X-Vsr-Response-Path`) e modelo que respondeu.
- `data/rota_medida.json`: saída das duas medições (fonte principal fora do ar e no ar).

Como rodar: `ROUTER_URL=http://<ROTEADOR>:<PORTA>/v1/chat/completions SAIDA=rota_medida.json python3 scripts/medir_roteador.py`.

Os dados são de um dia em que a fonte principal caiu sem ação minha. Para repetir o caso de queda, é preciso derrubar a fonte principal, o que não está descrito aqui.
