"""
FFmpeg worker for generating media proxies
"""
import os
import subprocess
import time

from shared.soap import (
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

def _duracao_via_ffprobe(input_file: str) -> float:
    """
    Obtém a duração do arquivo via ffprobe quando o MAM não fornece.
    Usado como fallback para mídias sem duração cadastrada (ex: BRUTOS).
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_file
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        duracao_str = result.stdout.strip()
        if duracao_str and duracao_str != "N/A":
            return float(duracao_str)
    except Exception as ex:
        print(f"[ffprobe] Erro ao obter duração de {input_file}: {ex}")
    return None


def obter_duracao_segundos(media, input_file: str = None):
    """
    Retorna a duração em segundos.
    Fonte primária: campo 'duracao' do MAM (HH:MM:SS.ms).
    Fallback: ffprobe sobre o arquivo de entrada (quando input_file fornecido).
    """
    duracao = media.get("duracao")

    if duracao:
        h, m, s = duracao.split(":")
        return (
            int(h) * 3600 +
            int(m) * 60 +
            float(s)
        )

    if input_file:
        print(
            f"[{media['mediaId']}] Duração não disponível no MAM — "
            f"obtendo via ffprobe..."
        )
        segundos = _duracao_via_ffprobe(input_file)
        if segundos:
            print(f"[{media['mediaId']}] ffprobe: {segundos:.1f}s")
            return segundos

    raise Exception(
        f"Duração não encontrada para {media['mediaId']}. "
        "Verifique se o media_id está correto no MAM."
    )

# --------------------------------------------------
# GERA PROXY
# --------------------------------------------------

def gerar_proxy(media, progress_callback=None):
    """
    Generate MP4 proxy from MXF source

    Args:
        media: Dictionary containing media information (mediaId, tipo, duracao)
        progress_callback: Optional function to call with progress updates
                          Function signature: callback(media_id, status, percentual) -> bool (returns False if should cancel)

    Returns:
        dict: Result information including success status and output file path
    """
    media_id = media["mediaId"]
    tipo = media["tipo"]

    # Note: In the new architecture, job state management is handled by the worker
    # This function focuses purely on FFmpeg execution and progress reporting

    print("\n--------------------------------")
    print("MediaID :", media_id)
    print("Tipo    :", tipo)
    print("--------------------------------")

    # Obtain token for SOAP updates (still needed for external service)
    token = obter_token(media_id)
    print(f"[{media_id}] Token: {token}")

    # Locate input file
    input_file = localizar_arquivo(
        media_id,
        tipo
    )

    if not input_file:
        raise Exception(
            f"MXF não encontrado: {media_id}"
        )

    # Define output file path
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

    # Get total duration for progress calculation (fallback: ffprobe do arquivo)
    duracao_total = obter_duracao_segundos(media, input_file=input_file)

    # Build FFmpeg command
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
        "-preset", "superfast",
        "-profile:v", "high",
        "-level", "4.1",
        "-pix_fmt", "yuv420p",
        "-crf", "25",
        "-c:a", "aac",
        "-b:a", "96k",
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

    # Start FFmpeg process
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1
    )

    ultimo_pct = -1

    # Process FFmpeg output for progress
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

            # Call progress callback if provided
            if progress_callback:
                # If callback returns False, it means the job was cancelled in DB
                if progress_callback(media_id, "Processando", pct) is False:
                    print(f"[{media_id}] Cancelamento detectado. Matando FFmpeg...")
                    proc.kill()
                    raise Exception("Processamento cancelado pelo usuário")

            ultimo_pct = pct

    # Wait for process to complete
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

    # Mark as completed in SOAP
    marcar_concluido(
        media_id,
        token
    )

    # Final progress update
    if progress_callback:
        progress_callback(media_id, "Concluído", 100)

    print(
        f"[OK] Proxy concluído: {media_id}"
    )

    return {
        "success": True,
        "media_id": media_id,
        "output_file": output_file,
        "token": token
    }