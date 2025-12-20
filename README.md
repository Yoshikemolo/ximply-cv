# XIMPLY Vision

A computer vision application for real-time object detection, recognition, and catalog management.

## Features

- **View**: Real-time object detection from camera feeds with confidence percentages
- **Learn**: Train custom objects with rich metadata (name, description, weight, dimensions, price, reference, color, materials)
- **Catalog**: Manage and organize detected objects with full CRUD operations
- **Admin**: User management with role-based access control (RBAC)

## Technology Stack

### Backend
- Python 3.11+
- FastAPI
- PyTorch / Ultralytics (YOLO)
- OpenCV
- PostgreSQL
- MinIO (Object Storage)
- JWT Authentication

### Frontend
- Angular 19
- TypeScript
- SCSS (Dark/Light themes)
- i18n (English/Spanish)

### Infrastructure
- Docker / Docker Compose
- PostgreSQL 16
- MinIO
- Nginx

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Node.js 20+ (for local frontend development)
- Python 3.11+ (for local backend development)

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/your-org/ximply-vision.git
cd ximply-vision
```

2. Copy environment files:
```bash
cp .env.development.example .env
```

3. Start services:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

4. Access the application:
- Frontend: http://localhost:4200
- API Docs: http://localhost:8000/docs
- MinIO Console: http://localhost:9001

### Local Development

#### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

#### Frontend
```bash
cd frontend
npm install
ng serve
```

## Project Structure

```
computer-vision/
├── backend/          # FastAPI Python backend
├── frontend/         # Angular 19 frontend
├── docker/           # Docker configurations
├── doc/              # Documentation
├── planning/         # Project planning and milestones
├── postman/          # API collection
└── models/           # ML model weights
```

## Documentation

- [Architecture](doc/infrastructure/architecture.md)
- [API Reference](doc/infrastructure/api.md)
- [Features](doc/features/)
- [Operations](doc/operations/)

## API Versioning

All API endpoints are versioned: `/api/v1/...`

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests: `pytest` (backend) and `ng test` (frontend)
4. Submit a pull request

## License

Proprietary - All rights reserved
