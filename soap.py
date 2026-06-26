import os
from dotenv import load_dotenv
from zeep import Client
from zeep.helpers import serialize_object

# Load environment variables
load_dotenv()

# --------------------------------------------------
# CONFIGURAÇÃO
# --------------------------------------------------

WSDL = os.getenv("WSDL_URL", "http://172.20.15.190/mam080622/trf_services.asmx?WSDL")

SERVIDOR = os.getenv("SERVIDOR", "A")

# --------------------------------------------------
# CLIENT
# --------------------------------------------------

def get_client():
    return Client(WSDL)

# --------------------------------------------------
# TOKEN
# --------------------------------------------------

def obter_token(media_id):

    client = get_client()

    cadastro = serialize_object(
        client.service.carrega_cadastro(media_id)
    )

    if not cadastro:
        raise Exception(
            f"Cadastro não encontrado: {media_id}"
        )

    return int(cadastro["TOKEN"])

# --------------------------------------------------
# RESERVA SERVIDOR
# --------------------------------------------------

def reservar_servidor(media_id):

    client = get_client()

    ret = client.service.insere_Flag_SRVBAIXA(
        media_id,
        SERVIDOR
    )

    print(
        f"[SOAP] Reserva {media_id}: {ret}"
    )

    return ret == SERVIDOR

# --------------------------------------------------
# STATUS ERRO
# --------------------------------------------------

def marcar_erro(
    media_id,
    token,
    erro
):

    client = get_client()

    media = {
        "mediaId": media_id,
        "token": token,

        "erro_baixa": erro,
        "status_baixa": "Erro",

        "flag_Baixa": "E",
        "flag_srvbaixa": SERVIDOR
    }

    return client.service.insere_Status_Baixa(
        media
    )

# --------------------------------------------------
# STATUS OK
# --------------------------------------------------

def marcar_concluido(
    media_id,
    token
):

    client = get_client()

    media = {
        "mediaId": media_id,
        "token": token,

        "erro_baixa": None,
        "status_baixa": "Feito",

        "flag_Baixa": "D",
        "flag_srvbaixa": SERVIDOR
    }

    return client.service.insere_Status_Baixa(
        media
    )

# --------------------------------------------------
# PRÓXIMA MÍDIA
# --------------------------------------------------

def proxima_media():

    client = get_client()

    media = serialize_object(
        client.service.ProximaMedia()
    )

    if not media:
        return None

    media_id = media.get("mediaId")

    if not media_id:
        return None

    return media


# --------------------------------------------------
# STATUS PENDENTE
# --------------------------------------------------

def marcar_pendente(
    media_id,
    token
):

    client = get_client()

    media = {
        "mediaId": media_id,
        "token": token,

        "erro_baixa": None,
        "status_baixa": "Pendente",

        "flag_Baixa": "P",
        "flag_srvbaixa": SERVIDOR
    }

    return client.service.insere_Status_Baixa(
        media
    )