import time
import threading
import os
from dotenv import load_dotenv

from concurrent.futures import (
    ThreadPoolExecutor
)

import state

from soap import (
    proxima_media,
    reservar_servidor,
    obter_token,
    marcar_erro,
    marcar_concluido
)

from ffmpeg_worker import (
    gerar_proxy
)

# Load environment variables
load_dotenv()

# --------------------------------------------------
# CONFIGURAÇÃO
# --------------------------------------------------

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "1"))

# --------------------------------------------------
# CONTROLE DE CONCORRÊNCIA
# --------------------------------------------------

executor = ThreadPoolExecutor(
    max_workers=MAX_WORKERS
)

lock = threading.Lock()

# mídias atualmente em processamento
medias_em_processamento = set()

# --------------------------------------------------
# WORKER
# --------------------------------------------------

def processar_media(media):

    media_id = media["mediaId"]
    is_error = False
    error_msg = None

    # Initialize job tracking for frontend (when processing starts)
    with state.lock:
        state.jobs[media_id] = {
            "media_id": media_id,
            "percentual": 0,
            "inicio": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        # Note: state.processos[media_id] is set by the caller (main function)

    try:

        gerar_proxy(media)

    except Exception as ex:

        is_error = True
        error_msg = str(ex)

        print(
            f"\n[ERRO] {media_id}"
        )

        print(ex)

        # ------------------------------------------
        # Atualiza dashboard
        # ------------------------------------------

        with state.lock:

            state.historico.append({

                "media_id": media_id,

                "resultado": "Erro",

                "erro": error_msg,

                "horario": time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            })

        # ------------------------------------------
        # Atualiza SOAP
        # ------------------------------------------

        try:

            token = obter_token(
                media_id
            )

            marcar_erro(
                media_id,
                token,
                error_msg
            )

            print(
                f"[SOAP] Erro registrado: {media_id}"
            )

        except Exception as ex2:

            print(
                f"[SOAP ERRO] {media_id}"
            )

            print(ex2)

    finally:

        with lock:

            medias_em_processamento.discard(
                media_id
            )

            print(
                f"[FINALIZADO] {media_id}"
            )

            print(
                f"[ATIVOS] "
                f"{len(medias_em_processamento)}"
                f"/{MAX_WORKERS}"
            )

            # Clean up job tracking when processing ends (success or error)
            with state.lock:
                state.processos.pop(media_id, None)
                state.jobs.pop(media_id, None)

                # Add to history on success (error case already handled in except block)
                if not is_error:
                    state.historico.append({
                        "media_id": media_id,
                        "resultado": "Concluído",
                        "erro": "",
                        "horario": time.strftime("%Y-%m-%d %H:%M:%S")
                    })

                    # ------------------------------------------
                    # Atualiza SOAP para sucesso
                    # ------------------------------------------

                    try:

                        token = obter_token(
                            media_id
                        )

                        marcar_concluido(
                            media_id,
                            token
                        )

                        print(
                            f"[SOAP] Marcado como concluído: {media_id}"
                        )

                    except Exception as ex2:

                        print(
                            f"[SOAP ERRO] {media_id}"
                        )

                        print(ex2)

# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print(
        "\n=================================="
    )

    print(
        "STRATUS PYTHON CONCORRENTE"
    )

    print(
        f"WORKERS: {MAX_WORKERS}"
    )

    print(
        "==================================\n"
    )

    while True:

        try:

            with lock:

                ativos = len(
                    medias_em_processamento
                )

            # sem slots livres
            if ativos >= MAX_WORKERS:

                time.sleep(1)

                continue

            media = proxima_media()

            if not media:

                print(
                    "[SEM MÍDIAS]"
                )

                time.sleep(5)

                continue

            media_id = media["mediaId"]

            # evita duplicidade local
            with lock:

                if media_id in medias_em_processamento:

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

                print(
                    f"[IGNORADA] "
                    f"{media_id} "
                    f"não reservada"
                )

                time.sleep(1)

                continue

            with lock:

                medias_em_processamento.add(
                    media_id
                )

            print(
                f"[FILA] {media_id}"
            )

            print(
                f"[ATIVOS] "
                f"{len(medias_em_processamento)}"
                f"/{MAX_WORKERS}"
            )

            # Submit job and store the Future for cancellation support
            future = executor.submit(processar_media, media)
            with state.lock:
                state.processos[media_id] = future

        except Exception as ex:

            print(
                "\n[FALHA GERAL]"
            )

            print(ex)

        time.sleep(0.5)

# --------------------------------------------------

if __name__ == "__main__":

    main()