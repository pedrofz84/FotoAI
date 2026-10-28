from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config.settings import settings

SQLALCHEMY_DATABASE_URL = f"sqlite:///{settings.DB_PATH}"

# check_same_thread=False é vital quando usado via FastAPI (Threads concorrentes)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def ensure_columns():
    """
    O create_all só cria tabelas novas; não acrescenta colunas a tabelas que já existem.
    Aqui acrescentam-se as colunas novas às bases criadas por versões anteriores.
    """
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    val = col.default.arg
                    default = f" DEFAULT '{val}'" if isinstance(val, str) else f" DEFAULT {val}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}{default}'))
            for idx in table.indexes:
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS "{idx.name}" ON "{table.name}" '
                    f'({", ".join(c.name for c in idx.columns)})'))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
