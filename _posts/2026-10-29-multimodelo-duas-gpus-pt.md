---
title: "Dois servidores na mesma GPU AMD deixaram a placa em 100% sem trabalho; uma variável resolveu"
lang: pt-BR
permalink: /pt/2026/10/29/multimodelo-duas-gpus/
description: "Laboratório: dois processos llama.cpp (ROCm) na mesma RX 9060 XT mantinham a GPU em 100% e ~37 W ociosa. Isolei a causa em 4 experimentos e medi o contorno GPU_MAX_HW_QUEUES=1: 11 W ociosa, +2,6 ms por embedding."
resumo: "Dois processos llama.cpp com ROCm na mesma placa a mantinham em 100% e 37 W parada. Quatro experimentos até a causa, e um contorno de 2,6 ms por pedido."
image: /assets/img/multimodelo-duas-gpus/cover-pt.png
---

*[Read in English]({{ "/en/2026/10/29/multimodelo-duas-gpus/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>Versão 2 · 30 de outubro de 2026 · <a href="#o-que-mudou">o que mudou</a></span></p>

<p class="lead">Num hospedeiro com duas GPUs AMD de 16 GB, a segunda placa ficava em 100% de uso o dia inteiro, sem nenhum pedido. A causa não era um modelo nem um pedido preso: bastava ter <strong>dois processos</strong> llama.cpp com ROCm na mesma GPU. Uma variável de ambiente do HIP devolveu a placa ao repouso, ao custo de 2,6 ms por embedding.</p>

É um laboratório pessoal, não produção. O post mostra como isolei a causa, o contorno, quanto ele custa e o que ainda não sei.

<div class="tiles">
<div class="tile foco"><div class="tile-value">100%</div><div class="tile-label">uso da GPU com 2 processos ociosos: 11 de 11 janelas com a configuração padrão, em 4 experimentos</div></div>
<div class="tile"><div class="tile-value">37 → 11 W</div><div class="tile-label">potência da GPU ociosa, antes e depois do contorno (mediana, 120 leituras cada)</div></div>
<div class="tile neutro"><div class="tile-value">+2,6 ms</div><div class="tile-label">custo por pedido de embedding (7,6 → 10,2 ms, 60 pedidos cada)</div></div>
</div>

<div class="key" markdown="1">
Em resumo

- **Dois processos na mesma GPU bastam.** Com um servidor só, a GPU 1 ficou em 2% e 11 a 12 W. Com os dois, 100% e 35 a 39 W, mesmo sem nenhum pedido.
- **Não depende do modelo nem da placa.** O padrão se repetiu com a ordem invertida e também na GPU 0, quando subi um segundo processo ao lado do modelo de fallback.
- **O consumo é real, não um erro de leitura.** O clock subiu de 31 MHz para cerca de 3.450 MHz junto com a potência.
- **`GPU_MAX_HW_QUEUES=1` resolveu** neste ambiente: 2% e 11 W com os dois servidores ligados, depois de pedidos reais. Com `=2`, voltou a 100%.
- **Custo medido:** +2,6 ms por embedding (+34%) e +5 ms por completação de 64 tokens (+0,6%). O contorno ficou aplicado.
- **Limite:** não sei o mecanismo dentro do driver. Os relatos públicos [1][2][3] descrevem o mesmo sintoma em outras placas AMD, mas sem causa confirmada.
</div>

<div class="toc-box" markdown="1">
<strong>Neste post</strong>

* TOC
{:toc}
</div>

## O que mudou nesta versão {#o-que-mudou}

<div class="callout" markdown="1">
A primeira versão (29/10) dizia que a causa estava "fora do timer" e que não tinha sido investigada. Também dizia que o backend era Vulkan. Corrigi três coisas:

- **Backend:** os três servidores usam **ROCm (HIP)**, não Vulkan. Conferi pelas bibliotecas carregadas em cada processo.
- **Causa:** o timer não tinha relação com o problema. A causa é ter dois processos HIP na mesma GPU (seção [Resultados](#resultados)).
- **Figura em inglês:** a versão em inglês usava a figura em português. Agora cada idioma tem a sua.
</div>

## Ambiente

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/ambiente-pt.svg" | relative_url }}" alt="Diagrama do hospedeiro: GPU 0 com o modelo de fallback Qwen3-14B (10,4 GB); GPU 1 com dois processos, completação de código Qwen2.5-Coder-3B na porta 8083 e embeddings Qwen3-Embedding-0.6B na porta 8084." loading="lazy">
<figcaption>Distribuição dos modelos. A GPU 0 tem um processo (o fallback do roteador). A GPU 1 tem dois processos independentes, e é nela que o problema aparecia.</figcaption>
</figure>

| Item | Valor |
|---|---|
| Hospedeiro | AMD Ryzen 5 5600G (12 threads), 62 GB de RAM, Proxmox VE 8.4.19, kernel 6.14.11 |
| GPUs | 2 × AMD Radeon RX 9060 XT (Navi 44, RDNA4), 16 GB cada |
| Container | LXC privilegiado com as duas GPUs, Ubuntu 24.04 |
| ROCm | 7.2.3 |
| Servidor | llama.cpp `llama-server`, build 216 (`f12cc6d`), backend HIP |
| GPU 0 | Qwen3-14B Q4_K_M, contexto 16k, sempre carregado (fallback do roteador semântico) |
| GPU 1 | Qwen2.5-Coder-3B Q4_K_M (completação de código) e Qwen3-Embedding-0.6B Q8_0 (embeddings do RAG), um `llama-server` para cada |
| Estado | sem pedidos durante as janelas ociosas; os servidores atendem a rede local, mas os logs não mostravam tráfego |

Endereços, nomes de máquina e chaves ficaram fora do texto e dos dados.

## Como medi

Usei três leituras que o driver `amdgpu` expõe no sysfs do hospedeiro, uma por segundo:

- `gpu_busy_percent`: o firmware de gerenciamento de energia (SMU) amostra, a cada milissegundo, se algum bloco da GPU está ocupado, e devolve a fração [4][5];
- `power1_average`: potência média da placa, em microwatts [5];
- `pp_dpm_sclk`: o clock atual do núcleo.

Para saber **quais processos** usam cada placa, li `/proc/<pid>/fdinfo`. O kernel publica ali, para cada descritor de GPU aberto, o endereço PCI da placa e a memória usada pelo processo [6]. Os contadores de tempo de motor não aparecem para cargas de computação do ROCm, então a identificação foi por exclusão: ligar e desligar cada servidor e observar a placa.

Cada experimento é um script que roda no hospedeiro, liga e desliga os serviços dentro do container e grava as leituras em CSV. Descartei os 10 primeiros segundos de cada fase, que são transição.

| Experimento | O que varia | Fases × duração |
|---|---|---|
| A | desliga um servidor por vez, depois os dois; religa; manda 1 pedido a cada servidor | 7 × 90 s |
| B | a mesma coisa em outra ordem; depois sobe um 2º processo na GPU 0 | 6 × 60 s |
| C | `GPU_MAX_HW_QUEUES` ausente, `=1`, `=2`, ausente de novo | 4 × 60 s |
| D | custo do contorno: 30 embeddings e 10 completações por configuração, depois 60 s ociosa | 2 rodadas × 2 configurações |

## Resultados

### 1. A GPU só fica ocupada quando os dois servidores estão ligados

A figura abaixo é o experimento A inteiro. A faixa laranja marca as fases com dois processos na GPU 1.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/fases-pt.svg" | relative_url }}" alt="Série temporal de 650 segundos. Uso da GPU 1 em 100% com os dois servidores ligados, cai para 2% quando um deles é desligado (qualquer um), 0% com os dois desligados e volta a 100% assim que os dois são religados, antes de qualquer pedido. A potência acompanha: cerca de 38 W, 12 W, 9 W e de novo 35 a 37 W." loading="lazy">
<figcaption>Experimento A, uma leitura por segundo. O que olhar: o uso volta a 100% no segundo 375, quando os dois servidores sobem de novo, <em>antes</em> de qualquer pedido. Os picos de potência nas fases 6 e 7 são os dois pedidos.</figcaption>
</figure>

- **Qualquer um dos dois, sozinho, fica em 2%.** Não é um servidor específico: desligar a completação ou o embedding dá o mesmo resultado.
- **Os pedidos não mudam nada.** A placa já estava em 100% antes deles (fase 5) e continuou depois (fases 6 e 7).
- **O consumo acompanha o indicador.** O clock foi de 31 MHz (um processo) para cerca de 3.450 MHz (dois processos), e a potência de 11 a 12 W para 35 a 39 W. Não é um erro de leitura do `gpu_busy_percent`: a placa está de fato ativa.

### 2. A regra se repete na outra ordem e na outra GPU

No experimento B inverti a ordem. Depois, para separar o efeito "dois processos" do efeito "estes dois modelos", subi temporariamente um segundo processo na **GPU 0**, ao lado do modelo de fallback, que até então ficava em 2%.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/regra-pt.svg" | relative_url }}" alt="Dois gráficos de pontos. Eixo x: número de processos llama-server na mesma GPU (0, 1, 2). Com 0 processos, 0% e 9 W. Com 1, cerca de 2% e 11 a 12 W. Com 2, 100% e 35 a 39 W. Os pontos do experimento A, do experimento B e do controle na GPU 0 ficam juntos em cada grupo." loading="lazy">
<figcaption>Cada ponto é a mediana de uma fase. O que olhar: os três marcadores (experimento A, experimento B e GPU 0) caem no mesmo lugar. O número de processos explica o uso; o modelo e a placa, não.</figcaption>
<details><summary>Números por fase</summary>
<p>Experimento A: fases com 2 processos: 100% (mín. e máx. 100) e 35 a 39 W; com 1 processo: 2% e 11 a 12 W; sem processos: 0% e 9 W. Experimento B: 2 processos: 100%, 36 a 38 W; 1 processo: 2%, 11 a 12 W. GPU 0 com o fallback e um processo temporário: 100% e 36 W; só o fallback: 2% e 11 W. Arquivo completo: <code>resumo_fases.json</code> em <code>labs/</code>.</p>
</details>
</figure>

Esse padrão bate com dois relatos públicos. No primeiro, de 2023, uma RX 7900 (RDNA3) rodando o mesmo `llama-server` ficava em 100% ociosa, e o autor ligou o efeito à criação de filas de hardware pelo runtime HIP [1][2]. No segundo, de 2026, um APU Ryzen AI MAX (gfx1151) ficava em 100% e no clock máximo **sempre que dois ou mais clientes ROCm** tinham modelos residentes, e voltava ao repouso com um só [3]. A minha placa é de outra geração (RDNA4). Não encontrei explicação oficial do mecanismo.

### 3. O contorno: uma fila de hardware por processo

Cada processo HIP cria, por padrão, até 4 filas de hardware por GPU, controladas pela variável `GPU_MAX_HW_QUEUES` [7]. Um dos comentários do relato de 2023 cita essa variável como contorno [1]. Testei com `1` e `2`, com os dois servidores ligados e depois de um pedido a cada um:

| Configuração (2 processos na GPU 1) | Uso mediano | Potência mediana | Leituras |
|---|---|---|---|
| padrão (4 filas) | 100% | 37 W | 50 |
| `GPU_MAX_HW_QUEUES=1` | **2%** | **12 W** | 50 |
| `GPU_MAX_HW_QUEUES=2` | 100% | 37 W | 50 |
| padrão de novo | 100% | 37 W | 50 |

Leitura: com uma fila por processo, a placa repousa mesmo com dois processos. Com duas, não. Voltar ao padrão traz o problema de volta, então não foi o reinício que resolveu.

### 4. Quanto o contorno custa

Uma fila só serializa o trabalho de cada processo. Para medir o custo, repeti, em duas rodadas por configuração, 30 pedidos de embedding com um texto de 1.000 caracteres (o tamanho de um trecho do meu índice RAG) e 10 completações de 64 tokens.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/contorno-pt.svg" | relative_url }}" alt="Dois gráficos de pontos. À esquerda, potência da GPU 1 ociosa: 37 W no padrão e 11 W com GPU_MAX_HW_QUEUES=1. À direita, tempo por pedido de embedding: mediana de 7,6 ms no padrão e 10,2 ms com o contorno." loading="lazy">
<figcaption>Experimento D. O que olhar: a potência ociosa cai 26 W, e o embedding fica 2,6 ms mais lento. Os pontos são leituras e pedidos individuais; a barra preta é a mediana.</figcaption>
</figure>

| Medida | Padrão | `GPU_MAX_HW_QUEUES=1` | Δ |
|---|---|---|---|
| GPU 1 ociosa, uso (120 leituras) | 100% | 2% | −98 p.p. |
| GPU 1 ociosa, potência | 37 W | 11 W | −26 W |
| Embedding, 1.000 caracteres (60 pedidos) | 7,6 ms | 10,2 ms | +2,6 ms (+34%) |
| Completação, 64 tokens (20 pedidos) | 912 ms | 918 ms | +5 ms (+0,6%) |
| Erros HTTP | 0 | 0 | — |

- **Para o meu uso, o custo é irrelevante.** O indexador do RAG gera algumas centenas de embeddings por hora; 2,6 ms a mais em cada um somam menos de um segundo. A completação, dominada pela geração de tokens, quase não muda.
- **A economia é contínua.** 26 W a menos, 24 horas por dia, dão cerca de 230 kWh por ano. É uma conta sobre a potência que a placa informa, não medição na tomada.
- **Apliquei o contorno** nos dois serviços da GPU 1, com um arquivo de override do systemd. A GPU 0 continua com um processo só e não precisou.

## O que deu errado

| Sintoma | Causa | Correção |
|---|---|---|
| GPU 1 em 100% e ~37 W sem pedidos | dois processos HIP na mesma GPU, com as filas padrão | `GPU_MAX_HW_QUEUES=1` nos dois serviços |
| Atribuí a causa ao timer de descarga | o timer só alcança o roteador, mas isso não tinha relação com o sintoma | medir ligando e desligando cada processo |
| Post anterior dizia "Vulkan" | os serviços têm variáveis de ambiente de Vulkan, mas o binário foi compilado com HIP | conferir as bibliotecas carregadas pelo processo |
| Modelo de 27B não coube | 30 GB em Q6, numa placa de 16 GB | removido; o hospedeiro ficou com modelos de até 14B |

## Limites

- **Uma máquina e um driver.** Não testei outro kernel, outra versão do ROCm nem Vulkan.
- **Não sei o mecanismo.** Os dados mostram a relação entre número de processos, filas e uso, não o que o firmware faz por dentro.
- **Janelas curtas.** As fases têm de 60 a 90 s. Não medi o contorno por dias; vou acompanhar a potência.
- **Potência informada pela placa**, não medida na tomada.
- **Custo medido em pedidos sequenciais.** Com muitos pedidos simultâneos no mesmo processo, uma fila só pode custar mais.
- O episódio antigo do modo de repouso do llama.cpp (que também deixava a GPU 0 em 100%) pode ter a mesma causa, mas não testei.

## Como reproduzir

Pré-requisitos: um hospedeiro Linux com GPU AMD e o driver `amdgpu`, ROCm, `llama-server` compilado com HIP, dois modelos GGUF pequenos e acesso root para ler o sysfs. Tempo: cerca de 40 minutos.

1. **Suba dois `llama-server` na mesma GPU**, por exemplo um de embeddings e um de completação:

   ```bash
   ROCR_VISIBLE_DEVICES=1 llama-server -m <MODELO_EMBED>.gguf -ngl 99 --embeddings --port 8084 --api-key <CHAVE> &
   ROCR_VISIBLE_DEVICES=1 llama-server -m <MODELO_FIM>.gguf -ngl 99 --port 8083 --api-key <CHAVE> &
   ```

   *Funcionou se* `curl http://<HOST>:8084/health` devolver `{"status":"ok"}`.

2. **Leia o uso da placa sem mandar pedidos:** `cat /sys/class/drm/card1/device/gpu_busy_percent`. *Reproduziu se* ficar em 100 por mais de 1 minuto.
3. **Desligue um dos dois** e leia de novo. *Reproduziu se* cair para perto de 0.
4. **Aplique o contorno** e religue os dois:

   ```ini
   # /etc/systemd/system/<servico>.service.d/gpu-max-hw-queues.conf
   [Service]
   Environment=GPU_MAX_HW_QUEUES=1
   ```

   *Funcionou se* o uso ficar perto de 0 com os dois ligados.
5. **Rode as medições do post:** os scripts `experimento_a.sh` a `experimento_d.sh` (no hospedeiro Proxmox, com `CT=<id do container>`) gravam os CSV; `make_figures.py` gera as figuras e o `resumo_fases.json`.

Variação conhecida: o relato de 2026 [3] diz que, num APU, `GPU_MAX_HW_QUEUES=1` piorou o sintoma com PyTorch. Teste na sua placa antes de aplicar.

## Material para reproduzir

Scripts, dados brutos (CSV de cada experimento) e o gerador das figuras: [`labs/multimodelo-duas-gpus/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/multimodelo-duas-gpus).

## Referências

1. Googulator, "100% GPU usage and high power draw when creating multiple HW queues with MES on RDNA3", ROCm/amdgpu, issue #153, nov. 2023, com comentários até 2026. <https://github.com/ROCm/amdgpu/issues/153>. Sustenta: o mesmo sintoma com `llama-server` em RDNA3, ligado à criação de filas de hardware; o comentário com `GPU_MAX_HW_QUEUES` como contorno; um relato em RDNA4.
2. Googulator, "100% GPU usage and high power draw during idle after memcpy/memset with HIP streams on RDNA3", ROCm/ROCm, issue #2625, nov. 2023. <https://github.com/ROCm/ROCm/issues/2625>. Sustenta: o relato original, com casos mínimos em HIP que reproduzem o 100% sem executar código na GPU.
3. "gfx1151 (Strix Halo): GPU pinned at 100% busy / max sclk whenever ≥2 idle ROCm compute clients are resident", ROCm/TheRock, issue #7578, ago. 2026. <https://github.com/ROCm/TheRock/issues/7578>. Sustenta: o padrão "um cliente repousa, dois clientes ficam em 100%", em outra placa, e a ressalva de que `GPU_MAX_HW_QUEUES=1` piorou num caso com PyTorch.
4. Ubuntu, página de manual `rocm-smi(1)`, Ubuntu 24.04. <https://manpages.ubuntu.com/manpages/noble/man1/rocm-smi.1.html>. Sustenta: como o `gpu_busy_percent` é calculado (amostragem de blocos ocupados pelo SMU).
5. The Linux Kernel documentation, "GPU Power/Thermal Controls and Monitoring" (amdgpu). <https://docs.kernel.org/gpu/amdgpu/thermal.html>. Sustenta: o significado de `gpu_busy_percent` e de `power1_average`.
6. The Linux Kernel documentation, "DRM client usage stats". <https://docs.kernel.org/gpu/drm-usage-stats.html>. Sustenta: os campos de `fdinfo` (`drm-pdev`, memória por região) usados para saber qual processo usa qual placa.
7. AMD, "HIP environment variables", documentação do HIP (ROCm). <https://rocm.docs.amd.com/projects/HIP/en/latest/reference/env_variables.html>. Sustenta: `GPU_MAX_HW_QUEUES` define o número máximo de filas de hardware por processo e por dispositivo (padrão 4).

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
