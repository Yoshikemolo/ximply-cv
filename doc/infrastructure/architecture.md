# XIMPLY Vision - System Architecture

## Overview

XIMPLY Vision is a computer vision application built with a modern microservices-oriented architecture, featuring a Python backend, Angular frontend, and supporting services for storage and database.

## System Components

```
+-------------------+     +-------------------+     +-------------------+
|                   |     |                   |     |                   |
|    Frontend       |     |    Backend API    |     |    PostgreSQL     |
|    (Angular 19)   +---->+    (FastAPI)      +---->+    Database       |
|                   |     |                   |     |                   |
+-------------------+     +--------+----------+     +-------------------+
                                   |
                                   v
                          +--------+----------+
                          |                   |
                          |    MinIO          |
                          |    (S3 Storage)   |
                          |                   |
                          +-------------------+
```

## Component Details

### Frontend (Angular 19)

**Technology:** Angular 19, TypeScript, SCSS

**Responsibilities:**
- User interface rendering
- Client-side routing
- State management (Signals)
- API communication
- Camera access (WebRTC)
- Real-time updates (SSE)

**Key Features:**
- Standalone components
- Dark/Light theme support
- Internationalization (en/es)
- Responsive design
- PWA support (future)

### Backend API (FastAPI)

**Technology:** Python 3.11+, FastAPI, SQLAlchemy, PyTorch

**Responsibilities:**
- REST API endpoints
- Authentication (JWT)
- Business logic
- Database operations
- Object detection (YOLO)
- Model training
- File storage management

**Key Features:**
- Async-first design
- OpenAPI documentation
- SSE for real-time events
- Role-based access control
- GPU acceleration support

### PostgreSQL Database

**Technology:** PostgreSQL 16

**Responsibilities:**
- User data storage
- Object catalog storage
- Role and permission storage
- Detection history
- Training job tracking

**Schema Overview:**
- users - User accounts
- roles - User roles
- permissions - Granular permissions
- objects - Catalog objects
- object_images - Training images
- categories - Object categories
- detection_logs - Detection history

### MinIO Object Storage

**Technology:** MinIO (S3-compatible)

**Responsibilities:**
- Image storage
- Model weight storage
- Training data storage
- Thumbnail storage

**Bucket Structure:**
```
ximply-vision/
  objects/{object_id}/
    images/{image_id}.jpg
    thumbnails/{image_id}_thumb.jpg
  training/{object_id}/
    data/
    checkpoints/
  models/
    base/
    custom/{object_id}/
```

## Data Flow

### Authentication Flow
```
1. User submits credentials
2. Backend validates credentials
3. Backend generates JWT tokens
4. Frontend stores tokens
5. Frontend includes token in API requests
6. Backend validates token on each request
```

### Object Detection Flow
```
1. Frontend captures camera frame
2. Frontend sends frame to backend (or processes locally)
3. Backend runs YOLO detection
4. Backend matches against custom models
5. Backend sends results via SSE
6. Frontend renders bounding boxes
```

### Object Learning Flow
```
1. User captures/uploads images
2. Frontend sends images to backend
3. Backend stores in MinIO
4. User initiates training
5. Backend queues training job
6. Backend fine-tunes model
7. Backend saves model weights
8. Object status updates to active
```

## Deployment Architecture

### Development
```
+-------------+     +-------------+     +-------------+
|  Frontend   |     |   Backend   |     | PostgreSQL  |
|  (ng serve) |     | (uvicorn)   |     | (Docker)    |
|  :4200      |     |  :8000      |     |  :5432      |
+-------------+     +-------------+     +-------------+
                           |
                    +------+------+
                    |    MinIO    |
                    |   (Docker)  |
                    |  :9000/9001 |
                    +-------------+
```

### Production
```
                    +-------------+
                    |   Nginx     |
                    | (Reverse    |
                    |  Proxy)     |
                    +------+------+
                           |
          +----------------+----------------+
          |                                 |
    +-----+-----+                    +------+------+
    |  Frontend |                    |   Backend   |
    |  (Nginx)  |                    | (Uvicorn)   |
    |   x 2     |                    |   x 2       |
    +-----------+                    +------+------+
                                            |
              +-------------+---------------+
              |                             |
       +------+------+              +-------+------+
       | PostgreSQL  |              |    MinIO     |
       +-------------+              +--------------+
```

## Security Architecture

### Authentication
- JWT Bearer tokens
- Access token: 15-30 min expiry
- Refresh token: 7 days expiry
- Password hashing: bcrypt

### Authorization
- Role-Based Access Control (RBAC)
- Permissions embedded in JWT
- Route guards on frontend
- Middleware checks on backend

### Data Protection
- HTTPS in production
- Environment-based secrets
- Non-root Docker containers
- Input validation (Pydantic)

## Scalability Considerations

### Horizontal Scaling
- Stateless backend design
- Session-less authentication (JWT)
- Shared database and storage
- Load balancer ready

### Vertical Scaling
- GPU support for detection
- Connection pooling for database
- Async I/O for concurrent requests
- Background job processing

## Monitoring and Logging

### Health Checks
- `/api/v1/health` - Full health status
- `/api/v1/health/live` - Liveness probe
- `/api/v1/health/ready` - Readiness probe

### Logging
- Structured JSON logging
- Request/response logging
- Error tracking
- Performance metrics

## Future Considerations

- Kubernetes deployment
- Redis for caching
- Celery for background tasks
- Elasticsearch for search
- Prometheus/Grafana monitoring
