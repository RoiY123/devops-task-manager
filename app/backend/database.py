from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/task_manager"

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "connect_timeout": 5,
    },
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

def check_database_connection():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()