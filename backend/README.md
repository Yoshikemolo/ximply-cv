# XIMPLY Vision Backend

FastAPI backend for the XIMPLY Vision computer vision application.

## Technology Stack

- Python 3.11+
- FastAPI
- SQLAlchemy (async)
- PostgreSQL
- MinIO (S3-compatible storage)
- PyTorch / Ultralytics (YOLO)
- OpenCV

## Setup

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 16
- MinIO

### Installation

1. Create virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
# Development
pip install -e ".[dev]"

# With ML models
pip install -e ".[dev,ml]"
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your settings
```

4. Run migrations:
```bash
alembic upgrade head
```

5. Start development server:
```bash
uvicorn app.main:app --reload
```

## API Documentation

- Swagger UI: http://localhost:8000/api/v1/docs
- ReDoc: http://localhost:8000/api/v1/redoc

## Project Structure

```
backend/
├── app/
│   ├── api/           # REST API routes
│   ├── core/          # Configuration, security, database
│   ├── models/        # Pydantic schemas, SQLAlchemy entities
│   ├── services/      # Business logic
│   ├── utils/         # Utility functions
│   └── workers/       # Background tasks
├── tests/             # Test files
├── alembic/           # Database migrations
└── pyproject.toml     # Dependencies
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=app

# Specific tests
pytest -k "test_auth"
```

## Code Quality

```bash
# Format code
black app tests

# Lint
ruff check app tests

# Type check
mypy app
```
