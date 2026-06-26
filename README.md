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
# Install Docker and Git
sudo apt update && sudo apt install -y docker.io git

# Add your user to the docker group
sudo usermod -aG docker $USER
newgrp docker
```

`docker-compose-plugin` is not available in the default Ubuntu repos on Ubuntu 24+/26. Install the Compose V2 plugin manually:

```bash
DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
mkdir -p $DOCKER_CONFIG/cli-plugins

curl -SL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
  -o $DOCKER_CONFIG/cli-plugins/docker-compose

chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose

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

The worker container requires access to the MXF source files and the proxy output directory on the SAN/NAS. The share is mounted via SMB (CIFS).

```bash
# Install SMB client
sudo apt install -y cifs-utils

# Create mount point
sudo mkdir -p /mnt/arquivo

# Test mount first (replace <nas-ip> and <share> with your values)
sudo mount -t cifs //<nas-ip>/<share> /mnt/arquivo \
  -o username=<user>,password=<pass>,uid=$(id -u),gid=$(id -g),vers=2.0

# Verify expected directory structure
ls /mnt/arquivo/{FINALIZADOS,INSERCOES,BRUTOS,EDITADOS,ACERVO,PROXY}

# Unmount after test (cd out of the directory first)
cd ~
sudo umount /mnt/arquivo
```

**Make it persistent via `/etc/fstab`:**

```bash
# Store credentials securely
sudo nano /etc/samba/credentials_arquivo
```

```
username=<user>
password=<pass>
```

```bash
sudo chmod 600 /etc/samba/credentials_arquivo

# Add to /etc/fstab (replace <nas-ip> and <share>)
echo "//<nas-ip>/<share>  /mnt/arquivo  cifs  credentials=/etc/samba/credentials_arquivo,uid=$(id -u),gid=$(id -g),vers=2.0,_netdev,nofail  0  0" | sudo tee -a /etc/fstab

# Apply and verify
sudo mount -a
ls /mnt/arquivo
```

> **Note:** If `vers=2.0` fails with error 95, try `vers=2.1` or `vers=3.0`. Run `dmesg | tail -20` to see the exact rejection reason.

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
