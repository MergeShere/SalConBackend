import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


database_url = settings.DATABASE_URL

print(f" DEBUG: DATABASE_URL exists: {bool(database_url)}")

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)


engine_args = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True, 
    "pool_size": 10,       
    "max_overflow": 20,    
    "pool_recycle": 1800   
}

if not database_url:
    
    database_url = "sqlite:///./salon_connect.db"
    print(" Development: Using SQLite")
    engine_args = {"connect_args": {"check_same_thread": False}}
else:
    print(" Production: Using PostgreSQL")


engine = create_engine(database_url, **engine_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()