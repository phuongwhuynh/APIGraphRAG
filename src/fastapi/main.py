"""
FastAPI Todo Application
A simple, clean REST API for managing todos
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import todo_router

# Create FastAPI app
app = FastAPI(
    title="Todo API",
    description="""
    A simple and clean REST API for managing todo items.

    ## Features
    - Create, read, update, and delete todos
    - Filter by status and priority
    - Search functionality
    - Statistics endpoint
    - Pagination support

    ## Architecture
    Simple and practical structure:
    - `models/`: Data models
    - `schemas/`: Pydantic schemas for validation
    - `services/`: Business logic
    - `routers/`: API endpoints
    - `utils/`: Utilities and dependencies
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(todo_router.router)


@app.get("/", tags=["Root"])
def root():
    """
    Root endpoint - API information

    Returns basic API information and links to documentation
    """
    return {
        "message": "Welcome to Todo API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "todos": "/todos",
            "statistics": "/todos/statistics",
        },
    }


@app.get("/health", tags=["Root"])
def health_check():
    """
    Health check endpoint

    Used by monitoring systems to verify service health
    """
    return {"status": "healthy", "service": "todo-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
