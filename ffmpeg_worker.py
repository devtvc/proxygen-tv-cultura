import os
import subprocess
import time
import state

from soap import (
    obter_token,
    marcar_concluido,
)

from dotenv import load_dotenv
load_dotenv()

PROXY_DIR = os.getenv("PROXY_DIR", "/Volumes/arquivo$/PROXY")

INPUT_DIRS = {
    "P": os.getenv("INPUT_DIR_P", "/Volumes/arquivo$/FINALIZADOS"),
    "I": os.getenv("INPUT_DIR_I", "/Volumes/arquivo$/INSERCOES"),
    "B": os.getenv("INPUT_DIR_B", "/Volumes/arquivo$/BRUTOS"),
    "E": os.getenv("INPUT_DIR_E", "/Volumes/arquivo$/EDITADOS"),
    "A": os.getenv("INPUT_DIR_A", "/Volumes/arquivo$/ACERVO")
}

# --------------------------------------------------
# PROCURA ARQUIVO MXF
# --------------------------------------------------

def localizar_arquivo(media_id, tipo):

    caminhos = []

    if tipo in INPUT_DIRS:

        caminhos.append(
            os.path.join(
                INPUT_DIRS[tipo],
                f"{media_id}.mxf"
            )
        )

    for pasta in INPUT_DIRS.values():

        caminhos.append(
            os.path.join(
                pasta,
                f"{media_id}.mxf"
            )
        )

    for caminho in caminhos:

        if os.path.exists(caminho):
            return caminho

    return None

# --------------------------------------------------
# DURAÇÃO
# --------------------------------------------------

def obter_duracao_segundos(media):

    duracao = media.get("duracao")

    if not duracao:
        raise Exception(
            f"Duração inválida para {media['mediaId']}"
        )

    h, m, s = duracao.split(":")

    return (
        int(h) * 3600 +
        int(m) * 60 +
        float(s)
    )

# --------------------------------------------------
# GERA PROXY
# --------------------------------------------------

def gerar_proxy(media, progress_callback=None):

    media_id = media["mediaId"]
    tipo = media["tipo"]

    with state.lock:

        state.jobs[media_id] = {

            "media_id": media_id,
            "tipo": tipo,
            "status": "Iniciando",
            "percentual": 0,
            "inicio": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "arquivo": ""
        }

    print("\n--------------------------------")
    print("MediaID :", media_id)
    print("Tipo    :", tipo)
    print("--------------------------------")

    token = obter_token(media_id)

    print(f"[{media_id}] Token: {token}")

    input_file = localizar_arquivo(
        media_id,
        tipo
    )

    with state.lock:

        if media_id in state.jobs:

            state.jobs[media_id][
                "arquivo"
            ] = input_file

    if not input_file:

        raise Exception(
            f"MXF não encontrado: {media_id}"
        )

    output_file = os.path.join(
        PROXY_DIR,
        f"{media_id}.mp4"
    )

    print(
        f"[{media_id}] Entrada: {input_file}"
    )

    print(
        f"[{media_id}] Saída  : {output_file}"
    )

    duracao_total = obter_duracao_segundos(
        media
    )

    cmd = [

        "ffmpeg",

        "-y",

        "-i",
        input_file,

        "-map", "0:v:0",

        "-map", "0:a:0?",

        "-vf",
        "scale=640:360",

        "-c:v", "libx264",

        "-preset", "fast",

        "-profile:v", "high",
        "-level", "4.1",

        "-pix_fmt", "yuv420p",

        "-crf", "23",

        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",

        "-movflags", "+faststart",

        "-progress",
        "pipe:1",

        "-nostats",

        output_file
    ]

    print(
        f"[{media_id}] Iniciando FFmpeg..."
    )

    with state.lock:

        if media_id in state.jobs:

            state.jobs[media_id][
                "status"
            ] = "Processando"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )
    
    with state.lock:
        
        state.processos[media_id] = proc

    ultimo_pct = -1

    for linha in proc.stdout:

        linha = linha.strip()

        if not linha.startswith(
            "out_time_ms="
        ):
            continue

        valor = linha.split("=")[1]

        if valor == "N/A":
            continue

        out_ms = int(valor)

        segundos = (
            out_ms / 1000000
        )

        pct = int(
            (segundos / duracao_total)
            * 100
        )

        if pct > 100:
            pct = 100

        if pct != ultimo_pct:

            print(
                f"[{media_id}] {pct}%"
            )

            if progress_callback:
                if progress_callback(media_id, "Processando", pct) is False:
                    print(f"[{media_id}] Cancelamento detectado. Matando FFmpeg...")
                    proc.kill()
                    raise Exception("Processamento cancelado pelo usuário")

            with state.lock:

                if media_id in state.jobs:

                    state.jobs[media_id][
                        "percentual"
                    ] = pct

            ultimo_pct = pct

    retorno = proc.wait()

    if retorno != 0:

        raise Exception(
            f"FFmpeg retornou código {retorno}"
        )

    if not os.path.exists(
        output_file
    ):

        raise Exception(
            "Proxy não foi criado"
        )

    marcar_concluido(
        media_id,
        token
    )

    if progress_callback:
        progress_callback(media_id, "Concluído", 100)


    with state.lock:

        if media_id in state.jobs:

            state.jobs[media_id][
                "percentual"
            ] = 100

            state.jobs[media_id][
                "status"
            ] = "Concluído"

        state.historico.append({

            "media_id": media_id,

            "resultado": "Concluído",

            "horario": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        })
        
        state.processos.pop(
            media_id,
            None
        )

        state.jobs.pop(
            media_id,
            None
        )

    print(
        f"[OK] Proxy concluído: {media_id}"
    )