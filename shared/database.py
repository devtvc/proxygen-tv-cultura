"""
Database connection and session management
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database URL from environment variables
user = os.getenv('POSTGRES_USER', 'broadcast')
password = os.getenv('POSTGRES_PASSWORD', 'pass123')
host = os.getenv('POSTGRES_HOST', 'localhost')
port = os.getenv('POSTGRES_PORT', '5432')
db_name = os.getenv('POSTGRES_DB', 'broadcast_db')

DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

# Create engine — timezone forçado para America/Sao_Paulo em todas as sessões
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    connect_args={"options": "-c timezone=America/Sao_Paulo"}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """
    Dependency to get DB session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """
    Create all tables in the database
    """
    from shared.models import Base
    Base.metadata.create_all(bind=engine)
    _sync_schema()


def _sync_schema():
    """
    Ajustes idempotentes de schema para bancos já existentes (sem migração manual).
    create_all() não altera tabelas pré-existentes, então colunas novas são
    adicionadas aqui de forma segura para o ambiente 24/7.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE fila_manual ADD COLUMN IF NOT EXISTS tentativas INTEGER DEFAULT 0",
        "ALTER TABLE medias ADD COLUMN IF NOT EXISTS titulo TEXT",
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as ex:
                print(f"[DB] Aviso ao sincronizar schema ({stmt}): {ex}")