from sqlalchemy import create_engine, Column, String, DateTime, JSON, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    type = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    result_path = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)


class Run(Base):
    __tablename__ = "runs"
    id = Column(String, primary_key=True)
    data_job_id = Column(String, nullable=True)
    algorithm = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    model_path = Column(String, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    hyperparams = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)


class Backtest(Base):
    __tablename__ = "backtests"
    id = Column(String, primary_key=True)
    run_id = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    test_start = Column(String, nullable=True)
    test_end = Column(String, nullable=True)
    result_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)


def create_tables():
    Base.metadata.create_all(bind=engine)
