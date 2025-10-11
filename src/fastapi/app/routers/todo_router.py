"""
Todo router - API endpoints for todo operations
Handles HTTP requests and delegates to service layer
"""

from fastapi import APIRouter, Depends, Query, status
from typing import Optional, Annotated

from ..schemas.todo import (
    TodoCreate,
    TodoUpdate,
    TodoResponse,
    TodoListResponse,
    TodoStats,
)
from ..models.todo import TodoStatus, TodoPriority
from ..services.todo_service import TodoService
from ..utils.dependencies import get_todo_service


router = APIRouter(prefix="/todos", tags=["Todos"])


@router.get("", response_model=TodoListResponse, summary="List all todos")
def list_todos(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(10, ge=1, le=100, description="Max items to return"),
    status: Optional[TodoStatus] = Query(None, description="Filter by status"),
    priority: Optional[TodoPriority] = Query(None, description="Filter by priority"),
    search: Optional[str] = Query(None, description="Search in title/description"),
    service: TodoService = Depends(get_todo_service),
):
    """
    Get list of todos with optional filtering and pagination

    - **skip**: Number of items to skip for pagination
    - **limit**: Maximum number of items to return (max 100)
    - **status**: Filter by todo status
    - **priority**: Filter by priority level
    - **search**: Search text in title and description
    """
    todos, total = service.get_all_todos(
        skip=skip, limit=limit, status=status, priority=priority, search=search
    )

    return TodoListResponse(
        items=[TodoResponse(**todo.to_dict()) for todo in todos],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/statistics", response_model=TodoStats, summary="Get todo statistics")
def get_statistics(service: TodoService = Depends(get_todo_service)):
    """
    Get statistics about todos

    Returns counts grouped by:
    - Status
    - Priority
    - Completed today
    """
    return service.get_statistics()


@router.get("/{todo_id}", response_model=TodoResponse, summary="Get todo by ID")
def get_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
):
    """
    Get a specific todo by ID

    - **todo_id**: Unique identifier of the todo
    """
    todo = service.get_todo_by_id(todo_id)
    return TodoResponse(**todo.to_dict())


@router.post(
    "",
    response_model=TodoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new todo",
)
def create_todo(
    todo_data: TodoCreate,
    service: TodoService = Depends(get_todo_service),
):
    """
    Create a new todo

    - **title**: Todo title (required, 1-200 characters)
    - **description**: Optional description (max 2000 characters)
    - **priority**: Priority level (low/medium/high)
    - **tags**: List of tags for categorization
    - **created_by**: Creator email or username
    """
    todo = service.create_todo(todo_data)
    return TodoResponse(**todo.to_dict())


@router.put("/{todo_id}", response_model=TodoResponse, summary="Update a todo")
def update_todo(
    todo_id: int,
    todo_data: TodoUpdate,
    service: TodoService = Depends(get_todo_service),
):
    """
    Update an existing todo

    - **todo_id**: Unique identifier of the todo
    - All fields are optional - only provided fields will be updated
    """
    todo = service.update_todo(todo_id, todo_data)
    return TodoResponse(**todo.to_dict())


@router.delete(
    "/{todo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a todo",
)
def delete_todo(
    todo_id: int,
    service: TodoService = Depends(get_todo_service),
):
    """
    Delete a specific todo

    - **todo_id**: Unique identifier of the todo to delete
    """
    service.delete_todo(todo_id)


@router.delete("", status_code=status.HTTP_200_OK, summary="Delete completed todos")
def delete_completed_todos(service: TodoService = Depends(get_todo_service)):
    """
    Delete all todos with 'completed' status

    Returns the number of deleted items
    """
    deleted_count = service.delete_completed_todos()
    return {
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} completed todo(s)",
    }
