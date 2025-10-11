"""
FastAPI dependencies
Handles dependency injection for services
"""

from ..services.todo_service import TodoService
from ..database import todos_db


def get_todo_service() -> TodoService:
    """
    Get TodoService instance with database dependency

    Returns:
        TodoService instance
    """
    return TodoService(db=todos_db)
