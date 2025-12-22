import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, ForeignKey, Integer, String, Text, DateTime, JSON, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


DB_URL = "sqlite:///prompt_history.db"

class Base(DeclarativeBase):
    pass

class Prompt(Base):
    __tablename__ = "prompts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    
    versions: Mapped[List["PromptVersion"]] = relationship(back_populates="prompt")
    
    test_cases: Mapped[List["TestCase"]] = relationship(back_populates="prompt")

class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    
    # Core Data
    template_text: Mapped[str] = mapped_column(Text)  # The actual prompt
    input_schema: Mapped[Optional[dict]] = mapped_column(JSON) # e.g. {"article": "string"}
    
    parent_version_id: Mapped[Optional[int]] = mapped_column(ForeignKey("prompt_versions.id"), nullable=True)
    
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    prompt: Mapped["Prompt"] = relationship(back_populates="versions")

    children: Mapped[List["PromptVersion"]] = relationship(back_populates="parent")
    parent: Mapped[Optional["PromptVersion"]] = relationship(remote_side=[id], back_populates="children")
    evaluation_results: Mapped[List["EvaluationResult"]] = relationship(back_populates="version")


class TestCase(Base):
    __tablename__ = "test_cases"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"))
    
    dataset_slug: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    input_data: Mapped[str] = mapped_column(Text) 
    expected_output: Mapped[str] = mapped_column(Text)
    
    prompt: Mapped["Prompt"] = relationship(back_populates="test_cases")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("prompt_versions.id"))
    

    score: Mapped[float] = mapped_column(Float)
    pass_count: Mapped[int] = mapped_column(Integer)
    fail_count: Mapped[int] = mapped_column(Integer)
    
    detailed_metrics: Mapped[dict] = mapped_column(JSON) 
    
    run_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    version: Mapped["PromptVersion"] = relationship(back_populates="evaluation_results")

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    print("Initializing Professional Database Schema...")
    Base.metadata.create_all(bind=engine)
    print("Tables created: Prompts, Versions, TestCases, Results.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    init_db()