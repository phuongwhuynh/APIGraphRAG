"""
Todo service - business logic for todo operations
Handles the coordination between routers and database using SQLAlchemy
"""

from datetime import datetime
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models.todo import TodoStatus, TodoPriority
from ..models.todo_db import TodoDB
from ..schemas.todo import TodoCreate, TodoUpdate, TodoStats


class TodoService:
    """Service for todo business logic with SQLite database"""

    def __init__(self, db: Session):
        """
        Initialize service with database session

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def get_all_todos(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[TodoStatus] = None,
        priority: Optional[TodoPriority] = None,
        search: Optional[str] = None
    ) -> tuple[list[TodoDB], int]:
        """
        Get all todos with optional filtering

        Args:
            skip: Number of items to skip
            limit: Maximum number of items to return
            status: Filter by status
            priority: Filter by priority
            search: Search in title and description

        Returns:
            Tuple of (list of todos, total count)
        """
        query = self.db.query(TodoDB)

        if status:
            query = query.filter(TodoDB.status == status.value)
        if priority:
            query = query.filter(TodoDB.priority == priority.value)
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (TodoDB.title.ilike(search_pattern)) |
                (TodoDB.description.ilike(search_pattern))
            )

        total = query.count()
        todos = query.order_by(TodoDB.updated_at.desc()).offset(skip).limit(limit).all()

        return todos, total

    def get_todo_by_id(self, todo_id: int) -> TodoDB:
        """
        Get a todo by ID

        Args:
            todo_id: Todo ID

        Returns:
            Todo object

        Raises:
            HTTPException: If todo not found
        """
        todo = self.db.query(TodoDB).filter(TodoDB.id == todo_id).first()
        if not todo:
            raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
        return todo

    def create_todo(self, todo_data: TodoCreate) -> TodoDB:
        """
        Create a new todo

        Args:
            todo_data: Todo creation data

        Returns:
            Created todo
        """
        tags_str = ",".join(todo_data.tags) if todo_data.tags else None

        todo = TodoDB(
            title=todo_data.title,
            description=todo_data.description,
            priority=todo_data.priority.value,
            tags=tags_str,
            created_by=todo_data.created_by,
        )

        self.db.add(todo)
        self.db.commit()
        self.db.refresh(todo)
        return todo

    def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> TodoDB:
        """
        Update an existing todo

        Args:
            todo_id: Todo ID
            todo_data: Update data

        Returns:
            Updated todo

        Raises:
            HTTPException: If todo not found
        """
        todo = self.get_todo_by_id(todo_id)
        update_dict = todo_data.model_dump(exclude_unset=True)

        for field, value in update_dict.items():
            if field == "status" and value:
                setattr(todo, field, value.value)
                if value == TodoStatus.COMPLETED:
                    todo.completed_at = datetime.utcnow()
                elif todo.status != TodoStatus.COMPLETED.value:
                    todo.completed_at = None
            elif field == "priority" and value:
                setattr(todo, field, value.value)
            elif field == "tags" and value is not None:
                setattr(todo, field, ",".join(value) if value else None)
            elif value is not None:
                setattr(todo, field, value)

        todo.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(todo)
        return todo

    def delete_todo(self, todo_id: int) -> None:
        """
        Delete a todo

        Args:
            todo_id: Todo ID

        Raises:
            HTTPException: If todo not found
        """
        todo = self.get_todo_by_id(todo_id)
        self.db.delete(todo)
        self.db.commit()

    def delete_completed_todos(self) -> int:
        """
        Delete all completed todos

        Returns:
            Number of deleted todos
        """
        result = self.db.query(TodoDB).filter(
            TodoDB.status == TodoStatus.COMPLETED.value
        ).delete()
        self.db.commit()
        return result

    def get_statistics(self) -> TodoStats:
        """
        Get todo statistics

        Returns:
            TodoStats object
        """
        total = self.db.query(TodoDB).count()

        by_status = {}
        for status in TodoStatus:
            count = self.db.query(TodoDB).filter(TodoDB.status == status.value).count()
            by_status[status.value] = count

        by_priority = {}
        for priority in TodoPriority:
            count = self.db.query(TodoDB).filter(TodoDB.priority == priority.value).count()
            by_priority[priority.value] = count

        today = datetime.utcnow().date()
        completed_today = self.db.query(TodoDB).filter(
            TodoDB.status == TodoStatus.COMPLETED.value,
            TodoDB.completed_at != None,
            TodoDB.completed_at >= datetime.combine(today, datetime.min.time())
        ).count()

        return TodoStats(
            total=total,
            by_status=by_status,
            by_priority=by_priority,
            completed_today=completed_today,
        )