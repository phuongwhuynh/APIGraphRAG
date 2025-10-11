"""
Todo database model
Represents todos in the database (in-memory for now)
"""

from datetime import datetime
from enum import Enum
from typing import Optional


class TodoStatus(str, Enum):
    """Todo status enumeration"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TodoPriority(str, Enum):
    """Todo priority enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Todo:
    """
    Todo model - represents a todo item
    In production, this would be a SQLAlchemy model
    """

    def __init__(
        self,
        id: int,
        title: str,
        description: Optional[str] = None,
        status: TodoStatus = TodoStatus.PENDING,
        priority: TodoPriority = TodoPriority.MEDIUM,
        tags: Optional[list[str]] = None,
        created_by: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ):
        self.id = id
        self.title = title
        self.description = description
        self.status = status
        self.priority = priority
        self.tags = tags or []
        self.created_by = created_by
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()
        self.completed_at = completed_at

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, TodoStatus) else self.status,
            "priority": self.priority.value if isinstance(self.priority, TodoPriority) else self.priority,
            "tags": self.tags,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at and isinstance(self.completed_at, datetime) else self.completed_at,
        }
