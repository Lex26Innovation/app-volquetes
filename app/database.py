from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# URL para SQLite local (cambiaremos a postgresql://... en producción)
SQLALCHEMY_DATABASE_URL = "sqlite:///./volquetes_mvp.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False} # Solo necesario en SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependencia para obtener la sesión de DB en los endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()