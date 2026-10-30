# Multimodelo em duas GPUs: material para reproduzir

Acompanha o post "Multimodelo em duas GPUs de 16 GB" (pt-BR e en).

- `scripts/amostrar_gpu.sh`: amostra uso e VRAM das duas GPUs a cada 5 s, por 5 minutos, no hospedeiro.
- `scripts/make_figures.py`: gera a figura a partir do CSV.
- `data/gpu_amostra.csv`: 60 leituras da medição do dia.

Uma amostra de 5 minutos não basta para concluir sobre a GPU 1. Para investigar, é preciso amostrar em outros momentos e identificar qual processo usa a placa.
