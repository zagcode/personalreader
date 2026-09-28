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

Com o VoxCPM2 há quatro vozes prontas em `app/tts/engines/voxcpm.py`, feitas com o recurso de voice design do VoxCPM2, que cria uma voz a partir de uma descrição em texto. Como uma voz desenhada varia um pouco de timbre de uma frase para outra, a primeira frase gerada com cada voz é salva em `data/app/voices/_anchor_<voz>.wav` e passa a servir de referência para as seguintes. Apague esse arquivo se quiser sortear outro timbre.

Para clonar uma voz, coloque um áudio curto e limpo (5 a 15 segundos) em `data/app/voices/nome.wav`. Se criar também `nome.txt` com a transcrição exata do áudio, o modelo usa o modo de clonagem mais fiel. A voz aparece na lista depois de recarregar a página.

## Trocar o modelo de voz

O VoxCPM2 é um dos motores possíveis. A fila, o cache, a API e o player só conhecem o contrato em `app/tts/base.py`, e cada motor fica num módulo em `app/tts/engines/` com as próprias vozes e opções. Para usar outro modelo:

1. Crie `app/tts/engines/<nome>.py` com uma classe que herda de `TTSEngine` e implementa:
   - `voices()`: a lista de vozes que o player mostra. Cada `Voice` tem `id`, `label`, os idiomas que fala (`languages`, vazio se o modelo detecta sozinho) e um dicionário `params` livre para o motor.
   - `synthesize(text, voice)`: devolve a onda mono em float32 e o sample rate.
   - `load()`: opcional. Carrega o modelo uma vez, antes da primeira frase.
   - `cache_id()`: opcional. Tudo que muda o áudio além do texto e da voz, como o nome do modelo e a precisão. O cache em disco usa esse valor na chave, então trocar de modelo nunca devolve áudio do anterior.
2. Registre o nome em `ENGINES` no `app/tts/engines/__init__.py`, ou pule o registro e use o caminho completo: `TTS_ENGINE=app.tts.engines.meu:MeuMotor`.
3. Leia as opções do motor de variáveis de ambiente com um prefixo próprio, dentro do módulo, como `voxcpm.py` faz com `VOXCPM_*`.
4. Ponha as dependências no `requirements.txt`. Só o motor escolhido é importado, então as dependências dos outros podem ficar de fora da imagem.

`app/tts/engines/mock.py` é o exemplo mínimo, e `tests/test_engines.py` tem o teste de contrato que um motor novo deve passar.

Um cuidado ao escolher o modelo: o VoxCPM2 descobre o idioma pelo texto, mas a maioria dos TTS rápidos (Kokoro, Piper) tem uma voz por idioma. Com eles você escolhe a voz do idioma do documento no player. Os campos `languages` já existem para o player um dia filtrar as vozes pelo idioma detectado, mas essa detecção ainda não está implementada.

## Requisitos da VPS

O VoxCPM2 tem 2 bilhões de parâmetros. O modelo vem em bfloat16, mas em CPU sem instruções bf16 no hardware essas contas são emuladas. Por isso `VOXCPM_DTYPE=auto` carrega o modelo em float32 quando roda em CPU. O modelo não é baixado de novo: o app monta em `data/.../models/` uma pasta com hardlinks para os mesmos pesos e só o `config.json` alterado.

Num PC desktop de 6 núcleos, gerando uma frase curta em inglês:

| dtype | passos | tempo de geração ÷ duração do áudio |
|---|---|---|
| bfloat16 | 10 | ~36× |
| float32 | 10 | ~10× |
| float32 | 6 | ~7× |

Em float32 o modelo ocupa uns 10 GB de RAM. Então a VPS precisa de 16 GB de RAM, 4 vCPUs ou mais e uns 25 GB de disco. Com só 8 GB de RAM, use `VOXCPM_DTYPE=bfloat16` (uns 5 GB) e aceite a lentidão, a não ser que a CPU tenha AMX (Xeon Sapphire Rapids ou mais novo). Nesse caso o bfloat16 tende a ser o mais rápido dos dois, mas isso não foi medido aqui.

Mesmo no melhor caso, uma frase leva bem mais tempo para gerar do que para tocar, e a pré-carga só compensa em parte. O canto superior direito da página mostra a razão medida no seu servidor, por exemplo "Cada segundo de fala leva ~7 s para gerar". O que ajuda:

- `VOXCPM_TIMESTEPS=6` (o padrão é 10) reduz os passos de difusão, com alguma perda de naturalidade;
- pausas a cada frase ou a cada 3 frases dão tempo para a fila adiantar o trecho seguinte;
- velocidade 0,85× no player estica o tempo de reprodução de cada frase.

A conversão com docling também é lenta em CPU. Um PDF de 9 páginas com tabelas levou 51 s no teste local. O OCR vem desligado (`DOCLING_OCR=false`) porque é a etapa mais cara. Ligue-o só se for ler PDFs escaneados ou imagens.

## Deploy com Docker

```bash
git clone https://github.com/zagcode/personalreader.git
cd personalreader
cp .env.example .env        # defina APP_PASSWORD e as variáveis TRAEFIK_*
docker compose up -d --build
docker compose logs -f      # a primeira subida baixa os modelos para ./data/hf
```

O container não publica porta nenhuma. Ele entra na rede externa do Traefik e é roteado pelas labels do `docker-compose.yml`, que leem quatro variáveis do `.env`:

| Variável | Padrão | O que é |
|---|---|---|
| `TRAEFIK_HOST` | (obrigatória) | domínio da página, por exemplo `leitor.seudominio.com` |
| `TRAEFIK_NETWORK` | `traefik` | rede Docker em que o seu Traefik está |
| `TRAEFIK_ENTRYPOINT` | `websecure` | entrypoint HTTPS do Traefik |
| `TRAEFIK_CERTRESOLVER` | `letsencrypt` | nome do certresolver configurado no Traefik |

Confira os nomes reais na configuração do seu Traefik; `docker network ls` mostra a rede. O redirecionamento de HTTP para HTTPS continua sendo do Traefik, como nos outros serviços.

A rota de áudio só responde quando a frase termina de ser gerada, o que em CPU pode levar mais de um minuto numa frase longa. Nos padrões do Traefik isso funciona, porque ele não limita o tempo de resposta do backend (`responseHeaderTimeout` é 0). Se você tiver definido `forwardingTimeouts` ou `respondingTimeouts.writeTimeout` na configuração, deixe folga de alguns minutos. No Traefik v3, `respondingTimeouts.readTimeout` do entrypoint vem em 60 s e vale para receber o upload. Por isso o limite de upload da demo é 10 MB (`MAX_UPLOAD_MB`): com uns 10% de overhead de HTTP e TLS, esse tamanho sobe em menos de 60 s a partir de ~1,5 Mbps de upload, que é o piso de um 4G fraco ou de um ADSL. Em 1 Mbps só caberiam uns 6,5 MB. Se precisar de arquivos maiores, aumente `MAX_UPLOAD_MB` e o `readTimeout` do entrypoint juntos.

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
