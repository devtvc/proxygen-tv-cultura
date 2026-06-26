"""
FastAPI application for the broadcast proxy system
"""
import os
import time
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from shared.database import get_db, create_tables
from shared.models import Media, Job, Event, FilaManual
import shared.schemas as schemas
from shared.soap import obter_token, marcar_pendente, listar_falhas_legado

app = FastAPI(title="Broadcast Proxy System", version="2.0.0")

# Definir caminhos absolutos para static e templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static"
)

templates = Jinja2Templates(
    directory=os.path.join(BASE_DIR, "templates")
)


# Create tables on startup
@app.on_event("startup")
def startup_event():
    create_tables()
    print("[WEB] Application started")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


def _enrich_job(job: Job, db: Session) -> dict:
    """Retorna dict do job enriquecido com titulo/tipo/duracao da tabela medias."""
    media = db.query(Media).filter(Media.media_id == job.media_id).first()
    return {
        "id":        job.id,
        "media_id":  job.media_id,
        "status":    job.status,
        "inicio":    job.inicio,
        "fim":       job.fim,
        "percentual": job.percentual,
        "worker":    job.worker,
        "mensagem":  job.mensagem,
        "titulo":    media.titulo  if media else None,
        "tipo":      media.tipo    if media else None,
        "duracao":   media.duracao if media else None,
    }


@app.get("/api/jobs", response_model=List[schemas.JobResponse])
def get_active_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(
        Job.status.in_(["Iniciando", "Processando"])
    ).order_by(Job.inicio.desc()).all()
    return [_enrich_job(j, db) for j in jobs]


@app.get("/api/history", response_model=List[schemas.JobResponse])
def get_history(limit: int = 100, db: Session = Depends(get_db)):
    """
    Histórico unificado: jobs locais finalizados + erros do MAM legado.
    Erros do MAM que já existem localmente (mesmo media_id) não são duplicados.
    """
    jobs = db.query(Job).filter(
        Job.status.in_(["Concluído", "Erro", "Cancelado"])
    ).order_by(Job.fim.desc()).limit(limit).all()

    local = [_enrich_job(j, db) for j in jobs]
    ids_locais = {j["media_id"] for j in local}

    # Adiciona erros do MAM legado que não têm registro local
    try:
        falhas_soap = listar_falhas_legado()
        for item in falhas_soap:
            mid = item.get("mediaId")
            if not mid or mid in ids_locais:
                continue
            local.append({
                "id":        None,
                "media_id":  mid,
                "status":    "Erro",
                "inicio":    None,
                "fim":       item.get("data_baixa"),
                "percentual": 0,
                "worker":    "soap-legado",
                "mensagem":  item.get("erro_baixa") or "Erro registrado no MAM legado",
                "titulo":    item.get("titulo"),
                "tipo":      item.get("tipo"),
                "duracao":   item.get("duracao"),
            })
    except Exception as ex:
        print(f"[API] Aviso: falha ao buscar erros legado para histórico: {ex}")

    return local


@app.get("/api/stats", response_model=schemas.StatsResponse)
def get_stats(db: Session = Depends(get_db)):
    workers    = int(os.getenv("MAX_WORKERS", "1"))
    ativos     = db.query(Job).filter(Job.status.in_(["Iniciando", "Processando"])).count()
    concluidos = db.query(Job).filter(Job.status == "Concluído").count()
    erros_local = db.query(Job).filter(Job.status == "Erro").count()

    # Erros do MAM legado que não têm registro local (sem duplicar)
    erros_legado = 0
    try:
        ids_locais = {
            r[0] for r in db.query(Job.media_id).filter(Job.status == "Erro").all()
        }
        falhas_soap = listar_falhas_legado()
        erros_legado = sum(
            1 for f in falhas_soap
            if f.get("mediaId") and f["mediaId"] not in ids_locais
        )
    except Exception:
        pass

    return schemas.StatsResponse(
        workers=workers,
        ativos=ativos,
        concluidos=concluidos,
        erros=erros_local + erros_legado,
        erros_legado=erros_legado,
    )


@app.get("/api/media/{media_id}", response_model=schemas.MediaResponse)
def get_media(media_id: str, db: Session = Depends(get_db)):
    """
    Get detailed information about a specific media item
    """
    media = db.query(Media).filter(Media.media_id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    return media


@app.get("/api/media/{media_id}/events", response_model=List[schemas.EventResponse])
def get_media_events(media_id: str, db: Session = Depends(get_db)):
    """
    Get events for a specific media item
    """
    events = db.query(Event).filter(
        Event.media_id == media_id
    ).order_by(Event.data_hora.desc()).all()
    return events


@app.post("/api/job/{media_id}/cancel", response_model=schemas.JobCancelResponse)
def cancelar_job(media_id: str, db: Session = Depends(get_db)):
    """
    Cancel a job by marking it as cancelled in the system and SOAP
    """
    # Check if job exists and is active
    job = db.query(Job).filter(
        Job.media_id == media_id,
        Job.status.in_(["Iniciando", "Processando"])
    ).first()

    if not job:
        return schemas.JobCancelResponse(
            ok=False,
            erro="Job não encontrado ou já finalizado"
        )

    # Update job status to cancelled
    job.status = "Cancelado"
    job.fim = func.now()
    db.commit()

    # Update media status to cancelled
    media = db.query(Media).filter(Media.media_id == media_id).first()
    if media:
        media.status = "Cancelado"
        media.atualizado_em = func.now()
        db.commit()

    # Try to update SOAP status to pending (to allow retry)
    try:
        token = obter_token(media_id)
        marcar_pendente(media_id, token)
    except Exception as ex:
        # Log SOAP error but don't fail the cancellation
        print(f"[SOAP] Warning: Could not update SOAP status for {media_id}: {ex}")

    return schemas.JobCancelResponse(
        ok=True
    )

@app.post("/api/job/{media_id}/retry", response_model=schemas.JobCancelResponse)
def retry_job(media_id: str, db: Session = Depends(get_db)):
    """
    Reinicia um job que falhou ou foi cancelado, inserindo-o na fila_manual
    com prioridade para ser processado antes dos itens do SOAP normal.
    """
    # 1. Verifica se a mídia existe no banco local
    media = db.query(Media).filter(Media.media_id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Mídia não encontrada")

    # 2. Só permite refazer se o status atual for Erro ou Cancelado
    if media.status not in ["Erro", "Cancelado"]:
        return schemas.JobCancelResponse(
            ok=False,
            erro=f"Apenas mídias com erro ou canceladas podem ser refeitas. Status atual: {media.status}"
        )

    try:
        # 3. Verifica se já existe na fila manual com status ativo (evita duplicata)
        existente = db.query(FilaManual).filter(
            FilaManual.media_id == media_id,
            FilaManual.status.in_(["Pendente", "Aguardando", "Processando"])
        ).first()

        if existente:
            return schemas.JobCancelResponse(
                ok=False,
                erro=f"Media ID {media_id} já está na fila de reprocessamento com status '{existente.status}'"
            )

        # 4. Insere na fila manual com prioridade
        item_fila = FilaManual(
            media_id=media_id,
            status="Pendente",
            mensagem="Reprocessamento solicitado pelo usuário (retry)"
        )
        db.add(item_fila)

        # 5. Atualiza o status local para Pendente para refletir no Dashboard imediatamente
        media.status = "Pendente"
        media.atualizado_em = func.now()

        # 6. Registra o evento de solicitação de retry
        event = Event(
            media_id=media_id,
            tipo_evento="RETRY_SOLICITADO",
            descricao="Reprocessamento com prioridade adicionado à fila manual pelo usuário"
        )
        db.add(event)

        db.commit()
        print(f"[API] Retry prioritário adicionado à fila manual para: {media_id}")

        return schemas.JobCancelResponse(ok=True)

    except Exception as ex:
        db.rollback()
        print(f"[API ERRO] Falha ao solicitar retry para {media_id}: {ex}")
        return schemas.JobCancelResponse(ok=False, erro=str(ex))


@app.post("/api/job/{media_id}/force-retry", response_model=schemas.JobCancelResponse)
def force_retry_job(media_id: str, db: Session = Depends(get_db)):
    """
    Força o reprocessamento de qualquer mídia (mesmo se concluída, inexistente no banco, etc.),
    marcando-a como Pendente tanto no SOAP quanto no banco local.
    """
    try:
        # 1. Obtém o token do SOAP para garantir que o media_id existe no sistema externo
        token = obter_token(media_id)
        
        # 2. Marca no SOAP como Pendente ('P')
        marcar_pendente(media_id, token)
        
        # 3. Busca a mídia no banco de dados local
        media = db.query(Media).filter(Media.media_id == media_id).first()
        if media:
            # Se já existe, atualiza para Pendente e atualiza o token
            media.status = "Pendente"
            media.token = token
            media.atualizado_em = func.now()
        else:
            # Se não existe no banco local, cria um novo registro
            media = Media(
                media_id=media_id,
                status="Pendente",
                token=token
            )
            db.add(media)
        
        # 4. Registra o evento de reprocessamento forçado
        event = Event(
            media_id=media_id,
            tipo_evento="RETRY_FORCADO",
            descricao="Reprocessamento forçado pelo usuário no dashboard"
        )
        db.add(event)
        
        # 5. Comita as alterações
        db.commit()
        print(f"[API] Force-retry solicitado para: {media_id}")
        return schemas.JobCancelResponse(ok=True)
        
    except Exception as ex:
        db.rollback()
        print(f"[API ERRO] Falha ao forçar retry para {media_id}: {ex}")
        return schemas.JobCancelResponse(ok=False, erro=str(ex))


@app.get("/api/erros-legado")
def get_erros_legado():
    """
    Retorna ao vivo a lista de mídias com flag_Baixa='E' (erro) registradas no MAM legado.
    Usa PesquisarMediaBaixaAlta(tipo='F') — mesmo método do app C# StratusBaixaAlta.
    Não grava nada no banco local; dados sempre frescos direto do SOAP.
    """
    try:
        falhas = listar_falhas_legado()
    except Exception as ex:
        print(f"[API ERRO] Falha ao consultar MAM legado: {ex}")
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao consultar o MAM: {str(ex)}"
        )

    return [
        {
            "media_id":  item.get("mediaId"),
            "titulo":    item.get("titulo"),
            "tipo":      item.get("tipo"),
            "duracao":   item.get("duracao"),
            "erro":      item.get("erro_baixa"),
            "data_baixa": str(item.get("data_baixa")) if item.get("data_baixa") else None,
            "formato":   item.get("formato"),
        }
        for item in falhas
        if item.get("mediaId")
    ]


@app.get("/api/fila-manual", response_model=List[schemas.FilaManualResponse])
def get_fila_manual(db: Session = Depends(get_db)):
    """
    Retorna todos os itens da fila de reprocessamento manual enriquecidos
    com titulo/tipo/duracao da tabela medias.
    """
    itens = db.query(FilaManual).order_by(FilaManual.id.asc()).all()
    resultado = []
    for item in itens:
        media = db.query(Media).filter(Media.media_id == item.media_id).first()
        d = {
            "id":          item.id,
            "media_id":    item.media_id,
            "status":      item.status,
            "tentativas":  item.tentativas,
            "criado_em":   item.criado_em,
            "atualizado_em": item.atualizado_em,
            "mensagem":    item.mensagem,
            "titulo":      media.titulo  if media else None,
            "tipo":        media.tipo    if media else None,
            "duracao":     media.duracao if media else None,
        }
        resultado.append(d)
    return resultado


@app.post("/api/fila-manual", response_model=schemas.JobCancelResponse)
def adicionar_fila_manual(body: schemas.FilaManualCreate, db: Session = Depends(get_db)):
    """
    Adiciona um media_id à fila de reprocessamento manual com prioridade.
    O worker irá processar este item ANTES de buscar novos itens no SOAP.
    Rejeita duplicatas com status Pendente ou Processando.
    """
    media_id = body.media_id.strip()

    if not media_id:
        return schemas.JobCancelResponse(ok=False, erro="Media ID inválido")

    # Verifica se já existe na fila com status ativo
    existente = db.query(FilaManual).filter(
        FilaManual.media_id == media_id,
        FilaManual.status.in_(["Pendente", "Processando"])
    ).first()

    if existente:
        return schemas.JobCancelResponse(
            ok=False,
            erro=f"Media ID {media_id} já está na fila manual com status '{existente.status}'"
        )

    # Insere na fila manual
    item = FilaManual(
        media_id=media_id,
        status="Pendente",
        mensagem="Solicitado manualmente pelo usuário"
    )
    db.add(item)

    # Registra evento de auditoria (se a mídia já existir no banco)
    media = db.query(Media).filter(Media.media_id == media_id).first()
    if media:
        evento = Event(
            media_id=media_id,
            tipo_evento="FILA_MANUAL_ADICIONADO",
            descricao="Adicionado à fila de reprocessamento manual pelo usuário"
        )
        db.add(evento)

    db.commit()
    print(f"[API] Media ID {media_id} adicionado à fila manual")
    return schemas.JobCancelResponse(ok=True)