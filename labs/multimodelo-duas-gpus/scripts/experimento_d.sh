#!/bin/sh
# O contorno GPU_MAX_HW_QUEUES=1 custa desempenho? Para cada configuracao (sem a variavel, =1),
# reinicia os dois servidores, faz 3 pedidos de aquecimento, mede 30 pedidos de embedding
# (texto de ~1.000 caracteres, o tamanho de um trecho do RAG) e 10 de completacao (64 tokens),
# e depois amostra a GPU 1 por 60 s ja ociosa.
# Variaveis (caminhos DENTRO do container): ENV_CHAVE (arquivo que define LLAMA_API_KEY).
# Uso: CT=<id> sh experimento_d.sh <pasta_saida>
# Saidas: latencias.csv (config,tipo,i,segundos,http) e ocioso.csv (config,t,busy1,w1)
set -eu
OUT=$1; CT=${CT:?defina CT}
G1=/sys/class/drm/card1/device; H1=$(echo $G1/hwmon/hwmon*)
mkdir -p "$OUT"; echo "config,tipo,i,segundos,http" > "$OUT/latencias.csv"; echo "config,t,busy1,w1" > "$OUT/ocioso.csv"
ct() { pct exec "$CT" -- env ENV_CHAVE="${ENV_CHAVE:-}" sh -c "$1"; }
pronto() { for _ in $(seq 1 90); do c=$(ct "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:$1/health" || true); [ "$c" = 200 ] && return 0; sleep 1; done; return 1; }
TXT=$(python3 -c "print(('O roteador encaminha pedidos para o modelo local e usa o fallback quando a placa principal cai. ' * 11)[:1000])")
medir() { # $1 config
  ct ". \${ENV_CHAVE:?}; for i in 1 2 3; do curl -s -o /dev/null -H \"Authorization: Bearer \$LLAMA_API_KEY\" -H 'Content-Type: application/json' -d '{\"input\":\"aquecimento\"}' http://127.0.0.1:8084/v1/embeddings; done"
  ct ". \${ENV_CHAVE:?}; for i in \$(seq 1 30); do curl -s -o /dev/null -w \"$1,embedding,\$i,%{time_total},%{http_code}\n\" -H \"Authorization: Bearer \$LLAMA_API_KEY\" -H 'Content-Type: application/json' -d '{\"input\":\"$TXT\"}' http://127.0.0.1:8084/v1/embeddings; done" >> "$OUT/latencias.csv"
  ct ". \${ENV_CHAVE:?}; for i in \$(seq 1 10); do curl -s -o /dev/null -w \"$1,completacao,\$i,%{time_total},%{http_code}\n\" -H \"Authorization: Bearer \$LLAMA_API_KEY\" -H 'Content-Type: application/json' -d '{\"input_prefix\":\"def listar_logs(pasta):\",\"input_suffix\":\"\",\"n_predict\":64,\"temperature\":0}' http://127.0.0.1:8083/infill; done" >> "$OUT/latencias.csv"
  sleep 10; i=0; while [ $i -lt 60 ]; do echo "$1,$(date +%s),$(cat $G1/gpu_busy_percent),$(( $(cat $H1/power1_average) / 1000000 ))" >> "$OUT/ocioso.csv"; i=$((i+1)); sleep 1; done; }
aplicar() { for s in llama-fim llama-embed; do
    if [ -n "$1" ]; then ct "mkdir -p /etc/systemd/system/$s.service.d && printf '[Service]\nEnvironment=GPU_MAX_HW_QUEUES=$1\n' > /etc/systemd/system/$s.service.d/zz-teste-hwq.conf"
    else ct "rm -f /etc/systemd/system/$s.service.d/zz-teste-hwq.conf"; fi; done
  ct 'systemctl daemon-reload && systemctl restart llama-fim llama-embed'; pronto 8083; pronto 8084; }
for rodada in 1 2; do
  aplicar ""; medir "padrao"
  aplicar 1; medir "hwq1"
done
aplicar ""
