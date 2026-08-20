# Teste 1

# DOM - Data Orchestrator for Metrics

Pipeline de sincronizacao de metricas do **Google Ad Manager (GAM)** para MongoDB. Extrai relatorios de receita por dominio e UTM campaign via SOAP API, processa as metricas e persiste em bulk no MongoDB.

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
