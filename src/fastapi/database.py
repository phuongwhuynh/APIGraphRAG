"""
In-memory database for todos
In production, replace with actual database (PostgreSQL, MongoDB, etc.)
"""

from datetime import datetime
from app.models.todo import Todo, TodoStatus, TodoPriority


# In-memory database (dictionary)
todos_db: dict[int, Todo] = {}


def initialize_sample_data():
    """Initialize database with sample data"""
    sample_todos = [
        Todo(
            id=1,
            title="Complete project documentation",
            description="Write comprehensive API documentation",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.HIGH,
            tags=["documentation", "urgent"],
            created_by="john@example.com",
            created_at=datetime(2025, 10, 11, 9, 0, 0),
            updated_at=datetime(2025, 10, 11, 10, 30, 0),
        ),
        Todo(
            id=2,
            title="Review pull requests",
            description="Check and approve pending PRs",
            status=TodoStatus.COMPLETED,
            priority=TodoPriority.MEDIUM,
            tags=["code-review", "team"],
            created_by="jane@example.com",
            created_at=datetime(2025, 10, 11, 8, 30, 0),
            updated_at=datetime(2025, 10, 11, 10, 15, 0),
            completed_at=datetime(2025, 10, 11, 10, 15, 0),
        ),
        Todo(
            id=3,
            title="Buy groceries",
            description="Milk, eggs, bread",
            status=TodoStatus.PENDING,
            priority=TodoPriority.LOW,
            tags=["personal", "shopping"],
            created_by="john@example.com",
            created_at=datetime(2025, 10, 11, 7, 0, 0),
            updated_at=datetime(2025, 10, 11, 7, 0, 0),
        ),
    ]

    for todo in sample_todos:
        todos_db[todo.id] = todo


# Initialize on module import
initialize_sample_data()
