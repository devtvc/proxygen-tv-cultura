"""
Worker main loop for discovering and processing media
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import os
import sys

# Ensure worker directory is at the beginning of sys.path to prioritize local imports (e.g. ffmpeg_worker)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


from sqlalchemy.orm import Session
from sqlalchemy import func
from shared.database import SessionLocal, engine, create_tables
from shared.models import Media, Job, Event, FilaManual
import shared.schemas as schemas

from shared.soap import (
    proxima_media,
    reservar_servidor,
    obter_token,
    obter_cadastro,
    marcar_erro,
    marcar_concluido,
    marcar_pendente
)

from ffmpeg_worker import gerar_proxy

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configuration
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))
# Máximo de tentativas para falhas TRANSITÓRIAS (SOAP/reserva) antes de marcar Erro definitivo.
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))
# Watchdog: tempo máximo (s) que um slot pode ficar reservado sem job ativo correspondente
# antes de ser considerado órfão e liberado. Cobre vazamentos residuais de slot.
WATCHDOG_GRACE = int(os.getenv("WATCHDOG_GRACE", "180"))

# Global control
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
lock = threading.Lock()
medias_em_processamento = set()
# Marca o instante (monotônico) em que cada slot foi reservado — usado pelo watchdog.
slot_inicio = {}


def reservar_slot(media_id: str) -> bool:
    """
    Reserva um slot de processamento de forma atômica.
    Retorna False se a mídia já estiver com slot reservado.
    """
    with lock:
        if media_id in medias_em_processamento:
            return False
        medias_em_processamento.add(media_id)
        slot_inicio[media_id] = time.monotonic()
        return True


def liberar_slot(media_id: str):
    """
    Libera o slot de uma mídia (idempotente).
    """
    with lock:
        medias_em_processamento.discard(media_id)
        slot_inicio.pop(media_id, None)


def get_db() -> Session:
    """
    Get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log_event(db: Session, media_id: str, tipo_evento: str, descricao: str = None):
    """
    Log an event to the database
    """
    event = Event(
        media_id=media_id,
        tipo_evento=tipo_evento,
        descricao=descricao
    )
    db.add(event)
    db.commit()
    return event


def update_media_status(db: Session, media_id: str, status: str, token: int = None,
                       arquivo_origem: str = None, arquivo_proxy: str = None):
    """
    Update media status in database
    """
    media = db.query(Media).filter(Media.media_id == media_id).first()
    if media:
        media.status = status
        if token is not None:
            media.token = token
        if arquivo_origem is not None:
            media.arquivo_origem = arquivo_origem
        if arquivo_proxy is not None:
            media.arquivo_proxy = arquivo_proxy
        media.atualizado_em = func.now()
        db.commit()
        db.refresh(media)
        return media
    return None


def create_or_update_job(db: Session, media_id: str, status: str,
                        worker: str = None, mensagem: str = None,
                        percentual: int = None) -> Job:
    """
    Create or update a job record
    """
    job = db.query(Job).filter(Job.media_id == media_id).first()

    if job:
        # Update existing job
        job.status = status
        if worker is not None:
            job.worker = worker
        if mensagem is not None:
            job.mensagem = mensagem
        if percentual is not None:
            job.percentual = percentual
        if status in ["Concluído", "Erro", "Cancelado"] and job.fim is None:
            job.fim = func.now()
        if status == "Iniciando" and job.inicio is None:
            job.inicio = func.now()
    else:
        # Create new job
        job = Job(
            media_id=media_id,
            status=status,
            worker=worker,
            mensagem=mensagem,
            percentual=percentual or 0
        )
        if status == "Iniciando":
            job.inicio = func.now()
        db.add(job)

    db.commit()
    db.refresh(job)
    return job


def progress_callback(media_id: str, status: str, percentual: int) -> bool:
    """
    Callback function to update job progress in database
    This will be called by ffmpeg_worker during processing
    Returns True if processing should continue, False if cancelled
    """
    db = SessionLocal()
    try:
        # Check if job was cancelled by the API
        job_status = db.query(Job.status).filter(Job.media_id == media_id).first()
        if job_status and job_status[0] == "Cancelado":
            return False

        # Update job with progress information
        job = create_or_update_job(
            db,
            media_id,
            status,
            worker="ffmpeg-worker",
            mensagem=f"Processamento em progresso: {percentual}%",
            percentual=percentual
        )

        # Also update media status if needed
        if status == "Processando":
            update_media_status(db, media_id, "Processando")
        elif status == "Concluído":
            update_media_status(db, media_id, "Concluído")

        db.commit()
        return True
    except Exception as ex:
        print(f"[ERROR] Failed to update progress for {media_id}: {ex}")
        db.rollback()
        return True # Continue despite logging error
    finally:
        db.close()

def processar_media(media: dict):
    """
    Process a single media item (equivalent to the current processar_media function)
    """
    db = SessionLocal()
    media_id = media["mediaId"]

    try:
        # Log start of encoding
        log_event(db, media_id, "ENCODE_INICIADO", "Iniciando codificação do proxy")

        # Update job status to processing
        create_or_update_job(db, media_id, "Processando",
                           worker="ffmpeg-worker",
                           mensagem="Iniciando processamento FFmpeg",
                           percentual=0)

        # Generate proxy using FFmpeg worker with progress callback
        result = gerar_proxy(media, progress_callback=progress_callback)

        # If we reach here, encoding was successful
        # Update media status to completed
        update_media_status(db, media_id, "Concluído",
                          arquivo_proxy=result["output_file"])

        # Update job status to completed
        create_or_update_job(db, media_id, "Concluído",
                           worker="ffmpeg-worker",
                           mensagem="Processamento concluído com sucesso",
                           percentual=100)

        # Log completion
        log_event(db, media_id, "ENCODE_CONCLUIDO", "Proxy gerado com sucesso")

        # Update SOAP status to completed
        try:
            token = obter_token(media_id)
            marcar_concluido(media_id, token)
            print(f"[SOAP] Concluído registrado: {media_id}")
        except Exception as ex:
            print(f"[SOAP ERRO] {media_id}: {ex}")
            # Don't fail the whole process if SOAP update fails

    except Exception as ex:
        # Handle error case
        print(f"\n[ERRO] {media_id}")
        print(ex)

        # Update media status to error
        update_media_status(db, media_id, "Erro")

        # Update job status to error
        create_or_update_job(db, media_id, "Erro",
                           worker="ffmpeg-worker",
                           mensagem=str(ex),
                           percentual=0)

        # Log error
        log_event(db, media_id, "ERRO", str(ex))

        # Update SOAP status to error
        try:
            token = obter_token(media_id)
            marcar_erro(media_id, token, str(ex))
            print(f"[SOAP] Erro registrado: {media_id}")
        except Exception as ex2:
            print(f"[SOAP ERRO] {media_id}: {ex2}")
            # Don't fail the whole process if SOAP update fails
    finally:
        # Clean up from processing set
        liberar_slot(media_id)
        with lock:
            ativos = len(medias_em_processamento)
        print(f"[FINALIZADO] {media_id}")
        print(f"[ATIVOS] {ativos}/{MAX_WORKERS}")
        db.close()


def processar_fila_manual(item_fila: dict):
    """
    Processa um item da fila manual com prioridade.
    Recebe um dict com 'id' (FK da fila_manual) e 'media_id'.
    Chama o SOAP, reserva, processa e atualiza o status na fila_manual.
    """
    media_id = item_fila["media_id"]
    fila_id = item_fila["id"]
    db = SessionLocal()

    try:
        print(f"[FILA MANUAL] Iniciando processamento prioritário de {media_id}")

        # Marca como Processando SOMENTE agora, quando a task realmente roda
        # (no loop o item fica "Aguardando"). Assim o status reflete o estado real:
        # "Processando" = codificando de fato.
        item = db.query(FilaManual).filter(FilaManual.id == fila_id).first()
        if item:
            item.status = "Processando"
            item.mensagem = "Em processamento pelo worker"
            db.commit()

        # Busca cadastro completo: token + tipo/duracao (evita falha quando banco não tem esses dados)
        cadastro = obter_cadastro(media_id)
        token = int(cadastro["TOKEN"])

        # CDG_STC = código do tipo de mídia (E, P, I, B, A) — campo confirmado via carrega_cadastro
        # DURACAO = não disponível no cadastro; vem apenas do ProximaMedia — usar o banco como fallback
        tipo_soap    = cadastro.get("CDG_STC")
        duracao_soap = cadastro.get("DURACAO")  # normalmente None neste endpoint
        print(f"[FILA MANUAL] Cadastro SOAP — CDG_STC={tipo_soap!r} DURACAO={duracao_soap!r}")

        # Reset de estado no SOAP antes de reservar (item pode estar em Erro/Cancelado)
        marcar_pendente(media_id, token)
        print(f"[FILA MANUAL] SOAP resetado para Pendente: {media_id}")

        # Reserva no SOAP (obrigatório)
        reservado = reservar_servidor(media_id)
        if not reservado:
            raise Exception(f"Não foi possível reservar {media_id} no SOAP")

        # Garante que a mídia existe no banco local
        media_record = db.query(Media).filter(Media.media_id == media_id).first()
        # TTL_MAT = título do material; PROGRAMA = nome do programa (fallback)
        titulo_soap_manual = cadastro.get("TTL_MAT") or cadastro.get("PROGRAMA")
        if not media_record:
            media_record = Media(
                media_id=media_id,
                status="Pendente",
                token=token,
                titulo=titulo_soap_manual,
                tipo=tipo_soap,
                duracao=duracao_soap,
            )
            db.add(media_record)
        else:
            media_record.status = "Pendente"
            media_record.token = token
            # Atualiza titulo/tipo/duracao com dados SOAP se o banco não os tiver
            if titulo_soap_manual and not media_record.titulo:
                media_record.titulo = titulo_soap_manual
            if tipo_soap and not media_record.tipo:
                media_record.tipo = tipo_soap
            if duracao_soap and not media_record.duracao:
                media_record.duracao = duracao_soap

        # Cria/atualiza job
        create_or_update_job(
            db, media_id, "Iniciando",
            worker="manual-worker",
            mensagem="Processamento manual solicitado pelo usuário",
            percentual=0
        )

        log_event(db, media_id, "MEDIA_DESCOBERTA", "Mídia adicionada manualmente pelo usuário")
        log_event(db, media_id, "RESERVADA", f"Mídia reservada no servidor {os.getenv('SERVIDOR', 'A')}")
        db.commit()

        # Captura tipo e duracao: prioriza SOAP sobre banco
        # duracao pode ser None — ffmpeg_worker tentará obter via ffprobe do arquivo
        media_tipo    = tipo_soap    or media_record.tipo
        media_duracao = duracao_soap or media_record.duracao
        db.close()

        # Processa via FFmpeg — inclui tipo e duracao necessários pelo ffmpeg_worker
        # (duracao=None é permitido: ffmpeg_worker usa ffprobe como fallback)
        media_dict = {
            "mediaId": media_id,
            "tipo":    media_tipo,
            "duracao": media_duracao,
        }

        # Slot já reservado de forma síncrona no loop principal antes do submit.
        # Mantém a garantia caso este método seja chamado por outro caminho.
        reservar_slot(media_id)

        processar_media(media_dict)

        # Atualiza status da fila manual após processamento
        db2 = SessionLocal()
        try:
            item = db2.query(FilaManual).filter(FilaManual.id == fila_id).first()
            if item:
                # Verifica o resultado no job
                job = db2.query(Job).filter(Job.media_id == media_id).order_by(Job.id.desc()).first()
                if job and job.status == "Concluído":
                    item.status = "Concluído"
                    item.mensagem = "Proxy gerado com sucesso"
                else:
                    item.status = "Erro"
                    item.mensagem = job.mensagem if job else "Erro desconhecido"
                db2.commit()
        finally:
            db2.close()

    except Exception as ex:
        print(f"[FILA MANUAL ERRO] {media_id}: {ex}")
        # Falhas aqui são da fase SOAP/reserva — antes de processar_media ser chamado.
        # processar_media trata seus próprios erros internamente; se chegou aqui, o
        # Job pode ter sido criado como "Iniciando" e nunca atualizado. Corrigir.
        db3 = SessionLocal()
        try:
            item = db3.query(FilaManual).filter(FilaManual.id == fila_id).first()
            if item:
                item.tentativas = (item.tentativas or 0) + 1
                definitivo = item.tentativas >= MAX_TENTATIVAS
                if definitivo:
                    item.status = "Erro"
                    item.mensagem = f"Falha após {item.tentativas} tentativa(s): {ex}"
                    print(f"[FILA MANUAL] {media_id} marcado Erro após {item.tentativas} tentativas")
                else:
                    item.status = "Pendente"
                    item.mensagem = (
                        f"Tentativa {item.tentativas}/{MAX_TENTATIVAS} falhou, "
                        f"reenfileirado: {ex}"
                    )
                    print(
                        f"[FILA MANUAL] {media_id} reenfileirado "
                        f"(tentativa {item.tentativas}/{MAX_TENTATIVAS})"
                    )
                db3.commit()
            else:
                definitivo = True  # sem item de fila, trata como definitivo

            # Atualiza o Job criado como "Iniciando" para refletir o estado real.
            # Se for reenfileirado, reverte para "Iniciando" do próximo ciclo não
            # existir — apenas fecha o job corrente como "Erro". Se definitivo,
            # atualiza Media também.
            job_preso = db3.query(Job).filter(
                Job.media_id == media_id,
                Job.status.in_(["Iniciando", "Processando"])
            ).first()
            if job_preso:
                job_preso.status = "Erro"
                job_preso.mensagem = str(ex)
                job_preso.fim = func.now()
                db3.commit()

            if definitivo:
                media_rec = db3.query(Media).filter(Media.media_id == media_id).first()
                if media_rec and media_rec.status in ["Iniciando", "Processando", "Pendente"]:
                    media_rec.status = "Erro"
                    media_rec.atualizado_em = func.now()
                    db3.commit()
        finally:
            db3.close()
        # Garante liberação do slot em caso de erro antes do processar_media
        liberar_slot(media_id)


def watchdog_slots():
    """
    Rede de segurança contra vazamento de slots.
    Libera qualquer slot reservado há mais de WATCHDOG_GRACE segundos que não
    tenha um job ativo nem item de fila manual ativo correspondente — situação
    que só ocorre se uma exceção impediu o despacho/limpeza normal.
    """
    agora = time.monotonic()
    with lock:
        candidatos = [
            mid for mid, inicio in slot_inicio.items()
            if agora - inicio > WATCHDOG_GRACE
        ]

    if not candidatos:
        return

    db = SessionLocal()
    try:
        for media_id in candidatos:
            job_ativo = db.query(Job.id).filter(
                Job.media_id == media_id,
                Job.status.in_(["Iniciando", "Processando"])
            ).first()
            fila_ativa = db.query(FilaManual.id).filter(
                FilaManual.media_id == media_id,
                FilaManual.status.in_(["Aguardando", "Processando"])
            ).first()

            if not job_ativo and not fila_ativa:
                liberar_slot(media_id)
                print(f"[WATCHDOG] Slot órfão liberado: {media_id}")
    except Exception as ex:
        print(f"[WATCHDOG] Erro na verificação: {ex}")
    finally:
        db.close()


def main():
    """
    Main worker loop
    """
    print(
        "\n=================================="
    )
    print(
        "STRATUS PYTHON CONCORRENTE (WORKER)"
    )
    print(
        f"WORKERS: {MAX_WORKERS}"
    )
    print(
        "==================================\n"
    )
    
    # Garante schema atualizado (cria tabelas / adiciona colunas novas) antes de operar
    try:
        create_tables()
    except Exception as e:
        print(f"[INIT] Aviso ao sincronizar schema: {e}")

    # Teste de conexão inicial
    try:
        print("[INIT] Testando conexão com serviço SOAP...")
        proxima_media()
        print("[INIT] Conexão SOAP OK.")
    except Exception as e:
        print(f"[INIT] Aviso: Servidor SOAP inacessível no momento: {e}")
        print("[INIT] O sistema continuará tentando em loop...")

    # Limpeza de órfãos na inicialização
    try:
        print("[INIT] Verificando jobs e fila_manual órfãos de execuções anteriores...")
        db = SessionLocal()

        # 1. Jobs órfãos na tabela jobs
        orphaned_jobs = db.query(Job).filter(Job.status.in_(["Iniciando", "Processando"])).all()
        if orphaned_jobs:
            print(f"[INIT] Limpando {len(orphaned_jobs)} jobs órfãos...")
            for job in orphaned_jobs:
                job.status = "Erro"
                job.mensagem = "Worker reiniciado"
                job.fim = func.now()

                media = db.query(Media).filter(Media.media_id == job.media_id).first()
                if media and media.status in ["Iniciando", "Processando"]:
                    media.status = "Erro"
                    media.atualizado_em = func.now()

        # 2. Itens da fila_manual presos em "Aguardando"/"Processando" — resetar para "Pendente"
        orphaned_fila = db.query(FilaManual).filter(
            FilaManual.status.in_(["Aguardando", "Processando"])
        ).all()
        if orphaned_fila:
            print(f"[INIT] Resetando {len(orphaned_fila)} itens da fila_manual para Pendente...")
            for item in orphaned_fila:
                item.status = "Pendente"
                item.mensagem = "Reenfileirado após reinício do worker"
                print(f"[INIT] fila_manual resetado: {item.media_id}")

        db.commit()
        db.close()
    except Exception as e:
        print(f"[INIT] Erro ao limpar órfãos: {e}")

    while True:
        try:
            # Rede de segurança: libera slots órfãos antes de avaliar capacidade
            watchdog_slots()

            # Get database session
            db = SessionLocal()

            with lock:
                ativos = len(medias_em_processamento)

            # sem slots livres
            if ativos >= MAX_WORKERS:
                db.close()
                time.sleep(1)
                continue

            # -------------------------------------------------------
            # PRIORIDADE: verifica fila manual antes de consultar SOAP
            # -------------------------------------------------------
            item_manual = db.query(FilaManual).filter(
                FilaManual.status == "Pendente"
            ).order_by(FilaManual.id.asc()).first()

            if item_manual:
                media_id_manual = item_manual.media_id
                fila_id_manual = item_manual.id

                # Reserva o slot de forma SÍNCRONA antes de submeter a task.
                # Sem isso, o set só é populado dentro da thread (após chamadas
                # SOAP lentas), permitindo que o loop ressubmeta o mesmo item /
                # pegue novos itens e gere jobs ativos duplicados (race condition).
                if not reservar_slot(media_id_manual):
                    db.close()
                    time.sleep(1)
                    continue

                # Marca o item como "Aguardando" (reservado, na fila do executor) para
                # não ser re-selecionado pela query. "Processando" só é gravado pela
                # própria task, quando a codificação realmente começa — assim o status
                # no dashboard reflete o estado real.
                item_manual.status = "Aguardando"
                item_manual.mensagem = "Reservado pelo worker, aguardando slot de codificação"
                db.commit()
                db.close()

                with lock:
                    ativos = len(medias_em_processamento)
                print(f"\n[FILA MANUAL] Item prioritário reservado: {media_id_manual}")
                print(f"[ATIVOS] {ativos}/{MAX_WORKERS}")

                # Despacha; se o submit falhar, libera o slot e reverte para Pendente
                # para não deixar slot vazado nem item preso fora da fila.
                try:
                    executor.submit(
                        processar_fila_manual,
                        {"id": fila_id_manual, "media_id": media_id_manual}
                    )
                except Exception as ex_submit:
                    print(f"[FILA MANUAL] Falha ao despachar {media_id_manual}: {ex_submit}")
                    liberar_slot(media_id_manual)
                    db_rev = SessionLocal()
                    try:
                        item_rev = db_rev.query(FilaManual).filter(
                            FilaManual.id == fila_id_manual
                        ).first()
                        if item_rev:
                            item_rev.status = "Pendente"
                            item_rev.mensagem = "Reenfileirado: falha ao despachar"
                            db_rev.commit()
                    finally:
                        db_rev.close()

                time.sleep(1)
                continue

            # -------------------------------------------------------
            # Comportamento normal: busca no SOAP
            # -------------------------------------------------------
            media = proxima_media()

            if not media:
                db.close()
                print(
                    "[SEM MÍDIAS]"
                )
                time.sleep(5)
                continue

            media_id = media["mediaId"]

            # evita duplicidade local
            with lock:
                if media_id in medias_em_processamento:
                    db.close()
                    time.sleep(1)
                    continue

            print(
                f"\n[{time.strftime('%H:%M:%S')}]"
            )
            print(
                f"Nova mídia: {media_id}"
            )

            reservado = reservar_servidor(
                media_id
            )

            if not reservado:
                db.close()
                print(
                    f"[IGNORADA] "
                    f"{media_id} "
                    f"não reservada"
                )
                time.sleep(1)
                continue

            # Reserva o slot de forma atômica (registra também o instante p/ watchdog)
            if not reservar_slot(media_id):
                db.close()
                time.sleep(1)
                continue

            # A partir daqui o slot está reservado: qualquer falha antes do submit
            # DEVE liberar o slot, senão ele vaza e trava o pipeline (ativos fica
            # permanentemente >= MAX_WORKERS).
            try:
                with lock:
                    ativos = len(medias_em_processamento)
                print(f"[FILA] {media_id}")
                print(f"[ATIVOS] {ativos}/{MAX_WORKERS}")

                # Create or update media record (using merge to avoid unique constraint error)
                titulo_soap = media.get("titulo")
                media_record = db.query(Media).filter(Media.media_id == media_id).first()
                if not media_record:
                    media_record = Media(
                        media_id=media_id,
                        titulo=titulo_soap,
                        tipo=media.get("tipo"),
                        duracao=media.get("duracao"),
                        status="Pendente"
                    )
                    db.add(media_record)
                else:
                    # Preenche campos ausentes com dados da descoberta SOAP
                    if titulo_soap and not media_record.titulo:
                        media_record.titulo = titulo_soap
                    if media.get("tipo") and not media_record.tipo:
                        media_record.tipo = media.get("tipo")
                    if media.get("duracao") and not media_record.duracao:
                        media_record.duracao = media.get("duracao")

                # Create initial job record
                job_record = create_or_update_job(
                    db,
                    media_id,
                    "Iniciando",
                    worker="discovery-worker",
                    mensagem="Mídia descoberta e reservada",
                    percentual=0
                )

                # Log discovery event
                log_event(db, media_id, "MEDIA_DESCOBERTA", "Mídia descoberta pelo serviço SOAP")
                log_event(db, media_id, "RESERVADA", f"Mídia reservada no servidor {os.getenv('SERVIDOR', 'A')}")

                db.commit()
                db.refresh(media_record)
                db.close()

                # Submit processing task to thread pool
                executor.submit(
                    processar_media,
                    media  # Pass the original media dict to maintain compatibility
                )
            except Exception as ex_dispatch:
                # Falha na preparação/despacho: libera o slot para não vazar
                liberar_slot(media_id)
                try:
                    db.close()
                except Exception:
                    pass
                print(f"[FALHA DESPACHO] {media_id}: {ex_dispatch}")
                time.sleep(1)
                continue

        except Exception as ex:
            print(
                "\n[FALHA GERAL]"
            )
            print(ex)
            # Se falhar a conexão com o SOAP, aguarda 10s antes de tentar novamente
            # para não sobrecarregar a rede/logs
            time.sleep(10)


if __name__ == "__main__":
    main()