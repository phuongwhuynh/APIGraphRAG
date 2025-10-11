"""
Todo service - business logic for todo operations
Handles the coordination between routers and data storage
"""

from datetime import datetime
from typing import Optional
from fastapi import HTTPException

from ..models.todo import Todo, TodoStatus, TodoPriority
from ..schemas.todo import TodoCreate, TodoUpdate, TodoStats


class TodoService:
    """Service for todo business logic"""

    def __init__(self, db: dict[int, Todo]):
        """
        Initialize service with database

        Args:
            db: Dictionary storing todos (in-memory database)
        """
        self.db = db
        self._next_id = max(db.keys(), default=0) + 1

    def get_all_todos(
        self,
        skip: int = 0,
        limit: int = 10,
        status: Optional[TodoStatus] = None,
        priority: Optional[TodoPriority] = None,
        search: Optional[str] = None
    ) -> tuple[list[Todo], int]:
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
        todos = list(self.db.values())

        # Apply filters
        if status:
            todos = [t for t in todos if t.status == status]
        if priority:
            todos = [t for t in todos if t.priority == priority]
        if search:
            search_lower = search.lower()
            todos = [
                t for t in todos
                if search_lower in t.title.lower()
                or (t.description and search_lower in t.description.lower())
            ]

        # Sort by updated_at descending
        todos.sort(key=lambda x: x.updated_at, reverse=True)

        total = len(todos)
        return todos[skip : skip + limit], total

    def get_todo_by_id(self, todo_id: int) -> Todo:
        """
        Get a todo by ID

        Args:
            todo_id: Todo ID

        Returns:
            Todo object

        Raises:
            HTTPException: If todo not found
        """
        todo = self.db.get(todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
        return todo

    def create_todo(self, todo_data: TodoCreate) -> Todo:
        """
        Create a new todo

        Args:
            todo_data: Todo creation data

        Returns:
            Created todo
        """
        todo = Todo(
            id=self._next_id,
            title=todo_data.title,
            description=todo_data.description,
            priority=todo_data.priority,
            tags=todo_data.tags,
            created_by=todo_data.created_by,
        )

        self.db[todo.id] = todo
        self._next_id += 1
        return todo

    def update_todo(self, todo_id: int, todo_data: TodoUpdate) -> Todo:
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

        # Update fields if provided
        update_dict = todo_data.model_dump(exclude_unset=True)

        for field, value in update_dict.items():
            setattr(todo, field, value)

        # Handle status change to completed
        if "status" in update_dict:
            if update_dict["status"] == TodoStatus.COMPLETED:
                todo.completed_at = datetime.utcnow()
            elif todo.status != TodoStatus.COMPLETED:
                todo.completed_at = None

        todo.updated_at = datetime.utcnow()
        return todo

    def delete_todo(self, todo_id: int) -> None:
        """
        Delete a todo

        Args:
            todo_id: Todo ID

        Raises:
            HTTPException: If todo not found
        """
        if todo_id not in self.db:
            raise HTTPException(status_code=404, detail=f"Todo {todo_id} not found")
        del self.db[todo_id]

    def delete_completed_todos(self) -> int:
        """
        Delete all completed todos

        Returns:
            Number of deleted todos
        """
        completed_ids = [
            todo.id for todo in self.db.values()
            if todo.status == TodoStatus.COMPLETED
        ]

        for todo_id in completed_ids:
            del self.db[todo_id]

        return len(completed_ids)

    def get_statistics(self) -> TodoStats:
        """
        Get todo statistics

        Returns:
            TodoStats object
        """
        todos = list(self.db.values())
        total = len(todos)

        # Count by status
        by_status = {}
        for status in TodoStatus:
            by_status[status.value] = sum(1 for t in todos if t.status == status)

        # Count by priority
        by_priority = {}
        for priority in TodoPriority:
            by_priority[priority.value] = sum(1 for t in todos if t.priority == priority)

        # Count completed today
        today = datetime.utcnow().date()
        completed_today = sum(
            1 for t in todos
            if t.completed_at and t.completed_at.date() == today
        )

        return TodoStats(
            total=total,
            by_status=by_status,
            by_priority=by_priority,
            completed_today=completed_today,
        )
