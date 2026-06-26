"""
SQLAlchemy models for the broadcast proxy system
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum
from datetime import datetime


Base = declarative_base()


class MediaStatusEnum(str, enum.Enum):
    PENDENTE = "Pendente"
    PROCESSANDO = "Processando"
    CONCLUIDO = "Concluído"
    ERRO = "Erro"
    CANCELADO = "Cancelado"


class JobStatusEnum(str, enum.Enum):
    INICIANDO = "Iniciando"
    PROCESSANDO = "Processando"
    CONCLUIDO = "Concluído"
    ERRO = "Erro"
    CANCELADO = "Cancelado"


class EventTypeEnum(str, enum.Enum):
    MEDIA_DESCOBERTA = "MEDIA_DESCOBERTA"
    RESERVADA = "RESERVADA"
    ENCODE_INICIADO = "ENCODE_INICIADO"
    ENCODE_CANCELADO = "ENCODE_CANCELADO"
    ENCODE_CONCLUIDO = "ENCODE_CONCLUIDO"
    ERRO = "ERRO"


class Media(Base):
    """
    Table for storing media information
    """
    __tablename__ = "medias"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(String(100), unique=True, index=True, nullable=False)
    titulo = Column(Text, nullable=True)
    tipo = Column(String(10))
    duracao = Column(String(20))  # HH:MM:SS.ms
    arquivo_origem = Column(Text)
    arquivo_proxy = Column(Text)
    status = Column(String(20), default=MediaStatusEnum.PENDENTE.value)
    token = Column(Integer, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())


class Job(Base):
    """
    Table for tracking encoding jobs
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default=JobStatusEnum.INICIANDO.value)
    inicio = Column(DateTime(timezone=True))
    fim = Column(DateTime(timezone=True), nullable=True)
    percentual = Column(Integer, default=0)
    worker = Column(String(100), nullable=True)
    mensagem = Column(Text, nullable=True)


class Event(Base):
    """
    Table for storing media processing events
    """
    __tablename__ = "eventos"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(String(100), nullable=False, index=True)
    tipo_evento = Column(String(50), nullable=False)
    descricao = Column(Text)
    data_hora = Column(DateTime(timezone=True), server_default=func.now())


class FilaManual(Base):
    """
    Tabela para armazenar proxies solicitados manualmente pelo usuário.
    Estes itens têm prioridade sobre a fila SOAP normal.
    """
    __tablename__ = "fila_manual"

    id = Column(Integer, primary_key=True, index=True)
    media_id = Column(String(100), nullable=False, index=True)
    # Pendente / Aguardando / Processando / Concluído / Erro
    # "Aguardando" = reservado pelo worker, na fila do executor, ainda não codificando.
    status = Column(String(20), default="Pendente")
    tentativas = Column(Integer, default=0)  # nº de tentativas já consumidas (falhas transitórias)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())
    mensagem = Column(Text, nullable=True)


# For backward compatibility with existing code, we can also add a Logs table
class Log(Base):
    """
    Table for structured logging
    """
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    nivel = Column(String(20))  # INFO, WARNING, ERROR, DEBUG
    modulo = Column(String(100))  # api, worker, soap, etc.
    mensagem = Column(Text)
    dados_adicionais = Column(Text, nullable=True)  # JSON string for additional data
    timestamp = Column(DateTime(timezone=True), server_default=func.now())