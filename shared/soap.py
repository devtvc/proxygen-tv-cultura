from zeep import Client
from zeep.helpers import serialize_object
from zeep.transports import Transport
from requests import Session
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --------------------------------------------------
# CONFIGURAÇÃO
# --------------------------------------------------

# Get WSDL from environment or use default
WSDL = os.getenv("WSDL_URL", "http://172.20.15.190/mam080622/trf_services.asmx?WSDL")
SERVIDOR = os.getenv("SERVIDOR", "A")

# --------------------------------------------------
# CLIENT
# --------------------------------------------------

# Cache global para o cliente SOAP para evitar parsing repetitivo do WSDL
_client_instance = None

def get_client():
    global _client_instance
    
    if _client_instance is not None:
        return _client_instance

    try:
        session = Session()
        # Timeout de conexão aumentado para 20s para dar margem ao WSDL
        transport = Transport(session=session, timeout=20, operation_timeout=60)
        
        print(f"[SOAP] Conectando ao WSDL: {WSDL}...")
        _client_instance = Client(WSDL, transport=transport)
        return _client_instance
    except Exception as e:
        _client_instance = None # Garante tentativa de reconexão na próxima chamada
        print(f"\n[ERRO CRÍTICO SOAP] Não foi possível conectar ao servidor MAM!")
        print(f"URL: {WSDL}")
        print(f"Detalhe: {e}")
        raise

# --------------------------------------------------
# TOKEN
# --------------------------------------------------

def obter_cadastro(media_id) -> dict:
    """Retorna o cadastro completo da mídia no MAM."""
    client = get_client()

    cadastro = serialize_object(
        client.service.carrega_cadastro(media_id)
    )

    if not cadastro:
        raise Exception(
            f"Cadastro não encontrado: {media_id}"
        )

    return dict(cadastro)


def obter_token(media_id) -> int:
    return int(obter_cadastro(media_id)["TOKEN"])

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
# LISTAR FALHAS LEGADO (PesquisarMediaBaixaAlta tipo="F")
# --------------------------------------------------

def listar_falhas_legado() -> list:
    """
    Retorna lista de mídias com flag_Baixa='E' (erro) registradas no MAM legado.
    Usa PesquisarMediaBaixaAlta(tipo='F') — mesmo método e parâmetro do
    aplicativo C# legado (StratusBaixaAlta), que lista a aba "Falhas".
    Resposta rápida (não faz full-scan), sem timeout especial necessário.
    """
    client = get_client()

    result = serialize_object(
        client.service.PesquisarMediaBaixaAlta(tipo='F')
    )

    if not result:
        return []

    return [dict(item) for item in result]


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