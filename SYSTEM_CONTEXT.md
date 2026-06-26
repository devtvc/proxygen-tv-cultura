# ProxyGen TV Cultura — Contexto do Sistema

> Use este arquivo como contexto inicial para qualquer nova conversa sobre este projeto.
> Ele descreve a arquitetura, fluxo de dados, integrações e decisões técnicas relevantes.

---

## 1. Visão Geral

**ProxyGen TV Cultura** é um sistema de geração automática de proxies MP4 a partir de arquivos MXF para a **TV Cultura / Fundação Padre Anchieta**. É a reimplementação em Python de um sistema legado escrito em **C# .NET WPF** chamado `StratusBaixaAlta`.

O sistema opera **24/7** em ambiente de broadcast, consultando periodicamente um **MAM (Media Asset Management) legado via SOAP** para encontrar mídias pendentes de conversão e processá-las via FFmpeg.

---

## 2. Stack Tecnológica

| Componente    | Tecnologia                              |
|---------------|-----------------------------------------|
| Backend API   | FastAPI (Python 3.11)                   |
| Worker        | Python puro, ThreadPoolExecutor         |
| Banco de dados| PostgreSQL 13 (SQLAlchemy ORM)          |
| Integração MAM| SOAP via `zeep` (WSDL)                  |
| Encoder       | FFmpeg + ffprobe (subprocess)           |
| Containerização| Docker Compose (3 serviços)            |
| Frontend      | HTML/CSS/JS vanilla (sem framework)     |

---

## 3. Arquitetura de Containers

```
stratus-db      → PostgreSQL 13 (porta 5432)
stratus-api     → FastAPI, porta 8000 — dashboard web + API REST
stratus-worker  → loop de processamento + FFmpeg
```

**Dependências de inicialização:** `db` → `api` (healthcheck) → `worker`

Volume compartilhado: o worker monta `HOST_VOLUME_PATH` (ex: `/Volumes/arquivo$`) que contém os MXF de origem e o diretório de saída dos proxies.

---

## 4. Estrutura de Arquivos

```
/NEW BAIXAS/
├── docker-compose.yml
├── shared/
│   ├── models.py       # SQLAlchemy ORM: Media, Job, FilaManual, Event, Log
│   ├── database.py     # engine, SessionLocal, create_tables(), _sync_schema()
│   ├── schemas.py      # Pydantic: JobResponse, FilaManualResponse, StatsResponse
│   └── soap.py         # cliente zeep: proxima_media, reservar, marcar_*, listar_falhas_legado
├── api/
│   └── app.py          # FastAPI: endpoints REST + servir dashboard HTML
├── worker/
│   ├── worker.py       # loop principal, fila manual, slot tracking, watchdog
│   └── ffmpeg_worker.py# localizar MXF, obter duração, executar FFmpeg
├── templates/
│   └── index.html      # dashboard (HTML com CSS inline)
└── static/
    └── js/main.js      # frontend JS: polling 3s, renderização das tabelas
```

---

## 5. Banco de Dados — Modelos

### `medias`
| Coluna         | Tipo    | Descrição                                      |
|----------------|---------|------------------------------------------------|
| media_id       | String  | ID único da mídia (chave natural do MAM)       |
| titulo         | Text    | Título do programa (do MAM via SOAP)           |
| tipo           | String  | Código do tipo: P, I, B, E, A                  |
| duracao        | String  | Duração no formato HH:MM:SS.ms                 |
| arquivo_origem | Text    | Caminho do MXF                                 |
| arquivo_proxy  | Text    | Caminho do MP4 gerado                          |
| status         | String  | Pendente / Processando / Concluído / Erro      |
| token          | Integer | Token SOAP da mídia                            |

### `jobs`
| Coluna    | Tipo    | Descrição                                           |
|-----------|---------|-----------------------------------------------------|
| media_id  | String  | FK lógica para medias.media_id                      |
| status    | String  | Iniciando / Processando / Concluído / Erro / Cancelado |
| inicio    | DateTime| Momento em que o job foi criado                     |
| fim       | DateTime| Momento da conclusão/erro                           |
| percentual| Integer | Progresso FFmpeg (0–100)                            |
| worker    | String  | Identificador do worker (discovery-worker, manual-worker) |
| mensagem  | Text    | Última mensagem de status                           |

### `fila_manual`
| Coluna    | Tipo    | Descrição                                           |
|-----------|---------|-----------------------------------------------------|
| media_id  | String  | Media ID a ser reprocessado                         |
| status    | String  | Pendente / Aguardando / Processando / Concluído / Erro |
| tentativas| Integer | Nº de tentativas com falha transitória              |
| mensagem  | Text    | Mensagem de status atual                            |

### `eventos`
Log de auditoria por media_id (MEDIA_DESCOBERTA, RESERVADA, ENCODE_INICIADO, etc.)

---

## 6. Integração SOAP (MAM Legado)

**WSDL:** `http://172.20.15.190/mam080622/trf_services.asmx?WSDL`  
**Biblioteca:** `zeep` com cliente cacheado em singleton (`_client_instance`)

### Métodos SOAP utilizados

| Função Python         | Método SOAP                        | Descrição                                         |
|-----------------------|------------------------------------|---------------------------------------------------|
| `proxima_media()`     | `ProximaMedia()`                   | Retorna próxima mídia com `flag_Baixa='P'`        |
| `obter_cadastro(id)`  | `carrega_cadastro(id)`             | Retorna cadastro completo (TOKEN, CDG_STC, TITULO)|
| `reservar_servidor()` | `insere_Flag_SRVBAIXA(id, srv)`    | Reserva mídia para servidor A ou B               |
| `marcar_pendente()`   | `insere_Status_Baixa(flag='P')`    | Reset para Pendente (antes de refazer)            |
| `marcar_concluido()`  | `insere_Status_Baixa(flag='D')`    | Marca como concluído (Feito)                      |
| `marcar_erro()`       | `insere_Status_Baixa(flag='E')`    | Registra erro no MAM                             |
| `listar_falhas_legado()`| `PesquisarMediaBaixaAlta(tipo='F')`| Lista mídias com flag='E' (rápido, sem full-scan)|

> **Atenção:** `PesquisarMediaBaixa(tipo='E')` causa **timeout** — faz full-scan na tabela SQL Server. Usar **sempre** `PesquisarMediaBaixaAlta(tipo='F')` para listar falhas.

### Flags `flag_Baixa` no MAM
| Flag | Significado       |
|------|-------------------|
| P    | Pendente          |
| D    | Feito (concluído) |
| E    | Erro              |

---

## 7. Fluxo de Processamento Principal

### 7.1 Fluxo normal (SOAP polling)

```
worker.py (loop a cada ~5s)
    ↓
proxima_media()   → MAM retorna próxima mídia com flag='P'
    ↓
reservar_servidor() → insere_Flag_SRVBAIXA(id, 'A')
    ↓
cria/atualiza Media no PostgreSQL (status=Pendente)
cria Job (status=Iniciando)
    ↓
executor.submit(processar_media, ...)
    ↓  [em thread separada]
gerar_proxy()
    ├── localizar_arquivo() → busca MXF nos INPUT_DIRS por tipo
    ├── obter_duracao_segundos() → MAM first, ffprobe fallback
    ├── FFmpeg subprocess → H.264 + AAC → MP4
    │       progress_callback → atualiza job.percentual no DB
    └── marcar_concluido() → insere_Status_Baixa(flag='D')
    ↓
Job status=Concluído, Media status=Concluído
```

### 7.2 Fluxo fila manual (reprocessamento prioritário)

```
Usuário → dashboard → POST /api/fila-manual  (ou botão "Refazer")
    ↓
FilaManual inserida com status=Pendente
    ↓
worker.py (loop) detecta fila_manual pendente → PRIORIDADE sobre SOAP
    ↓
item → status=Aguardando (reservado para executor, ainda não codificando)
    ↓
executor.submit(processar_fila_manual, ...)
    ↓  [em thread separada]
item → status=Processando
obter_cadastro() → TOKEN + tipo/duracao
marcar_pendente() → reset SOAP para P
reservar_servidor() → insere_Flag_SRVBAIXA
    ↓
gerar_proxy() [mesmo fluxo acima]
    ↓
FilaManual status=Concluído, Job status=Concluído
```

---

## 8. Controle de Slots (Race Condition Prevention)

```python
medias_em_processamento = set()  # em memória, por worker process
slot_inicio = {}                  # dict media_id -> timestamp de reserva
```

- `reservar_slot(media_id)` → add ao set + registra timestamp
- `liberar_slot(media_id)` → remove do set + timestamp
- `watchdog_slots()` → libera slots reservados há mais de `WATCHDOG_GRACE` segundos sem job ativo no DB (evita deadlock por exceção entre reserva e submit)

**Variáveis de ambiente relevantes:**
- `MAX_WORKERS` — nº de threads FFmpeg paralelas (default: 1)
- `WATCHDOG_GRACE` — segundos antes do watchdog liberar slot travado (default: 120)
- `MAX_TENTATIVAS` — tentativas na fila manual antes de marcar Erro (default: 3)

---

## 9. Tipos de Mídia e Diretórios de Entrada

| Tipo | Código | Diretório padrão          |
|------|--------|---------------------------|
| P    | PROG   | `/Volumes/arquivo$/FINALIZADOS` |
| I    | INS    | `/Volumes/arquivo$/INSERCOES`   |
| B    | BRUTOS | `/Volumes/arquivo$/BRUTOS`      |
| E    | EDIT   | `/Volumes/arquivo$/EDITADOS`    |
| A    | ACERVO | `/Volumes/arquivo$/ACERVO`      |

> Mídias tipo B (BRUTOS) frequentemente têm `DURACAO=None` no MAM. O sistema usa **ffprobe** como fallback para obter a duração diretamente do arquivo MXF.

---

## 10. Schema de Migrações Sem Downtime

`_sync_schema()` em `shared/database.py` aplica DDL idempotente a cada startup:

```python
statements = [
    "ALTER TABLE fila_manual ADD COLUMN IF NOT EXISTS tentativas INTEGER DEFAULT 0",
    "ALTER TABLE medias ADD COLUMN IF NOT EXISTS titulo TEXT",
]
```

`create_all()` do SQLAlchemy não altera tabelas existentes, por isso este mecanismo cobre colunas novas em bancos já em produção.

---

## 11. API REST — Endpoints

| Método | Endpoint                       | Descrição                                              |
|--------|--------------------------------|--------------------------------------------------------|
| GET    | `/`                            | Dashboard HTML                                         |
| GET    | `/health`                      | Healthcheck                                            |
| GET    | `/api/stats`                   | Workers, ativos, concluídos, erros (local + legado)   |
| GET    | `/api/jobs`                    | Jobs ativos (Iniciando / Processando) enriquecidos     |
| GET    | `/api/history`                 | Histórico unificado: jobs locais + falhas MAM legado  |
| GET    | `/api/fila-manual`             | Fila de reprocessamento manual enriquecida             |
| POST   | `/api/fila-manual`             | Adiciona media_id à fila manual                        |
| POST   | `/api/job/{id}/cancel`         | Cancela job ativo                                      |
| POST   | `/api/job/{id}/retry`          | Envia mídia com Erro/Cancelado para fila manual        |
| POST   | `/api/job/{id}/force-retry`    | Força reprocessamento (qualquer status, via SOAP reset)|
| GET    | `/api/erros-legado`            | Lista falhas do MAM legado ao vivo (proxy SOAP)        |
| GET    | `/api/media/{id}`              | Detalhes de uma mídia                                  |
| GET    | `/api/media/{id}/events`       | Eventos de auditoria de uma mídia                      |

### Enriquecimento de dados (`_enrich_job`)
Jobs retornados pela API incluem `titulo`, `tipo` e `duracao` via JOIN com a tabela `medias`. Entradas do MAM legado no histórico têm `id=null` e badge "Legado" (roxo) no frontend.

---

## 12. Histórico Unificado

`GET /api/history` combina duas fontes sem duplicar:

1. **Jobs locais** — status Concluído / Erro / Cancelado no PostgreSQL
2. **Falhas MAM legado** — `PesquisarMediaBaixaAlta(tipo='F')` ao vivo via SOAP

Deduplicação por `media_id`: se o media_id já tem registro local, a entrada SOAP é ignorada.

`GET /api/stats` aplica a mesma lógica para o contador total de erros (`erros = erros_local + erros_legado_sem_duplicata`).

---

## 13. Dashboard Frontend

- **Polling:** `fetchAll()` a cada **3 segundos** (stats, fila, jobs ativos, histórico)
- **4 tabelas:** Fila de Reprocessamento, Em Reprocessamento, Jobs Ativos, Histórico Recente
- **Colunas em todas as tabelas:** Media ID, Título, Tipo, Duração, Status, Ações
- **Sem frameworks JS** — vanilla fetch + DOM manipulation
- **Toast notifications** para ações do usuário (adicionar, cancelar, refazer)

---

## 14. Variáveis de Ambiente

| Variável            | Default                                               | Descrição                        |
|---------------------|-------------------------------------------------------|----------------------------------|
| `POSTGRES_USER`     | broadcast                                             |                                  |
| `POSTGRES_PASSWORD` | pass123                                               |                                  |
| `POSTGRES_HOST`     | db                                                    |                                  |
| `POSTGRES_DB`       | broadcast_db                                          |                                  |
| `WSDL_URL`          | http://172.20.15.190/mam080622/trf_services.asmx?WSDL|                                  |
| `SERVIDOR`          | A                                                     | Identificador do servidor (A/B)  |
| `MAX_WORKERS`       | 1                                                     | Threads FFmpeg paralelas         |
| `MAX_TENTATIVAS`    | 3                                                     | Tentativas fila manual           |
| `WATCHDOG_GRACE`    | 120                                                   | Segundos até watchdog liberar slot|
| `PROXY_DIR`         | /Volumes/arquivo$/PROXY                               | Saída dos MP4                    |
| `INPUT_DIR_P/I/B/E/A` | /Volumes/arquivo$/\<tipo\>                          | Entrada dos MXF por tipo         |
| `HOST_VOLUME_PATH`  | /Volumes/arquivo$                                     | Volume montado no worker         |

---

## 15. Problemas Conhecidos e Soluções Aplicadas

| Problema                              | Causa                                                    | Solução                                               |
|---------------------------------------|----------------------------------------------------------|-------------------------------------------------------|
| Proxies ficam presos em "Processando" | Slot leak: `medias_em_processamento` nunca removido em exceção | try/except com `liberar_slot` + watchdog         |
| Jobs ficam presos em "Iniciando"      | Except do worker não atualizava o Job, só a FilaManual   | Except handler atualiza Job para "Erro" também        |
| `PesquisarMediaBaixa` timeout         | Full-scan no SQL Server para qualquer parâmetro          | Usar `PesquisarMediaBaixaAlta(tipo='F')` — indexado  |
| BRUTOS sem duração no MAM             | `carrega_cadastro` não retorna DURACAO para tipo B       | ffprobe fallback direto no arquivo MXF                |
| Duplicatas na fila manual             | Retry chamado múltiplas vezes                            | Check de existência com status Pendente/Aguardando    |

---

## 16. Comandos Operacionais

```bash
# Deploy completo
docker compose up -d --build

# Rebuild apenas api e worker (mudanças de código)
docker compose up -d --build api worker

# Logs em tempo real
docker compose logs -f worker
docker compose logs -f api

# Acesso direto ao banco
docker exec -it stratus-db psql -U broadcast -d broadcast_db

# Queries úteis
SELECT media_id, status, mensagem FROM jobs ORDER BY inicio DESC LIMIT 20;
SELECT media_id, status, tentativas FROM fila_manual ORDER BY id ASC;
SELECT media_id, titulo, tipo, status FROM medias ORDER BY atualizado_em DESC LIMIT 20;

# Corrigir jobs órfãos manualmente
UPDATE jobs SET status='Erro', fim=NOW() WHERE status IN ('Iniciando','Processando') AND inicio < NOW() - INTERVAL '2 hours';
UPDATE medias SET status='Erro', atualizado_em=NOW() WHERE media_id='<id>' AND status IN ('Iniciando','Processando');
```
