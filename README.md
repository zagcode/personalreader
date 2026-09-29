# Personal Reader

Leitor em voz alta para treinar audição em outros idiomas. Você envia um arquivo (PDF, DOCX, EPUB, HTML, PPTX, XLSX, ODT, Markdown ou texto), o [docling](https://github.com/docling-project/docling) converte o conteúdo para Markdown e um modelo de voz lê o texto frase por frase. O modelo padrão é o [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), rodando pelo [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), que em CPU gera a fala mais rápido do que ela toca.

Foi pensado para uma VPS sem GPU. O áudio não é gerado de uma vez: o servidor sintetiza a frase que está tocando e as seguintes até o próximo ponto de confirmação. Ao fim de cada trecho a leitura pausa e pergunta se você quer continuar ou ouvir o trecho de novo. Enquanto a pausa não é respondida, o servidor não gera mais nada além da primeira frase do trecho seguinte, então uma aba esquecida aberta não ocupa a CPU com o livro inteiro.

## Como funciona

1. O upload grava o arquivo em `data/app/docs/<id>/` e entra numa fila de conversão, que processa um documento por vez. PDFs são convertidos em blocos de 4 páginas (`DOCLING_PAGES_PER_STEP`), e a página mostra a porcentagem a cada bloco. No teste local, converter em blocos levou o mesmo tempo que converter tudo de uma vez. Quando um parágrafo atravessa a divisa entre dois blocos, as duas metades são juntadas de novo. Os outros formatos não têm páginas no docling e mostram só "Convertendo o arquivo…", mas costumam ficar prontos em segundos.
2. O docling gera Markdown. `app/segmenter.py` separa o Markdown em blocos (títulos, parágrafos, listas, citações e tabelas) e os blocos em frases. Frases muito curtas são juntadas à seguinte e as muito longas são quebradas em vírgula ou ponto e vírgula. Tabelas aparecem na tela, mas não são lidas, e blocos de código são ignorados.
3. O player pede o áudio de uma frase por vez. `app/tts/queue.py` tem um único worker: em CPU, duas sínteses em paralelo só dividem os núcleos. A frase que o player está esperando passa na frente das frases de pré-carga.
4. O áudio gerado fica em cache no disco (MP3), indexado pelo modelo, pela voz e pelo texto. Ouvir de novo, voltar a um trecho ou reabrir o documento não gera nada outra vez.

## Na tela de leitura

A pausa para confirmar pode acontecer ao fim de cada parágrafo (o padrão), a cada frase, a cada 3 ou a cada 6 frases. Um título conta junto com o parágrafo que vem depois dele, e uma lista inteira conta como um trecho só.

Em Ajustes você também escolhe a voz, a velocidade (de 0,7× a 1,3×, sem mudar o tom), quantas vezes cada frase se repete e o modo escuta, que desfoca cada frase até você terminar de ouvi-la.

Atalhos: espaço toca ou pausa, ← e → mudam de frase, A repete a frase atual e R revela a frase no modo escuta. Clicar numa frase começa a leitura por ela. A posição de cada documento e a voz escolhida ficam salvas no navegador.

## Vozes do Kokoro

O seletor de voz em Ajustes lista todas as vozes do arquivo de vozes do modelo, agrupadas por idioma: inglês americano (20), inglês britânico (8), chinês (8), hindi (4), português do Brasil (3), espanhol (3), italiano (2) e francês (1). A voz padrão é a `af_heart`, a mais bem avaliada na lista do próprio Kokoro.

Cada voz fala um idioma só. O texto é convertido em fonemas no idioma da voz, então um texto em inglês lido por uma voz portuguesa sai com pronúncia errada. Escolha a voz pelo idioma do documento. O app ainda não detecta o idioma sozinho.

Os fonemas vêm do espeak-ng, que já vem embutido no kokoro-onnx, com duas exceções:

- Chinês usa o `misaki[zh]`, que está no `requirements.txt`. Pelo espeak o mandarim sai sem os tons.
- Japonês fica de fora da lista. O espeak não lê kanji (fala "Chinese letter" no lugar de cada ideograma), e o `misaki[ja]` depende do `pyopenjtalk`, que precisa compilar código C. A compilação falhou no Windows e não foi testada no Linux. Se `misaki[ja]` estiver instalado, as 5 vozes japonesas aparecem sozinhas na lista.

Num PC desktop de 6 núcleos, o Kokoro gerou cada frase em 0,4 a 0,7 do tempo que ela leva para tocar, com o processo usando uns 625 MB de RAM antes da primeira conversão com o docling. A versão int8 do modelo (`kokoro-v1.0.int8.onnx`, 114 MB) foi 10 vezes mais lenta que a fp32 nessa CPU, por isso o padrão é a fp32 (326 MB). Os arquivos são baixados sozinhos para `data/app/models/kokoro/` na primeira subida.

## Trocar o modelo de voz

A fila, o cache, a API e o player só conhecem o contrato em `app/tts/base.py`. Cada motor fica num módulo em `app/tts/engines/` com as próprias vozes e opções: `kokoro.py` e `mock.py`, que troca a voz por bipes para testes. Para usar outro modelo:

1. Crie `app/tts/engines/<nome>.py` com uma classe que herda de `TTSEngine` e implementa:
   - `voices()`: a lista de vozes que o player mostra. Cada `Voice` tem `id`, `label`, o grupo em que aparece no seletor (`group`), os idiomas que fala (`languages`) e um dicionário `params` livre para o motor.
   - `synthesize(text, voice)`: devolve a onda mono em float32 e o sample rate.
   - `load()`: opcional. Carrega o modelo uma vez, antes da primeira frase.
   - `cache_id()`: opcional. Tudo que muda o áudio além do texto e da voz, como o nome do modelo e a precisão. O cache em disco usa esse valor na chave, então trocar de modelo nunca devolve áudio do anterior.
2. Registre o nome em `ENGINES` no `app/tts/engines/__init__.py`, ou pule o registro e use o caminho completo: `TTS_ENGINE=app.tts.engines.meu:MeuMotor`.
3. Leia as opções do motor de variáveis de ambiente com um prefixo próprio, dentro do módulo, como `kokoro.py` faz com `KOKORO_*`.
4. Ponha as dependências no `requirements.txt`. Só o motor escolhido é importado.

`app/tts/engines/mock.py` é o exemplo mínimo, e `tests/test_engines.py` tem o teste de contrato que um motor novo deve passar.

## Requisitos da VPS

Com o Kokoro, 2 vCPUs e 4 GB de RAM devem bastar para uma demo. Não medi o pico de memória do docling convertendo um PDF grande, que é a etapa mais pesada, então 4 GB é uma estimativa com folga, não um número testado. Reserve uns 8 GB de disco para a imagem (o torch do docling é a maior parte), os modelos e o cache de áudio.

A conversão com docling é lenta em CPU. Um PDF de 9 páginas com tabelas levou 51 s no teste local. O OCR vem desligado (`DOCLING_OCR=false`) porque é a etapa mais cara. Ligue-o só se for ler PDFs escaneados ou imagens.

O canto superior direito da página mostra quanto tempo o servidor leva para gerar cada segundo de fala. Acima de 1, a leitura terá esperas entre as frases.

## Deploy com Docker

```bash
git clone https://github.com/zagcode/personalreader.git
cd personalreader
cp .env.example .env        # defina APP_PASSWORD e as variáveis TRAEFIK_*
docker compose up -d --build
docker compose logs -f      # a primeira subida baixa os modelos para ./data
```

O container não publica porta nenhuma. Ele entra na rede externa do Traefik e é roteado pelas labels do `docker-compose.yml`, que leem quatro variáveis do `.env`:

| Variável | Padrão | O que é |
|---|---|---|
| `TRAEFIK_HOST` | (obrigatória) | domínio da página, por exemplo `leitor.seudominio.com` |
| `TRAEFIK_NETWORK` | `traefik` | rede Docker em que o seu Traefik está |
| `TRAEFIK_ENTRYPOINT` | `websecure` | entrypoint HTTPS do Traefik |
| `TRAEFIK_CERTRESOLVER` | `letsencrypt` | nome do certresolver configurado no Traefik |

Confira os nomes reais na configuração do seu Traefik; `docker network ls` mostra a rede. O redirecionamento de HTTP para HTTPS continua sendo do Traefik, como nos outros serviços.

A rota de áudio só responde quando a frase termina de ser gerada. Com o Kokoro isso leva poucos segundos, e nos padrões do Traefik funciona sem ajuste, porque ele não limita o tempo de resposta do backend (`responseHeaderTimeout` é 0). Se você tiver definido `forwardingTimeouts` ou `respondingTimeouts.writeTimeout` na configuração, deixe pelo menos um minuto de folga para frases longas numa CPU mais fraca.

No Traefik v3, `respondingTimeouts.readTimeout` do entrypoint vem em 60 s e vale para receber o upload. Por isso o limite de upload da demo é 10 MB (`MAX_UPLOAD_MB`): com uns 10% de overhead de HTTP e TLS, esse tamanho sobe em menos de 60 s a partir de ~1,5 Mbps de upload, que é o piso de um 4G fraco ou de um ADSL. Em 1 Mbps só caberiam uns 6,5 MB. Se precisar de arquivos maiores, aumente `MAX_UPLOAD_MB` e o `readTimeout` do entrypoint juntos.

Com `APP_PASSWORD` definido, o navegador pede usuário e senha (qualquer usuário, essa senha). Sem senha, qualquer pessoa que achar o endereço consegue enviar arquivos e ocupar a CPU.

## Desenvolvimento local

```bash
python -m venv .venv
.venv/Scripts/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # Linux/macOS: .venv/bin/pip
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

Isso já roda com o Kokoro, que baixa os arquivos do modelo (uns 350 MB) na primeira subida. `TTS_ENGINE=mock` troca a voz por bipes e não baixa nada.

## Configuração

Todas as opções estão comentadas em `.env.example`. As que mais importam na prática são `APP_PASSWORD`, `TTS_ENGINE`, `DOCLING_OCR` e `MAX_UPLOAD_MB`.

## API

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/health` | estado do motor de voz, fila e razão de tempo real medida |
| GET | `/api/config` | formatos aceitos, limite de upload e vozes (com grupo e idiomas) |
| GET | `/api/documents` | lista os documentos |
| POST | `/api/documents` | envia um arquivo (multipart, campo `file`) |
| GET | `/api/documents/{id}` | metadados e, quando pronto, blocos e frases |
| DELETE | `/api/documents/{id}` | apaga o documento |
| GET | `/api/documents/{id}/segments/{i}/audio?voice=` | áudio da frase `i`, gerado na hora se ainda não existir |
| POST | `/api/documents/{id}/prefetch` | `{voice, start, end}`: enfileira essa janela e descarta pendências fora dela |

## Licenças

docling e kokoro-onnx usam a licença MIT, e o modelo Kokoro-82M, Apache 2.0.
