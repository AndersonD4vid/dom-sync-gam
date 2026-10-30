# Teste 1

# DOM - Data Orchestrator for Metrics

Pipeline de sincronizacao de metricas do **Google Ad Manager (GAM)** para MongoDB. Extrai relatorios de receita por dominio e UTM campaign via SOAP API, processa as metricas e persiste em bulk no MongoDB.

## Guia rapido para executar

Este guia explica o fluxo completo para quem ainda esta se familiarizando com Docker.

### 1. O que o projeto faz

O projeto consulta o Google Ad Manager, agrega as metricas e salva em duas colecoes do MongoDB:

- `DomRevenueByDomain`: receita agrupada por dominio;
- `DomRevenueByUtmCampaign`: receita agrupada por dominio e campanha UTM.

Os relatorios podem ser executados para `hoje`, `ontem`, `ultimos 7 dias` e `mês todo`.

### 2. Configuracao inicial

Instale o Docker Desktop (Mac/Windows) ou Docker Engine (Linux) e clone o repositorio:

```bash
git clone git@github.com:AndersonD4vid/dom-sync-gam.git
cd dom-sync-gam
```

Crie o arquivo de ambiente:

```bash
cp .env.example .env
```

Configure no `.env` as variaveis do MongoDB. O projeto monta a URI a partir destas chaves:

```env
MONGO_HOST=seu-host
MONGO_PORT=27017
MONGO_DB=seu-banco
MONGO_USER=seu-usuario
MONGO_PASSWORD=sua-senha
MONGO_AUTH_SOURCE=seu-banco
MONGO_REPLICA_SET=rs0
MONGO_TLS=false
MONGO_DIRECT_CONNECTION=false
```

Configure tambem o caminho da Service Account:

```env
GAM_KEY_FILE=credentials/service-account-key.json
```

Coloque o JSON fornecido pelo Google em:

```text
credentials/service-account-key.json
```

Esse arquivo e o `.env` contem segredos e nao devem ser commitados. Eles ja estao protegidos pelo `.gitignore`.

A Service Account precisa ter permissao de leitura e execucao de relatorios em cada network GAM cadastrada em `config/networks.py`. Se aparecer `NO_NETWORKS_TO_ACCESS`, a credencial nao tem acesso aquela network.

### 3. Rodar localmente com Docker

Construa a imagem para a plataforma da VPS. Em um Mac Apple Silicon, use `linux/amd64`:

```bash
docker build --platform linux/amd64 \
  -t ghcr.io/andersond4vid/dom-sync-gam:latest .
```

Inicie o container. O comando `tail -f /dev/null` mantem o container ativo para que os relatorios sejam executados com `docker exec`:

```bash
docker rm -f dom-sync 2>/dev/null || true

docker run -d \
  --name dom-sync \
  --restart unless-stopped \
  --env-file .env \
  -v "$PWD/credentials/service-account-key.json:/app/credentials/service-account-key.json:ro" \
  ghcr.io/andersond4vid/dom-sync-gam:latest \
  tail -f /dev/null
```

Confirme se esta ativo:

```bash
docker ps
docker exec dom-sync grep -n Bloogao /app/config/networks.py
```

### 4. Popular o banco

Execute um relatorio por vez e aguarde o relatorio final antes do proximo.

Dominios de hoje:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type domain --day today --workers 2
```

Dominios de ontem:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type domain --day yesterday --workers 2
```

Dominios dos ultimos 7 dias:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type domain --day last_7_days --workers 2
```

Campanhas UTM de hoje:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type utm_campaign --day today --workers 2
```

Campanhas UTM de ontem:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type utm_campaign --day yesterday --workers 2
```

Campanhas UTM dos ultimos 7 dias:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type utm_campaign --day last_7_days --workers 2
```

Para testar somente uma network:

```bash
docker exec dom-sync python soap_multiprocess.py \
  --run --type domain --day last_7_days \
  --network 21670997783 --workers 1 --debug
```

Importante: `Sucesso: 3` significa que tres jobs foram aceitos pelo GAM. Isso nao significa necessariamente que tres documentos foram gravados. Se o relatorio nao retornar linhas, nada sera inserido. Verifique tambem os logs:

```bash
docker exec dom-sync tail -n 100 /app/dom_processing.log
```

### 5. Publicar a imagem no GHCR

O `git push` nao constroi uma imagem automaticamente neste repositorio. Depois de alterar o codigo, o fluxo e:

```bash
git status
git add arquivo-alterado
git commit -m "descreve a alteracao"
git push origin main
```

Depois construa uma nova imagem:

```bash
docker build --platform linux/amd64 \
  -t ghcr.io/andersond4vid/dom-sync-gam:latest .
```

Autentique no GHCR, caso ainda nao esteja autenticado:

```bash
docker login ghcr.io
```

Publique:

```bash
docker push ghcr.io/andersond4vid/dom-sync-gam:latest
```

Nunca publique uma imagem contendo `.env`, senha do MongoDB ou a Service Account. Prefira passar o `.env` com `--env-file` e montar o JSON com `-v`, como no exemplo acima. Antes de publicar, confirme que os segredos nao estao sendo copiados para a imagem pelo `Dockerfile`.

### 6. Atualizar a VPS

Na VPS, baixar a imagem nao atualiza um container que ja esta rodando. Depois do `docker push`, execute:

```bash
docker pull ghcr.io/andersond4vid/dom-sync-gam:latest

docker rm -f dom-sync 2>/dev/null || true

docker run -d \
  --name dom-sync \
  --restart unless-stopped \
  --env-file .env \
  -v /caminho/na/vps/service-account-key.json:/app/credentials/service-account-key.json:ro \
  ghcr.io/andersond4vid/dom-sync-gam:latest \
  tail -f /dev/null
```

Substitua os caminhos pelos arquivos existentes na VPS. Confirme a versao implantada:

```bash
docker ps
docker exec dom-sync grep -n Bloogao /app/config/networks.py
```

Em seguida, execute os comandos de populacao da secao anterior.

### 7. O que fazer depois de qualquer alteracao

Para alteracoes em `config/`, `services/`, `repositories/`, `core/` ou qualquer outro codigo que vai rodar na VPS:

1. Teste localmente.
2. Faça `git add`, `git commit` e `git push`.
3. Construa novamente a imagem Docker.
4. Publique a nova imagem no GHCR.
5. Na VPS, execute `docker pull`.
6. Recrie o container, porque containers existentes nao trocam de imagem sozinhos.
7. Execute o relatorio desejado e confira os logs e o MongoDB.

Se a alteracao for somente em um arquivo de configuracao que esta dentro da imagem, tambem e necessario reconstruir e publicar a imagem. O `docker pull` so baixa a nova versao; ele nao reinicia nem recria o container automaticamente.

### 8. Execucao local sem Docker

Para depurar mais rapidamente no Mac, tambem e possivel executar com Python:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
GAM_KEY_FILE="$PWD/credentials/service-account-key.json" \
.venv/bin/python soap_multiprocess.py \
  --run --type domain --day last_7_days --workers 2
```

Nesse modo, o Redis precisa estar disponivel localmente e o `.env` continua apontando para o banco configurado.

## Tabela de comandos rapidos

Os comandos abaixo consideram que o container se chama `dom-sync` e esta ativo.

### Popular o MongoDB

| Periodo        | Dominios (`DomRevenueByDomain`)                                                                                                            | Campanhas UTM (`DomRevenueByUtmCampaign`)                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Hoje           | `docker exec dom-sync python soap_multiprocess.py --run --type domain --day today --workers 2`                                             | `docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign --day today --workers 2`                                             |
| Ontem          | `docker exec dom-sync python soap_multiprocess.py --run --type domain --day yesterday --workers 2`                                         | `docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign --day yesterday --workers 2`                                         |
| Ultimos 7 dias | `docker exec dom-sync python soap_multiprocess.py --run --type domain --day last_7_days --workers 2`                                       | `docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign --day last_7_days --workers 2`                                       |
| Mes atual      | `D=$(date +%d \| sed 's/^0//'); docker exec dom-sync python soap_multiprocess.py --run --type domain --day last_$((D-1))_days --workers 2` | `D=$(date +%d \| sed 's/^0//'); docker exec dom-sync python soap_multiprocess.py --run --type utm_campaign --day last_$((D-1))_days --workers 2` |

O comando de `Mes atual` calcula automaticamente o periodo do primeiro dia do mes ate hoje. Execute um comando por vez e aguarde o relatorio final.

Para executar somente uma network, acrescente, por exemplo:

```bash
--network 21670997783
```

### Docker e GHCR

| Objetivo                         | Comando |
| -------------------------------- | --- |
| Iniciar o container local        | `docker rm -f dom-sync 2>/dev/null`<br>`docker run -d --name dom-sync --env-file .env -v "$PWD/credentials/service-account-key.json:/app/credentials/service-account-key.json:ro" dom-sync-gam:local tail -f /dev/null` |
| Construir a imagem local         | `docker build --platform linux/amd64 -t dom-sync-gam:local .`             |
| Criar/taguear imagem para o GHCR | `docker tag dom-sync-gam:local ghcr.io/andersond4vid/dom-sync-gam:latest` |
| Autenticar no GHCR               | `docker login ghcr.io`                                                    |
| Subir a imagem para o GHCR       | `docker push ghcr.io/andersond4vid/dom-sync-gam:latest`                   |
| Baixar a imagem na VPS           | `docker pull ghcr.io/andersond4vid/dom-sync-gam:latest`                   |

O `docker push` so deve ser feito depois de validar a imagem localmente. O `.env` e o `service-account-key.json` devem continuar fora da imagem e ser fornecidos em runtime.

### Atalhos locais com Make

Para nao precisar memorizar os comandos longos, use o `Makefile` na raiz do projeto. Primeiro, inicie o ambiente:

```bash
make up prod
```

O ambiente deve ser informado sempre como o ultimo argumento: `prod` usa o `.env` e `dev` usa o `.env.development`. Se o ambiente nao for informado, os atalhos que dependem do container serao rejeitados.

Depois, use estes atalhos:

| Acao | Comando curto |
| --- | --- |
| Dominios de hoje | `make domain-today prod` |
| Dominios de ontem | `make domain-yesterday prod` |
| Dominios dos ultimos 7 dias | `make domain-7d prod` |
| Dominios do mes atual | `make domain-month prod` |
| UTMs de hoje | `make utm-today prod` |
| UTMs de ontem | `make utm-yesterday prod` |
| UTMs dos ultimos 7 dias | `make utm-7d prod` |
| UTMs do mes atual | `make utm-month prod` |
| Dominios e UTMs dos ultimos 7 dias | `make all-7d prod` |
| Verificar container | `make ps prod` |
| Ver logs | `make logs prod` |
| Parar/remover container | `make down prod` |

Para desenvolvimento, substitua o sufixo `prod` por `dev`, por exemplo: `make up dev` e `make domain-today dev`. O comando `make up prod` ou `make up dev` sempre reconstrói a imagem local antes de iniciar o container, garantindo que as alteracoes recentes do codigo estejam presentes. Para executar somente uma network, continue usando o comando completo com `--network` ou crie um atalho especifico no Makefile.

## Status das sincronizacoes

Cada execucao atualiza a colecao `DomSyncUpdateStatus`. Ela possui um documento com `_id` automatico do MongoDB para cada combinacao de:

```text
source_collection + period_key + network
```

As colecoes monitoradas sao `DomRevenueByDomain` e `DomRevenueByUtmCampaign`. O documento registra o codigo (`network`) e o nome (`network_name`) da network, o periodo real (`period_start` e `period_end`), o ultimo inicio de tentativa, o ultimo sucesso, a ultima gravacao de dados, a quantidade de registros e o erro da network, quando houver.

Os status possiveis sao `running`, `success`, `partial`, `no_data`, `auth_error` e `error`. Uma execucao sem dados nao atualiza `last_data_update_at`; assim, esse campo pode ser usado para identificar uma sincronizacao parada ou sem dados recentes.

## Arquitetura

O projeto segue uma arquitetura em camadas com os seguintes design patterns:

| Pattern           | Onde                                               | Proposito                                                 |
| ----------------- | -------------------------------------------------- | --------------------------------------------------------- |
| **Repository**    | `repositories/`                                    | Abstrai acesso ao MongoDB com QueryBuilder fluent         |
| **Service Layer** | `services/`                                        | Logica de negocio (extracao, processamento, orquestracao) |
| **DTO**           | `DTO/`                                             | Transporte de dados tipado entre camadas                  |
| **Singleton**     | `ConfigSingleton`, `MongoDB`, `NetworkRateLimiter` | Instancia unica para config, conexao e rate limiter       |
| **Worker Pool**   | `core/multiprocess/`                               | ThreadPoolExecutor com job manager por network            |

### Fluxo do Pipeline

```
CLI (soap_multiprocess.py)
  |
  +-> NetworkJobManager (distribui jobs por network)
  |     |
  |     +-> NetworkWorker (1 worker por thread)
  |           |
  |           +-> NetworkRateLimiter.wait_if_needed()
  |           +-> dom_report_runner.run()
  |                 |
  |                 +-> GamService (SOAP API) -----> Google Ad Manager
  |                 +-> MetricsReportService (agrega total + adx)
  |                 +-> MetricsProcessor (bulk upsert) -----> MongoDB
  |
  +-> progress.py (dashboard tempo real via tqdm)
```

## Estrutura do Projeto

```
DOM/
├── soap_multiprocess.py          # Entrypoint CLI
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.py               # ConfigSingleton (.env)
│   ├── networks.py               # Registry de networks GAM
│   ├── mongodb.py                # Conexao MongoDB (pool)
│   └── logging_config.py
├── core/
│   ├── auth.py
│   └── multiprocess/
│       ├── config.py             # Argparse (CLI flags)
│       ├── worker.py             # NetworkWorker (retry + rate limit)
│       ├── progress.py           # Dashboard e relatorio final
│       └── logging_config.py
├── services/
│   ├── gam_service.py            # Cliente SOAP GAM (v202602)
│   ├── dom_report_runner.py      # Orquestrador extract -> process -> persist
│   ├── metric_report_service.py  # Agregacao de metricas (total + adx)
│   └── process_metrics.py        # Bulk processor (chunks de 200)
├── repositories/
│   ├── base_repository.py        # QueryBuilder + BaseRepository
│   ├── revenue_domain_repository.py
│   └── revenue_utm_repository.py
├── DTO/
│   └── metric_data_dto.py        # MetricDataDTO (dataclass)
├── helpers/
│   └── jsonfy.py                 # CSV GAM -> JSON (header mapping + conversao)
├── utils/
│   ├── network_rate_limiter.py   # Rate limiter por network (sliding window)
│   ├── network_job_manager.py    # Gerenciador de jobs (1 network por vez por worker)
│   └── retry_handler.py          # Decorator exponential backoff
└── client/
    └── redis.py
```

## Setup

### 1. Ambiente

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Variaveis de Ambiente

Copie `.env.example` para `.env` e configure:

```bash
cp .env.example .env
```

| Variavel         | Descricao                                     | Default     |
| ---------------- | --------------------------------------------- | ----------- |
| `GAM_KEY_FILE`   | Caminho para o JSON da service account Google | -           |
| `JOINADS_API_URL`   | URL base da API de clientes da JoinAds     | `https://office.joinads.me` |
| `JOINADS_API_TOKEN` | Token do cliente na API JoinAds (so `source: joinads_api`) | -           |
| `MONGO_HOST`     | Host do cluster MongoDB (SRV)                 | `localhost` |
| `MONGO_PORT`     | Porta MongoDB                                 | `27017`     |
| `MONGO_DB`       | Nome do banco                                 | `admanager` |
| `MONGO_USER`     | Usuario MongoDB                               | `joinads`   |
| `MONGO_PASSWORD` | Senha MongoDB                                 | `joinads`   |
| `REDIS_HOST`     | Host Redis                                    | `localhost` |
| `REDIS_PORT`     | Porta Redis                                   | `6379`      |
| `REDIS_DB`       | DB Redis                                      | `0`         |
| `REDIS_PASSWORD` | Senha Redis                                   | -           |

### 3. Credenciais Google Ad Manager

O projeto usa autenticacao via **Service Account** (OAuth2). O arquivo JSON da service account deve estar no caminho configurado em `GAM_KEY_FILE`. A service account precisa ter acesso de leitura nas networks configuradas.

### 4. Configuracao de Networks

Edite `config/networks.py` para registrar as networks GAM:

```python
NETWORKS = [
    {
        "network_code": "1234567",
        "name": "Minha Network",
        "enabled": True,       # False para desabilitar sem remover
    },
    # ...
]
```

| Campo          | Tipo   | Descricao                                      |
| -------------- | ------ | ---------------------------------------------- |
| `network_code` | `str`  | Codigo da network no GAM                       |
| `name`         | `str`  | Nome descritivo                                |
| `enabled`      | `bool` | Se `False`, a network e ignorada pelo pipeline |

Campos opcionais para a network MCM "Manage Inventory" (MI), cujos dados vem da API de clientes da JoinAds (`office.joinads.me`) em vez do GAM:

| Campo             | Tipo        | Descricao                                                                                                      |
| ----------------- | ----------- | -------------------------------------------------------------------------------------------------------------- |
| `source`          | `str`       | `"gam"` (default, quando ausente) ou `"joinads_api"`                                                           |
| `joinads_network` | `str`       | So ficam as linhas da API com `network` igual a este valor (evita contar duas vezes dominios de outras networks) |
| `domains`         | `list[str]` | Opcional. Allowlist de dominios (exata, sem diferenciar maiusculas, tolera `www.`); um request por dia e dominio. Sem ela, um request por dia e o escopo e o do token: dominios do usuario e dos usuarios filhos no office |
| `revenue_field`   | `str`       | `"revenue"` (bruto) ou `"revenue_client"` (liquido do revshare); no UTM vira `earnings` / `earnings_client`    |

Alternativa via GAM: com `parent_network_code` (e sem `source`), o relatorio roda na network pai com a dimensao `CHILD_NETWORK_CODE` e so as linhas da filha (`network_code`) sao mantidas; `source`, `joinads_network` e `revenue_field` nao se aplicam. Se `source: "joinads_api"` e `parent_network_code` aparecerem juntos, o pai e ignorado.

Os dados sao sempre gravados com o `network_code` da entrada. Com `source: "joinads_api"` o GAM nao e chamado; sem `JOINADS_API_TOKEN` a execucao termina como `auth_error`, sem nenhuma chamada HTTP.

O relatorio UTM depende de a API do office aceitar o parametro `network` no `key-value` (a network e filtrada no servidor); habilite a entrada so apos esse deploy.

Impressoes e cliques vindos da API sao os mesmos do GAM. A receita chega arredondada em centavos por linha na origem (dia, ad unit e pais), entao o total pode ficar alguns centavos abaixo do que o GAM daria para o mesmo periodo, principalmente no UTM.

Funcoes disponiveis:

- `get_enabled_networks()` - Retorna apenas networks com `enabled=True`
- `get_network_by_code(code)` - Busca network pelo codigo

## Collections MongoDB

### `DomRevenueByDomain`

Armazena metricas agregadas por dominio.

| Campo         | Tipo       | Descricao                 |
| ------------- | ---------- | ------------------------- |
| `domain`      | `string`   | Nome do ad unit (dominio) |
| `network`     | `string`   | Codigo da network GAM     |
| `date`        | `string`   | Data do relatorio         |
| `impressions` | `int`      | Impressoes total + adx    |
| `clicks`      | `int`      | Cliques total + adx       |
| `ctr`         | `float`    | CTR calculado (%)         |
| `ecpm`        | `float`    | eCPM calculado (USD)      |
| `revenue`     | `float`    | Receita total + adx (USD) |
| `created_at`  | `datetime` | Timestamp de criacao      |
| `updated_at`  | `datetime` | Timestamp de atualizacao  |

**Indice unico:** `(domain, network, date)`

### `DomRevenueByUtmCampaign`

Armazena metricas agregadas por UTM campaign.

| Campo          | Tipo       | Descricao                         |
| -------------- | ---------- | --------------------------------- |
| `domain`       | `string`   | Nome do ad unit (dominio)         |
| `network`      | `string`   | Codigo da network GAM             |
| `utm_campaign` | `string`   | Valor do key-value `utm_campaign` |
| `date`         | `string`   | Data do relatorio                 |
| `impressions`  | `int`      | Impressoes total + adx            |
| `clicks`       | `int`      | Cliques total + adx               |
| `ctr`          | `float`    | CTR calculado (%)                 |
| `ecpm`         | `float`    | eCPM calculado (USD)              |
| `revenue`      | `float`    | Receita total + adx (USD)         |
| `created_at`   | `datetime` | Timestamp de criacao              |
| `updated_at`   | `datetime` | Timestamp de atualizacao          |

**Indice unico:** `(domain, network, utm_campaign, date)`

Ambas as collections usam **upsert** -- se o documento ja existe (pela chave unica), ele e atualizado. Caso contrario, e inserido.

## CLI

### Flags

| Flag        | Tipo                       | Default       | Descricao                                          |
| ----------- | -------------------------- | ------------- | -------------------------------------------------- |
| `--type`    | `domain` \| `utm_campaign` | -             | Tipo de relatorio                                  |
| `--day`     | `string`                   | -             | Periodo do relatorio                               |
| `--run`     | flag                       | `False`       | Executa o processamento (sem flag = modo listagem) |
| `--workers` | `int`                      | `cpu_count()` | Numero de threads concorrentes                     |
| `--limit`   | `int`                      | -             | Limita quantidade de networks processadas          |
| `--network` | `string`                   | -             | Processa apenas uma network especifica             |
| `--debug`   | flag                       | `False`       | Logging em modo debug                              |

### Valores de `--day`

| Valor          | Periodo                                       |
| -------------- | --------------------------------------------- |
| `today`        | Dia atual                                     |
| `yesterday`    | Dia anterior                                  |
| `last_7_days`  | Ultimos 7 dias                                |
| `last_30_days` | Ultimos 30 dias                               |
| `last_X_days`  | Ultimos X dias (dinamico, ex: `last_90_days`) |

### Exemplos

```bash
# Listar networks habilitadas (modo listagem, sem --run)
python soap_multiprocess.py

# Executar revenue by domain dos ultimos 7 dias
python soap_multiprocess.py --type domain --day last_7_days --run

# Executar revenue by utm_campaign de ontem
python soap_multiprocess.py --type utm_campaign --day yesterday --run

# Executar apenas uma network especifica
python soap_multiprocess.py --type domain --day last_30_days --run --network 1234567

# Limitar a 5 networks com 4 workers e debug
python soap_multiprocess.py --type domain --day yesterday --run --limit 5 --workers 4 --debug

# Periodo dinamico: ultimos 90 dias
python soap_multiprocess.py --type domain --day last_90_days --run
```

## Pipeline de Sincronizacao

O pipeline executa 4 etapas sequenciais para cada network:

### 1. Extract (GamService)

- Autentica via Service Account OAuth2
- Monta a query SOAP com dimensoes e colunas
- Submete o report job e faz polling ate `COMPLETED`
- Baixa o CSV comprimido (gzip), descompacta e converte para JSON
- Valores monetarios vem em micro-unidades (divididos por 1.000.000)
- Valores mapeados via `helpers/jsonfy.py` (header mapping do CSV GAM)

### 2. Process (MetricsReportService)

- Filtra dominios invalidos (`-`, `(not set)`, vazio)
- Agrega metricas **total + adx** (impressoes, cliques, receita)
- Calcula CTR: `(clicks / impressions) * 100`
- Calcula eCPM: `(revenue / impressions) * 1000`
- Para UTM: filtra apenas registros com `custom_key == 'utm_campaign'`
- Serializa via `MetricDataDTO`

### 3. Persist (MetricsProcessor)

- Processa em chunks de **200 documentos**
- Usa `bulk_write` com operacoes `UpdateOne` + `upsert=True`
- Chave de deduplicacao: `(domain, network, date)` ou `(domain, network, utm_campaign, date)`
- Retorna estatisticas: `matched`, `modified`, `upserted`

### 4. Report (Progress)

- Dashboard em tempo real via `tqdm`
- Contadores: sucesso, erro, erro de autenticacao, rate limit
- Relatorio final com tempo total, taxa de sucesso e req/s

## Rate Limiting

O sistema implementa rate limiting em duas camadas:

### Camada 1: NetworkRateLimiter (preventivo)

- **Singleton** thread-safe com lock por network
- **Sliding window**: rastreia timestamps de requisicoes no ultimo segundo
- Limite configuravel (default: 2 req/s por network na instancia singleton, 30 req/s global no main)
- Bloqueia a thread com `time.sleep()` quando o limite e atingido

### Camada 2: Exponential Backoff (reativo)

Quando a API retorna HTTP 429 ou `Resource has been exhausted`:

| Parametro            | Valor                       |
| -------------------- | --------------------------- |
| Max retries          | 10                          |
| Delay inicial        | 10 segundos                 |
| Delay maximo         | 120 segundos                |
| Fator de crescimento | 2x (exponencial)            |
| Jitter               | 20% (evita thundering herd) |

Formula do delay: `min(initial_delay * 2^attempt, max_delay) * (1 + 0.2 * jitter)`

### NetworkJobManager

Garante que **apenas 1 worker processa uma network por vez**. Isso evita requisicoes paralelas na mesma network que estourariam o rate limit da API GAM.

- Jobs agrupados por `network_code`
- Worker pega a proxima network disponivel (nao ativa, nao completa)
- Apos processar todos os jobs de uma network, marca como completa

## Error Handling

| Tipo de Erro                                | Tratamento                                          | Status                     |
| ------------------------------------------- | --------------------------------------------------- | -------------------------- |
| `AuthenticationError.NO_NETWORKS_TO_ACCESS` | Retorna `False`, pula network                       | `auth_error`               |
| `Unauthorized` / `PermissionDenied`         | Captura no worker, registra no dashboard            | `auth_error`               |
| HTTP 429 / Rate limit                       | Exponential backoff com ate 10 retries              | `rate_limit` (se esgotado) |
| Erro SOAP generico                          | Retry no `_report_service` (5 tentativas, delay 1s) | `error`                    |
| Erro de bulk write                          | Logado, chunk inteiro contado como erro             | `error`                    |
| `KeyboardInterrupt`                         | Encerra graciosamente com `sys.exit(1)`             | -                          |
| Erro fatal                                  | Imprime traceback se `--debug`, `sys.exit(1)`       | -                          |

## Conexao MongoDB

| Parametro                | Valor                  |
| ------------------------ | ---------------------- |
| Protocolo                | `mongodb+srv://` (TLS) |
| Max pool size            | 100                    |
| Min pool size            | 10                     |
| Connect timeout          | 5000ms                 |
| Server selection timeout | 5000ms                 |
| TLS                      | Habilitado             |

## Testes

O projeto possui **338 testes** com **99% de cobertura** de codigo. Todas as dependencias externas (MongoDB, Redis, Google Ad Manager SOAP API) sao mockadas via `unittest.mock`.

### Dependencias de Teste

```bash
pip install -r requirements-test.txt
```

| Pacote           | Uso                    |
| ---------------- | ---------------------- |
| `pytest`         | Framework de testes    |
| `pytest-cov`     | Relatorio de cobertura |
| `pytest-mock`    | Fixtures de mock       |
| `pytest-timeout` | Timeout por teste      |
| `freezegun`      | Mock de datas/horarios |

### Execucao

```bash
# Rodar todos os testes
pytest tests/

# Rodar com relatorio de cobertura
pytest tests/ --cov=. --cov-report=term-missing

# Rodar apenas uma categoria (markers: unit, integration, slow)
pytest tests/ -m unit
```

### Estrutura dos Testes

A estrutura de `tests/` espelha a estrutura do codigo-fonte:

```
tests/
├── conftest.py                  # Fixtures compartilhadas
├── test_soap_multiprocess.py    # Testes do entrypoint CLI
├── test_jsonfy.py               # Testes do helper JSON
├── test_metric_data_dto.py      # Testes do DTO
├── client/                      # Testes do cliente Redis
├── config/                      # Testes de configuracao
├── core/                        # Testes do worker, progress, multiprocess
├── repositories/                # Testes dos repositorios MongoDB
├── services/                    # Testes dos servicos (GAM, metricas, processor)
└── utils/                       # Testes de rate limiter, job manager, retry
```

### Cobertura

| Modulo                 | Cobertura |
| ---------------------- | --------- |
| `config/`              | 100%      |
| `core/multiprocess/`   | 100%      |
| `services/`            | 100%      |
| `repositories/`        | 100%      |
| `DTO/`                 | 100%      |
| `helpers/`             | 100%      |
| `utils/`               | 100%      |
| `client/`              | 100%      |
| `worker.py`            | 98%       |
| `soap_multiprocess.py` | 97%       |
| **Total**              | **99%**   |

## Dependencias Principais

| Pacote          | Versao | Uso                                     |
| --------------- | ------ | --------------------------------------- |
| `googleads`     | 48.0.0 | Cliente SOAP para Google Ad Manager     |
| `google-auth`   | 2.40.1 | Autenticacao OAuth2 Service Account     |
| `pymongo`       | 4.12.1 | Driver MongoDB                          |
| `redis`         | 5.3.0  | Cliente Redis                           |
| `python-dotenv` | 1.1.0  | Carregamento de `.env`                  |
| `tqdm`          | 4.67.1 | Barra de progresso                      |
| `zeep`          | 4.3.1  | Cliente SOAP (dependencia do googleads) |
| `lxml`          | 5.4.0  | Parser XML                              |
