# FastAPI Todo Application

A simple, clean REST API for managing todos built with FastAPI.

## Structure

```
src/fastapi/
├── app/
│   ├── models/          # Data models
│   │   └── todo.py      # Todo model and enums
│   ├── schemas/         # Pydantic schemas
│   │   └── todo.py      # Request/response schemas
│   ├── services/        # Business logic
│   │   └── todo_service.py
│   ├── routers/         # API endpoints
│   │   └── todo_router.py
│   └── utils/           # Utilities
│       └── dependencies.py
├── database.py          # In-memory database
└── main.py             # FastAPI app
```

## Features

- ✅ CRUD operations for todos
- ✅ Status tracking (pending, in_progress, completed, cancelled)
- ✅ Priority levels (low, medium, high)
- ✅ Filtering by status and priority
- ✅ Search in title/description
- ✅ Pagination
- ✅ Statistics endpoint
- ✅ Tags support
- ✅ Auto-generated OpenAPI docs

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Run the App

```bash
cd src/fastapi
python main.py
```

Or with uvicorn:

```bash
uvicorn src.fastapi.main:app --reload
```

### Access

- API: http://localhost:8000
- Swagger Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Todos

- `GET /todos` - List all todos (with filtering & pagination)
- `GET /todos/statistics` - Get todo statistics
- `GET /todos/{id}` - Get specific todo
- `POST /todos` - Create new todo
- `PUT /todos/{id}` - Update todo
- `DELETE /todos/{id}` - Delete todo
- `DELETE /todos` - Delete all completed todos

### Root

- `GET /` - API info
- `GET /health` - Health check

## Usage Examples

### Create Todo

```bash
curl -X POST "http://localhost:8000/todos" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Complete documentation",
    "description": "Write API docs",
    "priority": "high",
    "tags": ["documentation"],
    "created_by": "john@example.com"
  }'
```

### List Todos with Filters

```bash
# Get all todos
curl "http://localhost:8000/todos"

# Get high priority todos
curl "http://localhost:8000/todos?priority=high"

# Get completed todos
curl "http://localhost:8000/todos?status=completed"

# Search todos
curl "http://localhost:8000/todos?search=documentation"
```

### Update Todo

```bash
curl -X PUT "http://localhost:8000/todos/1" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Updated title",
    "status": "completed"
  }'
```

### Get Statistics

```bash
curl "http://localhost:8000/todos/statistics"
```

Response:
```json
{
  "total": 10,
  "by_status": {
    "pending": 4,
    "in_progress": 3,
    "completed": 2,
    "cancelled": 1
  },
  "by_priority": {
    "low": 2,
    "medium": 5,
    "high": 3
  },
  "completed_today": 1
}
```

## Architecture

### Models (`app/models/`)
Data models representing your business entities.

```python
class Todo:
    """Todo model with all fields"""
    id: int
    title: str
    description: Optional[str]
    status: TodoStatus
    priority: TodoPriority
    # ...
```

### Schemas (`app/schemas/`)
Pydantic models for request/response validation.

```python
class TodoCreate(BaseModel):
    """Schema for creating a todo"""
    title: str
    description: Optional[str]
    priority: TodoPriority
```

### Services (`app/services/`)
Business logic layer - handles data operations.

```python
class TodoService:
    def create_todo(self, todo_data: TodoCreate) -> Todo:
        """Create a new todo"""
        # Business logic here
```

### Routers (`app/routers/`)
API endpoints - handles HTTP requests.

```python
@router.post("/todos")
def create_todo(todo_data: TodoCreate, service: TodoService = Depends()):
    """Create todo endpoint"""
    return service.create_todo(todo_data)
```

### Benefits

- **Simple**: Easy to understand and extend
- **Organized**: Clear separation of concerns
- **Practical**: Real-world structure
- **Testable**: Each layer can be tested independently
- **Documented**: Auto-generated OpenAPI docs

## Database

Currently using in-memory storage (`database.py`). To use a real database:

1. Install SQLAlchemy: `pip install sqlalchemy`
2. Replace `database.py` with database connection
3. Update models to use SQLAlchemy ORM
4. Update service to use database session

Example with SQLAlchemy:

```python
# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql://user:pass@localhost/db")
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

## Testing

Create tests using pytest and TestClient:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_create_todo():
    response = client.post("/todos", json={
        "title": "Test Todo",
        "priority": "high"
    })
    assert response.status_code == 201
    assert response.json()["title"] == "Test Todo"
```

## Adding New Features

### Add a new field to Todo

1. Update model in `app/models/todo.py`
2. Update schemas in `app/schemas/todo.py`
3. Update service logic if needed
4. Database migrations (if using SQL)

### Add a new router

1. Create `app/routers/new_router.py`
2. Define endpoints
3. Register in `main.py`:

```python
from app.routers import new_router
app.include_router(new_router.router)
```

## Perfect for Documentation Generation

This codebase is ideal for building an API documentation generator:

- **Clear structure**: Easy to parse
- **Type hints**: Complete annotations
- **Docstrings**: Comprehensive docs
- **Schemas**: Rich Pydantic models
- **OpenAPI**: Auto-generated spec at `/openapi.json`

## License

MIT

## Support

For issues or questions, create an issue on GitHub.
