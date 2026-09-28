# Personal Reader

Leitor em voz alta para treinar audição em outros idiomas. Você envia um arquivo (PDF, DOCX, EPUB, HTML, PPTX, XLSX, ODT, Markdown ou texto), o [docling](https://github.com/docling-project/docling) converte o conteúdo para Markdown e o [VoxCPM2](https://github.com/OpenBMB/VoxCPM) lê o texto frase por frase. O VoxCPM2 fala 30 idiomas e detecta o idioma pelo próprio texto, sem precisar de configuração.

Foi pensado para uma VPS sem GPU. O áudio não é gerado de uma vez: o servidor sintetiza a frase que está tocando e as seguintes até o próximo ponto de confirmação. Ao fim de cada trecho a leitura pausa e pergunta se você quer continuar ou ouvir o trecho de novo. Enquanto a pausa não é respondida, o servidor não gera mais nada além da primeira frase do trecho seguinte, então uma aba esquecida aberta não ocupa a CPU com o livro inteiro.

## Como funciona

1. O upload grava o arquivo em `data/app/docs/<id>/` e entra numa fila de conversão, que processa um documento por vez.
2. O docling gera Markdown. `app/segmenter.py` separa o Markdown em blocos (títulos, parágrafos, listas, citações e tabelas) e os blocos em frases. Frases muito curtas são juntadas à seguinte e as muito longas são quebradas em vírgula ou ponto e vírgula. Tabelas aparecem na tela, mas não são lidas, e blocos de código são ignorados.
3. O player pede o áudio de uma frase por vez. `app/tts/queue.py` tem um único worker: em CPU, duas sínteses em paralelo só dividem os núcleos. A frase que o player está esperando passa na frente das frases de pré-carga.
4. O áudio gerado fica em cache no disco (MP3), indexado pelo texto e pela voz. Ouvir de novo, voltar a um trecho ou reabrir o documento não gera nada outra vez.

## Na tela de leitura

A pausa para confirmar pode acontecer ao fim de cada parágrafo (o padrão), a cada frase, a cada 3 ou a cada 6 frases. Um título conta junto com o parágrafo que vem depois dele, e uma lista inteira conta como um trecho só.

Em Ajustes você também escolhe a voz, a velocidade (de 0,7× a 1,3×, sem mudar o tom), quantas vezes cada frase se repete e o modo escuta, que desfoca cada frase até você terminar de ouvi-la.

Atalhos: espaço toca ou pausa, ← e → mudam de frase, A repete a frase atual e R revela a frase no modo escuta. Clicar numa frase começa a leitura por ela. A posição de cada documento fica salva no navegador.

## Vozes

Há quatro vozes prontas em `app/tts/voices.py`, feitas com o recurso de voice design do VoxCPM2, que cria uma voz a partir de uma descrição em texto. Como uma voz desenhada varia um pouco de timbre de uma frase para outra, a primeira frase gerada com cada voz é salva em `data/app/voices/_anchor_<voz>.wav` e passa a servir de referência para as seguintes. Apague esse arquivo se quiser sortear outro timbre.

Para clonar uma voz, coloque um áudio curto e limpo (5 a 15 segundos) em `data/app/voices/nome.wav`. Se criar também `nome.txt` com a transcrição exata do áudio, o modelo usa o modo de clonagem mais fiel. A voz aparece na lista depois de recarregar a página.

## Requisitos da VPS

O VoxCPM2 tem 2 bilhões de parâmetros e roda em bfloat16 na CPU, o que ocupa uns 5 GB de RAM. Somando o docling e o sistema, conte com pelo menos 8 GB de RAM (16 GB é mais confortável), 4 vCPUs ou mais e uns 20 GB de disco para imagem, modelos e cache.

A velocidade em CPU não foi medida neste projeto. Espere que uma frase leve mais tempo para gerar do que para tocar, e que CPUs com AVX-512 BF16 ou AMX (Xeon Sapphire Rapids ou mais novos, EPYC Zen 4 ou mais novos) sejam bem mais rápidas que as outras. O canto superior direito da página mostra a razão medida no seu servidor, por exemplo "Cada segundo de fala leva ~3 s para gerar". Com uma razão alta, o que ajuda:

- `VOXCPM_TIMESTEPS=6` (o padrão é 10) reduz os passos de difusão, com alguma perda de naturalidade;
- pausas a cada frase ou a cada 3 frases dão tempo para a fila adiantar o trecho seguinte;
- velocidade 0,85× no player estica o tempo de reprodução de cada frase.

A conversão com docling também é lenta em CPU. Um PDF de 9 páginas com tabelas levou 51 s no teste local. O OCR vem desligado (`DOCLING_OCR=false`) porque é a etapa mais cara. Ligue-o só se for ler PDFs escaneados ou imagens.

## Deploy com Docker

```bash
git clone https://github.com/zagcode/personalreader.git
cd personalreader
cp .env.example .env        # defina APP_PASSWORD
docker compose up -d --build
docker compose logs -f      # a primeira subida baixa os modelos para ./data/hf
```

O container escuta só em `127.0.0.1:8000`. Coloque o nginx na frente usando `deploy/nginx.conf` como base e gere o certificado com `certbot --nginx`. O `proxy_read_timeout` alto desse arquivo é necessário: a rota de áudio só responde quando a frase termina de ser gerada.

Com `APP_PASSWORD` definido, o navegador pede usuário e senha (qualquer usuário, essa senha). Sem senha, qualquer pessoa que achar o endereço consegue enviar arquivos e ocupar a CPU.

## Desenvolvimento local

O motor `mock` troca a voz por bipes com a duração aproximada da frase. Serve para mexer na interface sem baixar o modelo.

```bash
python -m venv .venv
.venv/Scripts/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # Linux/macOS: .venv/bin/pip
.venv/Scripts/pip install -r requirements-dev.txt
TTS_ENGINE=mock .venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

Para testar com a voz real, instale também `torchaudio` pelo mesmo índice de CPU, depois `pip install voxcpm`, e rode sem `TTS_ENGINE=mock`. O VoxCPM exige Python entre 3.10 e 3.12.

## Configuração

Todas as opções estão comentadas em `.env.example`. As que mais importam na prática são `APP_PASSWORD`, `VOXCPM_TIMESTEPS`, `TORCH_THREADS`, `DOCLING_OCR` e `MAX_UPLOAD_MB`.

## API

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/health` | estado do motor de voz, fila e razão de tempo real medida |
| GET | `/api/config` | formatos aceitos, limite de upload e vozes |
| GET | `/api/documents` | lista os documentos |
| POST | `/api/documents` | envia um arquivo (multipart, campo `file`) |
| GET | `/api/documents/{id}` | metadados e, quando pronto, blocos e frases |
| DELETE | `/api/documents/{id}` | apaga o documento |
| GET | `/api/documents/{id}/segments/{i}/audio?voice=` | áudio da frase `i`, gerado na hora se ainda não existir |
| POST | `/api/documents/{id}/prefetch` | `{voice, start, end}`: enfileira essa janela e descarta pendências fora dela |

## Licenças

docling usa a licença MIT e o VoxCPM, Apache 2.0.
