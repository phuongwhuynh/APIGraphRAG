"""
Todo schemas - Pydantic models for validation
Used for API request/response validation
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from ..models.todo import TodoStatus, TodoPriority


class TodoCreate(BaseModel):
    """Schema for creating a todo"""
    title: str = Field(..., min_length=1, max_length=200, description="Todo title")
    description: Optional[str] = Field(None, max_length=2000, description="Todo description")
    priority: TodoPriority = Field(default=TodoPriority.MEDIUM, description="Priority level")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    created_by: Optional[str] = Field(None, description="Creator email or username")

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Complete project documentation",
                "description": "Write API docs with examples",
                "priority": "high",
                "tags": ["documentation", "urgent"],
                "created_by": "john@example.com"
            }
        }
    }


class TodoUpdate(BaseModel):
    """Schema for updating a todo"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[TodoStatus] = None
    priority: Optional[TodoPriority] = None
    tags: Optional[list[str]] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Complete and review project documentation",
                "status": "in_progress",
                "priority": "high"
            }
        }
    }


class TodoResponse(BaseModel):
    """Schema for todo response"""
    id: int
    title: str
    description: Optional[str]
    status: TodoStatus
    priority: TodoPriority
    tags: list[str]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": 1,
                "title": "Complete project documentation",
                "description": "Write API docs with examples",
                "status": "in_progress",
                "priority": "high",
                "tags": ["documentation", "urgent"],
                "created_by": "john@example.com",
                "created_at": "2025-10-11T09:00:00",
                "updated_at": "2025-10-11T10:30:00",
                "completed_at": None
            }
        }
    }


class TodoListResponse(BaseModel):
    """Schema for paginated todo list"""
    items: list[TodoResponse]
    total: int
    skip: int
    limit: int


class TodoStats(BaseModel):
    """Schema for todo statistics"""
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    completed_today: int
