#!/bin/sh
# Experimento: qual processo mantem a GPU 1 ocupada sem pedidos?
# Variaveis (caminhos DENTRO do container): ENV_CHAVE (arquivo que define LLAMA_API_KEY), LLAMA_BIN, MODELO_EMBED.
# Os nomes de servico (llama-fim, llama-embed) e as portas 8083/8084 sao os do laboratorio; ajuste aos seus.
# Roda no hospedeiro Proxmox. Amostra a 1 Hz uso (%), potencia (W) e clock da GPU 0 e da GPU 1,
# enquanto liga e desliga os servidores da GPU 1 dentro do container.
# Saidas: amostras.csv (t,fase,busy0,busy1,w0,w1,sclk1_mhz) e eventos.csv (t,fase,descricao)
# Uso: CT=<id do container> FASE_S=90 sh experimento_gpu1.sh <pasta_saida>
set -eu
OUT=$1; CT=${CT:?defina CT}; FASE_S=${FASE_S:-90}
G0=/sys/class/drm/card0/device; G1=/sys/class/drm/card1/device
H0=$(echo $G0/hwmon/hwmon*); H1=$(echo $G1/hwmon/hwmon*)
mkdir -p "$OUT"; echo "t,fase,busy0,busy1,w0,w1,sclk1_mhz" > "$OUT/amostras.csv"; echo "t,fase,descricao" > "$OUT/eventos.csv"
amostrar() { # $1 = fase, $2 = segundos
  i=0; while [ $i -lt "$2" ]; do
    s=$(awk '/\*/{gsub("Mhz","",$2); print $2}' $G1/pp_dpm_sclk | head -1)
    echo "$(date +%s),$1,$(cat $G0/gpu_busy_percent),$(cat $G1/gpu_busy_percent),$(( $(cat $H0/power1_average) / 1000000 )),$(( $(cat $H1/power1_average) / 1000000 )),$s" >> "$OUT/amostras.csv"
    i=$((i+1)); sleep 1
  done; }
evento() { echo "$(date +%s),$1,$2" >> "$OUT/eventos.csv"; }
ct() { pct exec "$CT" -- env LLAMA_BIN="${LLAMA_BIN:-}" MODELO_EMBED="${MODELO_EMBED:-}" ENV_CHAVE="${ENV_CHAVE:-}" sh -c "$1"; }
pedido_embed() { ct '. ${ENV_CHAVE:?arquivo com LLAMA_API_KEY}; curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $LLAMA_API_KEY" -H "Content-Type: application/json" -d "{\"input\":\"teste de embedding\"}" http://127.0.0.1:8084/v1/embeddings'; }
pedido_fim() { ct '. ${ENV_CHAVE:?arquivo com LLAMA_API_KEY}; curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $LLAMA_API_KEY" -H "Content-Type: application/json" -d "{\"input_prefix\":\"def soma(a, b):\\n    \",\"input_suffix\":\"\\n\",\"n_predict\":16}" http://127.0.0.1:8083/infill'; }
esperar_pronto() { for _ in $(seq 1 60); do c=$(ct "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:$1/health" || true); [ "$c" = 200 ] && return 0; sleep 1; done; return 1; }

evento 1 "ambos ligados, estado encontrado"; amostrar 1 "$FASE_S"
ct 'systemctl stop llama-fim'; evento 2 "completacao parada; so embedding"; amostrar 2 "$FASE_S"
ct 'systemctl start llama-fim'; esperar_pronto 8083; ct 'systemctl stop llama-embed'; evento 3 "embedding parado; so completacao (recem-iniciada)"; amostrar 3 "$FASE_S"
ct 'systemctl stop llama-fim'; evento 4 "ambos parados"; amostrar 4 "$FASE_S"
ct 'systemctl start llama-embed llama-fim'; esperar_pronto 8084; esperar_pronto 8083; evento 5 "ambos recem-iniciados, sem pedidos"; amostrar 5 "$FASE_S"
r=$(pedido_embed); evento 6 "1 pedido de embedding (HTTP $r)"; amostrar 6 "$FASE_S"
r=$(pedido_fim); evento 7 "1 pedido de completacao (HTTP $r)"; amostrar 7 "$FASE_S"
evento 8 "fim"
