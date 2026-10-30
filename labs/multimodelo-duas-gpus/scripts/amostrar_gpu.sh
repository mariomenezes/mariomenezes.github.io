#!/bin/sh
# Amostra o uso e a VRAM de duas GPUs AMD a cada 5 s, durante 5 minutos (60 leituras).
# Rodar no hospedeiro. Saida: CSV com timestamp, busy% GPU0, busy% GPU1, VRAM GPU0 (bytes), VRAM GPU1 (bytes).
# Uso: sh amostrar_gpu.sh > gpu_amostra.csv
for i in $(seq 1 60); do
  t=$(date +%s)
  b0=$(cat /sys/class/drm/card0/device/gpu_busy_percent)
  b1=$(cat /sys/class/drm/card1/device/gpu_busy_percent)
  v0=$(cat /sys/class/drm/card0/device/mem_info_vram_used)
  v1=$(cat /sys/class/drm/card1/device/mem_info_vram_used)
  echo "$t,$b0,$b1,$v0,$v1"
  sleep 5
done
