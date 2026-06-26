"""
Pydantic schemas for API requests and responses
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MediaBase(BaseModel):
    media_id: str
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    duracao: Optional[str] = None
    arquivo_origem: Optional[str] = None
    arquivo_proxy: Optional[str] = None
    status: Optional[str] = None
    token: Optional[int] = None


class MediaCreate(MediaBase):
    pass


class MediaResponse(MediaBase):
    id: int
    criado_em: datetime
    atualizado_em: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobBase(BaseModel):
    media_id: str
    status: Optional[str] = None
    inicio: Optional[datetime] = None
    fim: Optional[datetime] = None
    percentual: Optional[int] = None
    worker: Optional[str] = None
    mensagem: Optional[str] = None


class JobCreate(JobBase):
    pass


class JobResponse(JobBase):
    id: Optional[int] = None  # None para entradas do MAM legado (sem registro local)
    # Campos enriquecidos via JOIN com medias (populados pela API, não pelo ORM)
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    duracao: Optional[str] = None

    class Config:
        from_attributes = True


class EventBase(BaseModel):
    media_id: str
    tipo_evento: str
    descricao: Optional[str] = None
    data_hora: Optional[datetime] = None


class EventCreate(EventBase):
    pass


class EventResponse(EventBase):
    id: int

    class Config:
        from_attributes = True


# Statistics schemas
class StatsResponse(BaseModel):
    workers: int
    ativos: int
    concluidos: int
    erros: int          # erros locais + erros MAM legado
    erros_legado: int   # só erros MAM legado (para referência)


# Job action schemas
class JobCancelResponse(BaseModel):
    ok: bool
    erro: Optional[str] = None


# Fila Manual schemas
class FilaManualBase(BaseModel):
    media_id: str


class FilaManualCreate(FilaManualBase):
    pass


class FilaManualResponse(FilaManualBase):
    id: int
    status: str
    tentativas: Optional[int] = 0
    criado_em: Optional[datetime] = None
    atualizado_em: Optional[datetime] = None
    mensagem: Optional[str] = None
    # Campos enriquecidos via JOIN com medias
    titulo: Optional[str] = None
    tipo: Optional[str] = None
    duracao: Optional[str] = None

    class Config:
        from_attributes = True