"""
SQLAlchemy database model for Todo
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from ...database import Base


class TodoDB(Base):
    """
    SQLAlchemy model for Todo items in the database
    """

    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    priority = Column(String(10), default="medium", nullable=False)
    tags = Column(Text, nullable=True)
    created_by = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Todo(id={self.id}, title='{self.title}', status='{self.status}')>"

    def to_dict(self):
        """Convert database model to dictionary"""
        from ..models.todo import TodoStatus, TodoPriority

        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": TodoStatus(self.status),
            "priority": TodoPriority(self.priority),
            "tags": self.tags.split(",") if self.tags else [],
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }
