"""
SQLite database configuration using SQLAlchemy
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DB_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, 'todos.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependency to get database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables
    """
    from .app.models.todo_db import TodoDB

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if db.query(TodoDB).count() == 0:
            initialize_sample_data(db)
    finally:
        db.close()


def initialize_sample_data(db):
    """Initialize database with sample data"""
    from datetime import datetime
    from app.models.todo_db import TodoDB

    sample_todos = [
        TodoDB(
            title="Complete project documentation",
            description="Write comprehensive API documentation",
            status="in_progress",
            priority="high",
            tags="documentation,urgent",
            created_by="john@example.com",
            created_at=datetime(2025, 10, 11, 9, 0, 0),
            updated_at=datetime(2025, 10, 11, 10, 30, 0),
        ),
        TodoDB(
            title="Review pull requests",
            description="Check and approve pending PRs",
            status="completed",
            priority="medium",
            tags="code-review,team",
            created_by="jane@example.com",
            created_at=datetime(2025, 10, 11, 8, 30, 0),
            updated_at=datetime(2025, 10, 11, 10, 15, 0),
            completed_at=datetime(2025, 10, 11, 10, 15, 0),
        ),
        TodoDB(
            title="Buy groceries",
            description="Milk, eggs, bread",
            status="pending",
            priority="low",
            tags="personal,shopping",
            created_by="john@example.com",
            created_at=datetime(2025, 10, 11, 7, 0, 0),
            updated_at=datetime(2025, 10, 11, 7, 0, 0),
        ),
    ]

    for todo in sample_todos:
        db.add(todo)

    db.commit()
