# ProxyGen TV Cultura

Automatic MXF-to-MP4 proxy generation system for **TV Cultura / Fundação Padre Anchieta**.

Reimplementation in Python of the legacy `StratusBaixaAlta` system (C# .NET WPF), operating 24/7 in a broadcast environment. Queries a legacy MAM via SOAP, locates MXF files on the SAN, encodes H.264/AAC MP4 proxies via FFmpeg, and reports status back to the MAM.

---

## Stack

| Component     | Technology                          |
|---------------|-------------------------------------|
| Backend API   | FastAPI (Python 3.11)               |
| Worker        | Python, ThreadPoolExecutor          |
| Database      | PostgreSQL 13 (SQLAlchemy ORM)      |
| MAM Integration | SOAP via `zeep` (WSDL)            |
| Encoder       | FFmpeg + ffprobe                    |
| Containers    | Docker Compose (3 services)         |
| Frontend      | Vanilla HTML/CSS/JS                 |

---

## Architecture

```
stratus-db      → PostgreSQL 13 (port 5432)
stratus-api     → FastAPI, port 8000 — web dashboard + REST API
stratus-worker  → processing loop + FFmpeg
```

Startup order enforced via healthchecks: `db` → `api` → `worker`

---

## Linux Deployment Tutorial

### Prerequisites

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git

# Add your user to the docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
docker compose version
```

---

### 1. Clone the repository

```bash
git clone https://github.com/devtvc/proxygen-tv-cultura.git
cd proxygen-tv-cultura
```

---

### 2. Configure environment variables

```bash
nano .env
```

Fill in `.env` with your environment values:

```env
# MAM SOAP endpoint
WSDL_URL=http://<mam-host>/mam080622/trf_services.asmx?WSDL
SERVIDOR=A                    # A or B — identifies this server in the MAM

# Host path to the NAS/SAN volume (Linux mount point)
HOST_VOLUME_PATH=/mnt/arquivo
CONTAINER_VOLUME_PATH=/mnt/arquivo

# Proxy output and MXF input directories (inside the container)
PROXY_DIR=/mnt/arquivo/PROXY
INPUT_DIR_P=/mnt/arquivo/FINALIZADOS
INPUT_DIR_I=/mnt/arquivo/INSERCOES
INPUT_DIR_B=/mnt/arquivo/BRUTOS
INPUT_DIR_E=/mnt/arquivo/EDITADOS
INPUT_DIR_A=/mnt/arquivo/ACERVO

# Database
POSTGRES_USER=broadcast
POSTGRES_PASSWORD=change_me
POSTGRES_DB=broadcast_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Worker
MAX_WORKERS=1
MAX_TENTATIVAS=3
WATCHDOG_GRACE=120

LOG_LEVEL=INFO
```

> **Never commit `.env` to version control.** It is listed in `.gitignore`.

---

### 3. Mount the media volume

The worker container requires access to the MXF source files and the proxy output directory on the SAN/NAS.

```bash
# Create mount point
sudo mkdir -p /mnt/arquivo

# NFS example
sudo mount -t nfs <nas-ip>:/arquivo /mnt/arquivo

# Make persistent — add to /etc/fstab
echo "<nas-ip>:/arquivo  /mnt/arquivo  nfs  defaults,_netdev  0  0" | sudo tee -a /etc/fstab

# Verify expected directory structure
ls /mnt/arquivo/{FINALIZADOS,INSERCOES,BRUTOS,EDITADOS,ACERVO,PROXY}
```

---

### 4. Deploy

```bash
docker compose up -d --build
```

Verify all three containers are running:

```bash
docker compose ps
```

Expected output:

```
NAME             STATUS          PORTS
stratus-db       Up (healthy)    5432/tcp
stratus-api      Up (healthy)    0.0.0.0:8000->8000/tcp
stratus-worker   Up
```

---

### 5. Access the dashboard

```
http://<server-ip>:8000
```

The dashboard polls every 3 seconds and displays:

- Active FFmpeg jobs with progress percentage
- Manual reprocessing queue
- Unified job history (local + MAM legacy errors)
- Per-media audit event log

---

### 6. Operational commands

```bash
# Live logs
docker compose logs -f worker
docker compose logs -f api

# Restart a single service
docker compose restart worker

# Rebuild and redeploy after code changes (no db restart needed)
docker compose up -d --build api worker

# Direct database access
docker exec -it stratus-db psql -U broadcast -d broadcast_db

# Useful queries
SELECT media_id, status, mensagem FROM jobs ORDER BY inicio DESC LIMIT 20;
SELECT media_id, status, tentativas FROM fila_manual ORDER BY id ASC;
SELECT media_id, titulo, tipo, status FROM medias ORDER BY atualizado_em DESC LIMIT 20;

# Fix orphaned jobs stuck after a crash
docker exec -it stratus-db psql -U broadcast -d broadcast_db -c \
  "UPDATE jobs SET status='Erro', fim=NOW() \
   WHERE status IN ('Iniciando','Processando') AND inicio < NOW() - INTERVAL '2 hours';"
```

---

### 7. Autostart on boot (systemd)

```bash
sudo nano /etc/systemd/system/proxygen.service
```

```ini
[Unit]
Description=ProxyGen TV Cultura
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/proxygen-tv-cultura
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

```bash
# Move project to a stable system path
sudo mv ~/proxygen-tv-cultura /opt/proxygen-tv-cultura

sudo systemctl daemon-reload
sudo systemctl enable proxygen
sudo systemctl start proxygen
```

---

### 8. Updating

```bash
cd /opt/proxygen-tv-cultura
git pull origin main
docker compose up -d --build api worker
```

> Database schema migrations run automatically on API startup via `_sync_schema()` — no manual migration step required.

---

## Environment Variables Reference

| Variable              | Default                    | Description                          |
|-----------------------|----------------------------|--------------------------------------|
| `WSDL_URL`            | —                          | MAM SOAP WSDL endpoint               |
| `SERVIDOR`            | `A`                        | Server identifier in the MAM (A/B)   |
| `MAX_WORKERS`         | `1`                        | Parallel FFmpeg threads              |
| `MAX_TENTATIVAS`      | `3`                        | Manual queue retry limit             |
| `WATCHDOG_GRACE`      | `120`                      | Seconds before watchdog frees a stuck slot |
| `PROXY_DIR`           | `/mnt/arquivo/PROXY`       | MP4 output directory                 |
| `INPUT_DIR_P/I/B/E/A` | `/mnt/arquivo/<type>`      | MXF input directories per media type |
| `HOST_VOLUME_PATH`    | `/mnt/arquivo`             | Host path mounted into the worker    |
| `POSTGRES_*`          | see `.env`                 | PostgreSQL connection settings       |

---

## REST API Endpoints

| Method | Endpoint                    | Description                                  |
|--------|-----------------------------|----------------------------------------------|
| GET    | `/`                         | Web dashboard                                |
| GET    | `/health`                   | Healthcheck                                  |
| GET    | `/api/stats`                | Worker stats (active, done, errors)          |
| GET    | `/api/jobs`                 | Active jobs (Iniciando / Processando)        |
| GET    | `/api/history`              | Unified history: local jobs + MAM legacy     |
| GET    | `/api/fila-manual`          | Manual reprocessing queue                    |
| POST   | `/api/fila-manual`          | Add media_id to manual queue                 |
| POST   | `/api/job/{id}/cancel`      | Cancel active job                            |
| POST   | `/api/job/{id}/retry`       | Send failed/cancelled job to manual queue    |
| POST   | `/api/job/{id}/force-retry` | Force reprocess (any status, via SOAP reset) |
| GET    | `/api/erros-legado`         | Live MAM legacy error list (SOAP proxy)      |
| GET    | `/api/media/{id}`           | Media details                                |
| GET    | `/api/media/{id}/events`    | Audit events for a media                     |
