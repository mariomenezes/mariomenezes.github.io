#!/bin/sh
# Teste de contorno: GPU_MAX_HW_QUEUES nos dois servidores da GPU 1 (drop-in temporario do systemd).
# Variaveis (caminhos DENTRO do container): ENV_CHAVE (arquivo que define LLAMA_API_KEY), LLAMA_BIN, MODELO_EMBED.
# Os nomes de servico (llama-fim, llama-embed) e as portas 8083/8084 sao os do laboratorio; ajuste aos seus.
# Fases: 1 sem a variavel (controle); 2 GPU_MAX_HW_QUEUES=1; 3 GPU_MAX_HW_QUEUES=2; 4 sem a variavel de novo.
# Em cada fase, os dois servidores sao reiniciados e recebem 1 pedido antes da amostragem.
# Uso: CT=<id> FASE_S=60 sh experimento_gpu1_c.sh <pasta_saida>
set -eu
OUT=$1; CT=${CT:?defina CT}; FASE_S=${FASE_S:-60}
G1=/sys/class/drm/card1/device; H1=$(echo $G1/hwmon/hwmon*)
mkdir -p "$OUT"; echo "t,fase,busy1,w1" > "$OUT/amostras.csv"; echo "t,fase,descricao" > "$OUT/eventos.csv"
amostrar() { i=0; while [ $i -lt "$2" ]; do
    echo "$(date +%s),$1,$(cat $G1/gpu_busy_percent),$(( $(cat $H1/power1_average) / 1000000 ))" >> "$OUT/amostras.csv"
    i=$((i+1)); sleep 1; done; }
evento() { echo "$(date +%s),$1,$2" >> "$OUT/eventos.csv"; }
ct() { pct exec "$CT" -- env LLAMA_BIN="${LLAMA_BIN:-}" MODELO_EMBED="${MODELO_EMBED:-}" ENV_CHAVE="${ENV_CHAVE:-}" sh -c "$1"; }
pronto() { for _ in $(seq 1 90); do c=$(ct "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:$1/health" || true); [ "$c" = 200 ] && return 0; sleep 1; done; return 1; }
pedidos() { ct '. ${ENV_CHAVE:?arquivo com LLAMA_API_KEY}; curl -s -o /dev/null -H "Authorization: Bearer $LLAMA_API_KEY" -H "Content-Type: application/json" -d "{\"input\":\"teste\"}" http://127.0.0.1:8084/v1/embeddings; curl -s -o /dev/null -H "Authorization: Bearer $LLAMA_API_KEY" -H "Content-Type: application/json" -d "{\"input_prefix\":\"def f():\",\"input_suffix\":\"\",\"n_predict\":8}" http://127.0.0.1:8083/infill'; }
aplicar() { # $1 = valor ou vazio
  for s in llama-fim llama-embed; do
    if [ -n "$1" ]; then ct "mkdir -p /etc/systemd/system/$s.service.d && printf '[Service]\nEnvironment=GPU_MAX_HW_QUEUES=$1\n' > /etc/systemd/system/$s.service.d/zz-teste-hwq.conf"
    else ct "rm -f /etc/systemd/system/$s.service.d/zz-teste-hwq.conf"; fi
  done
  ct 'systemctl daemon-reload && systemctl restart llama-fim llama-embed'; pronto 8083; pronto 8084; pedidos; sleep 5; }

aplicar ""; evento 1 "controle, sem GPU_MAX_HW_QUEUES"; amostrar 1 "$FASE_S"
aplicar 1; evento 2 "GPU_MAX_HW_QUEUES=1"; amostrar 2 "$FASE_S"
aplicar 2; evento 3 "GPU_MAX_HW_QUEUES=2"; amostrar 3 "$FASE_S"
aplicar ""; evento 4 "sem a variavel de novo"; amostrar 4 "$FASE_S"
evento 5 "fim"
