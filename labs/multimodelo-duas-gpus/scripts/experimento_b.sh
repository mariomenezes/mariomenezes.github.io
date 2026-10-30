#!/bin/sh
# Repeticao com a ordem invertida + controle na GPU 0.
# Variaveis (caminhos DENTRO do container): ENV_CHAVE (arquivo que define LLAMA_API_KEY), LLAMA_BIN, MODELO_EMBED.
# Os nomes de servico (llama-fim, llama-embed) e as portas 8083/8084 sao os do laboratorio; ajuste aos seus.
# Fases: 1 ambos ligados; 2 so completacao (embedding parado); 3 so embedding (completacao parada);
# 4 ambos ligados de novo; 5 GPU 0: um segundo processo HIP (embedding temporario) ao lado do fallback;
# 6 GPU 0 sem o processo temporario.
# Uso: CT=<id> FASE_S=60 sh experimento_gpu1_b.sh <pasta_saida>
set -eu
OUT=$1; CT=${CT:?defina CT}; FASE_S=${FASE_S:-60}
G0=/sys/class/drm/card0/device; G1=/sys/class/drm/card1/device
H0=$(echo $G0/hwmon/hwmon*); H1=$(echo $G1/hwmon/hwmon*)
mkdir -p "$OUT"; echo "t,fase,busy0,busy1,w0,w1,sclk1_mhz" > "$OUT/amostras.csv"; echo "t,fase,descricao" > "$OUT/eventos.csv"
amostrar() { i=0; while [ $i -lt "$2" ]; do
    s=$(awk '/\*/{gsub("Mhz","",$2); print $2}' $G1/pp_dpm_sclk | head -1)
    echo "$(date +%s),$1,$(cat $G0/gpu_busy_percent),$(cat $G1/gpu_busy_percent),$(( $(cat $H0/power1_average) / 1000000 )),$(( $(cat $H1/power1_average) / 1000000 )),$s" >> "$OUT/amostras.csv"
    i=$((i+1)); sleep 1; done; }
evento() { echo "$(date +%s),$1,$2" >> "$OUT/eventos.csv"; }
ct() { pct exec "$CT" -- env LLAMA_BIN="${LLAMA_BIN:-}" MODELO_EMBED="${MODELO_EMBED:-}" ENV_CHAVE="${ENV_CHAVE:-}" sh -c "$1"; }
pronto() { for _ in $(seq 1 90); do c=$(ct "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:$1/health" || true); [ "$c" = 200 ] && return 0; sleep 1; done; return 1; }

evento 1 "ambos ligados"; amostrar 1 "$FASE_S"
ct 'systemctl stop llama-embed'; evento 2 "so completacao"; amostrar 2 "$FASE_S"
ct 'systemctl start llama-embed'; pronto 8084; ct 'systemctl stop llama-fim'; evento 3 "so embedding"; amostrar 3 "$FASE_S"
ct 'systemctl start llama-fim'; pronto 8083; evento 4 "ambos ligados de novo"; amostrar 4 "$FASE_S"
ct 'systemd-run --unit=teste-gpu0 -p Environment=ROCR_VISIBLE_DEVICES=0 ${LLAMA_BIN:?defina LLAMA_BIN} -m ${MODELO_EMBED:?defina MODELO_EMBED} -ngl 99 -c 4096 --embeddings --host 127.0.0.1 --port 8099 -t 2'
pronto 8099; evento 5 "GPU 0: segundo processo HIP ao lado do fallback"; amostrar 5 "$FASE_S"
ct 'systemctl stop teste-gpu0'; evento 6 "GPU 0 sem o processo temporario"; amostrar 6 "$FASE_S"
evento 7 "fim"
