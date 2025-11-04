"""
FastAPI dependencies
Handles dependency injection for services
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from ..services.todo_service import TodoService
from ...database import get_db


def get_todo_service(db: Session = Depends(get_db)) -> TodoService:
    """
    Get TodoService instance with database dependency

    Args:
        db: SQLAlchemy database session

    Returns:
        TodoService instance
    """
    return TodoService(db=db)
