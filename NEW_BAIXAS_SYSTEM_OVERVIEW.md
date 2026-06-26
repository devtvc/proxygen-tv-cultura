# StratusBaixaAlta Python Reimplementation - System Overview

## Executive Summary
This document provides a comprehensive overview of the StratusBaixaAlta Python reimplementation, a broadcast media processing system designed for 24/7 television environments. The system processes media files through a workflow involving SOAP service integration, FFmpeg transcoding, and PostgreSQL-based monitoring.

## System Architecture

### High-Level Components
1. **FastAPI Backend** (`/api/`) - RESTful API with SQLAlchemy ORM
2. **Worker Process** (`/worker/`) - Media discovery and FFmpeg processing
3. **Shared Library** (`/shared/`) - Database models, SOAP client, schemas
4. **Frontend Dashboard** (`/templates/`) - HTML/JavaScript monitoring interface
5. **Infrastructure** - Docker-compose orchestration with PostgreSQL

### Key Architectural Principles
- **Containerization**: All services Dockerized for portability
- **Separation of Concerns**: Distinct layers for API, worker, data access
- **Database Persistence**: PostgreSQL as primary data store
- **SOAP Integration**: Legacy MAM service communication maintained
- **Concurrent Processing**: ThreadPoolExecutor for parallel FFmpeg jobs
- **Event Tracking**: Comprehensive audit trail of all operations

## Detailed Component Analysis

### 1. FastAPI Backend (`/api/app.py`)
**Responsibilities**:
- Exposes RESTful API endpoints for system interaction
- Manages database connections and transactions
- Implements business logic for job control (cancel, retry)
- Provides real-time statistics and historical data

**Key Endpoints**:
- `GET /` - Dashboard HTML interface
- `GET /api/jobs` - Active processing jobs
- `GET /api/history` - Job completion history
- `GET /api/stats` - System statistics (workers, active, completed, errors)
- `GET /api/media/{id}` - Detailed media information
- `POST /api/job/{id}/cancel` - Cancel active job
- `POST /api/job/{id}/retry` - Retry failed/cancelled job (ALREADY IMPLEMENTED)

### 2. Worker Process (`/worker/worker.py`)
**Responsibilities**:
- Main discovery loop polling SOAP service for media
- Thread management for concurrent FFmpeg processing
- Database synchronization for media, job, and event tracking
- Progress monitoring and error handling

**Core Functions**:
- `main()`: Discovery loop with worker slot management
- `processar_media()`: Individual media processing orchestrator
- `create_or_update_job()`: Job record management
- `update_media_status()`: Media state persistence
- `log_event()`: Audit trail creation

### 3. FFmpeg Processing (`/worker/ffmpeg_worker.py`)
**Responsibilities**:
- Independent FFmpeg execution with progress reporting
- Source file location and validation
- Progress callback integration for database updates
- SOAP status updates on completion/error

**Features**:
- Configurable FFmpeg parameters (scale=640:360, libx264, etc.)
- Real-time progress reporting via callback mechanism
- Error handling and cleanup
- SOAP integration for completion/error notifications

### 4. SOAP Integration (`/shared/soap.py`)
**Responsibilities**:
- Communication with legacy MAM SOAP service
- Global client caching for performance
- Standardized function interfaces for all SOAP operations

**Key Functions**:
- `obter_token(media_id)`: Retrieve authentication token
- `reservar_servidor(media_id)`: Reserve media for processing server
- `proxima_media()`: Get next media from SOAP queue
- `marcar_pendente(media_id, token)`: Set media to pending status
- `marcar_concluido(media_id, token)`: Set media to completed status
- `marcar_erro(media_id, token, erro)`: Set media to error status

### 5. Data Layer (`/shared/`)
#### Database Models (`models.py`)
- **Media Table**: Current state of each media item
  - `media_id` (unique): Media identifier
  - `tipo`: Media type (P/I/B/E/A)
  - `duracao`: Duration (HH:MM:SS)
  - `status`: Current state (Pendente/Processando/Concluído/Erro/Cancelado)
  - `token`: SOAP authentication token
  - Timestamps for creation/update

- **Job Table**: Individual processing attempts
  - `media_id` (indexed): Associated media
  - `status`: Job state (Iniciando/Processando/Concluído/Erro/Cancelado)
  - `inicio`/`fim`: Timestamps
  - `percentual`: Completion percentage (0-100)
  - `worker`: Processing identifier
  - `mensagem`: Status/error description

- **Event Table**: Audit trail
  - `media_id` (indexed): Associated media
  - `tipo_evento`: Event type
  - `descricao`: Detailed description
  - `data_hora`: Timestamp

- **Log Table**: Structured logging (available but unused)

#### Schemas (`schemas.py`)
Pydantic models for API request/response validation including:
- MediaBase/Response
- JobBase/Response  
- EventBase/Response
- StatsResponse
- JobCancelResponse

## Data Flow & Processing Lifecycle

### Normal Processing Flow
1. **Discovery**: Worker calls `proxima_media()` → gets media from SOAP
2. **Reservation**: Worker calls `reservar_servidor()` → reserves media for server A
3. **Database Init**: Creates Media("Pendente") and Job("Iniciando") records
4. **Event Logging**: Logs MEDIA_DESCOBERTA and RESERVADA events
5. **FFmpeg Start**: Worker executes `gerar_proxy()` with progress callback
6. **Progress Updates**: FFmpeg outputs → callback → database job updates
7. **Completion**: 
   - Success: Media→"Concluído", Job→"Concluído"(100%), `marcar_concluido()` SOAP call
   - Error: Media→"Erro", Job→"Erro"(0%), `marcar_erro()` SOAP call
   - Cancellation: Media→"Cancelado", Job→"Cancelado" (via API)
8. **Cleanup**: Worker removes from active processing set

### Retry Flow (ALREADY IMPLEMENTED)
1. **User Action**: Click "Refazer" button on dashboard for Error/Cancelled job
2. **API Call**: POST `/api/job/{media_id}/retry`
3. **Validation**: Checks media exists and status is Error/Cancelled
4. **SOAP Reset**: Calls `marcar_pendente()` to return media to SOAP queue
5. **DB Update**: Sets media status to "Pendente" for immediate UI reflection
6. **Event Log**: Creates RETRY_SOLICITADO audit entry
7. **Worker Pickup**: Next `proxima_media()` call returns the retried media
8. **Standard Processing**: Creates new Job("Iniciando") and processes normally

## Current Feature Status

### Implemented Features
✅ Concurrent FFmpeg processing (configurable workers)
✅ Job monitoring and progress tracking
✅ Error reporting and handling
✅ Job history maintenance
✅ **Retry functionality for failed/cancelled jobs** (complete implementation)
✅ SOAP service integration (discovery, reservation, status updates)
✅ Web dashboard with real-time updates
✅ Database persistence with SQLAlchemy ORM
✅ Docker-compose orchestration
✅ Event tracking and audit trail

### Architecture Compliance
The retry implementation maintains full compliance with all architectural requirements:
- Uses existing SOAP workflow (`marcar_pendente()`)
- Preserves reservation logic (worker still calls `reservar_servidor()`)
- Maintains FFmpeg workflow unchanged
- Preserves monitoring functionality (database tracking)
- Maintains database integrity (ACID transactions)
- Does not bypass required SOAP functions
- Proper error handling with rollback
- Only allows retry of appropriate statuses (Erro/Cancelado)

## Potential Improvement Areas

While the core retry functionality is complete, here are suggested enhancements that maintain architectural integrity:

### 1. Enhanced Retry Controls
- **Retry Limits**: Add configurable maximum retry attempts per media
- **Retry Delay**: Implement exponential backoff between retry attempts
- **Selective Retry**: Allow operators to choose specific processing stages to retry

### 2. Monitoring & Observability
- **Metrics Endpoint**: Add Prometheus-compatible `/metrics` endpoint
- **Health Checks**: Implement liveness/readiness probes for Kubernetes
- **Structured Logging**: Implement actual logging to the Log table
- **Performance Metrics**: Track FFmpeg processing times, SOAP latency

### 3. API Enhancements
- **Pagination**: Add limit/offset to `/api/jobs` and `/api/history` endpoints
- **Filtering**: Allow filtering by media type, date range, status
- **Bulk Operations**: Enable retry/cancel for multiple media items
- **WebSocket Support**: Replace polling with real-time updates

### 4. Database Improvements
- **Indexing**: Add composite indexes for common query patterns
- **Partitioning**: Consider time-based partitioning for large history tables
- **Archiving**: Implement old data archiving strategy
- **Connection Pooling**: Tune SQLAlchemy pool settings for production load

### 5. Worker Enhancements
- **Dynamic Scaling**: Allow runtime adjustment of MAX_WORKERS
- **Graceful Shutdown**: Improve shutdown handling for in-progress jobs
- **Health Monitoring**: Add worker heartbeat and status reporting
- **Fault Tolerance**: Implement checkpointing for long-running FFmpeg jobs

### 6. Frontend Improvements
- **Enhanced UI**: Add media type filtering, date range selectors
- **Detailed Views**: Show FFmpeg progress charts, SOAP interaction logs
- **Bulk Actions**: Select multiple jobs for retry/cancel operations
- **Export Capabilities**: Allow CSV/PDF export of job history

### 7. Security & Reliability
- **Input Validation**: Strengthen validation on all API inputs
- **Rate Limiting**: Implement API rate limiting to prevent abuse
- **Authentication**: Add basic auth or token-based API protection
- **Backup Strategies**: Implement automated database backup procedures
- **Circuit Breaker**: Add resilience patterns for SOAP service failures

## Deployment & Operations

### Current Deployment (docker-compose.yml)
- **PostgreSQL**: Official PostgreSQL 13 image with persistent volume
- **API Service**: FastAPI application with uvicorn
- **Worker Service**: Python worker with FFmpeg dependencies
- **Networking**: Internal Docker network for service communication
- **Volumes**: Persistent storage for PostgreSQL data
- **Restart Policies**: `unless-stopped` for high availability

### Operational Considerations
1. **Monitoring**: Track database connection pools, worker queue depths
2. **Backup**: Regular pg_dump of PostgreSQL database
3. **Logs**: Monitor container logs for SOAP connectivity issues
4. **Updates**: Rolling updates possible due to stateless API workers
5. **Scaling**: Increase MAX_WORKERS environment variable for more parallelism

## Conclusion

The StratusBaixaAlta Python reimplementation provides a solid foundation for broadcast media processing with:
- **Production-ready architecture** following microservices principles
- **Complete retry functionality** already implemented as requested
- **Strong separation of concerns** enabling independent component scaling
- **Comprehensive audit trail** for regulatory compliance
- **Containerized deployment** for portability and easy replication
- **Database-driven state management** ensuring consistency and recoverability

The system meets all mandatory project standards including Docker containerization, PostgreSQL as default database, and focus on scalability, backup strategies, and minimal downtime. The retry feature specifically satisfies all requirements:
- Preserves existing SOAP logic and workflows
- Maintains database integrity and monitoring capabilities
- Provides intuitive user interface through the web dashboard
- Handles both Error and Cancelled job states appropriately
- Includes proper error handling and validation

No additional implementation is required for the core retry functionality. The system is ready for immediate deployment in broadcast television environments.