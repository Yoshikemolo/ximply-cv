# XIMPLY Vision - System Architecture

## Overview

XIMPLY Vision is a computer vision application built with a modern
microservices-oriented architecture, featuring a Python backend, Angular
frontend, and supporting services for storage, database and an optional message
broker.

## System Components

```
+-------------------+     +-------------------+     +-------------------+
|                   |     |                   |     |                   |
|    Frontend       |     |    Backend API    |     |    PostgreSQL     |
|    (Angular 19)   +---->+    (FastAPI)      +---->+    Database       |
|                   |     |                   |     |                   |
+-------------------+     +--------+----------+     +-------------------+
                                   |
                     +-------------+-------------+
                     |                           |
            +--------+----------+       +--------+----------+
            |                   |       |                   |
            |    MinIO          |       |    Mosquitto      |
            |    (S3 Storage)   |       |    (MQTT broker)  |
            |                   |       |                   |
            +-------------------+       +-------------------+
```

The broker is optional and off by default. Nothing else in the stack changes
when it is absent.

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
- Live streaming to subscribers (SSE and multipart JPEG)
- Publishing events to the MQTT broker, when one is configured

**Key Features:**
- Async-first design
- OpenAPI documentation
- SSE for real-time events
- Role-based access control
- GPU acceleration support

**Streaming components:**
- `StreamHub` - the in-process fan-out. Bounded queues per owner for events and
  per owner and camera for frames. It holds one frame per camera and overwrites
  it, and a full queue drops its oldest entry rather than blocking the caller
- `MqttPublisher` - owns the broker connection and a bounded outbound queue,
  filled from the detection path and drained by one background task, so a broker
  that is slow or unreachable costs memory and no detection latency

Streaming added no table and no column. The hub, the queues and the broker
connection are per worker and held in memory, like the protocol switch and the
acceleration preference, and the subscriber count on a camera is computed when
the state is read rather than stored. Several workers therefore mean several
hubs and several broker connections, each publishing what its own requests
raised.

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

### MQTT Broker (Optional)

**Technology:** Eclipse Mosquitto

**Responsibilities:**
- Carrying event records to subscribers that connect rather than receive
- Carrying event captures and live camera frames, when those are enabled
- Reporting whether this instance is online, on a retained last will topic

The broker runs behind a Compose profile and is off by default. With
`MQTT_ENABLED` false the publisher never starts, the HTTP stream still works,
and the rest of the application does not know the difference. It is a separate
process with its own accounts, its own access rules and its own log, so what
must be configured before its port leaves the machine is in
[SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

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

### Streaming Flow
```
1. Detection raises an event and dispatches its webhooks
2. Backend hands the same record to the stream hub and to the broker queue
3. Hub writes it to every open event stream belonging to that owner
4. Publisher task writes it to the broker topic for that owner and type
5. Frames follow the same path, and are encoded only while somebody is watching
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
              +------------+------------+
              |                         |
       +------+------+           +------+------+
       |    MinIO    |           |  Mosquitto  |
       |   (Docker)  |           |  (optional) |
       |  :9000/9001 |           |  :1883      |
       +-------------+           +-------------+
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
    +-----+-----+                    +------+------+     +--------------+
    |  Frontend |                    |   Backend   +---->+  Mosquitto   |
    |  (Nginx)  |                    | (Uvicorn)   |     |  (optional)  |
    |   x 2     |                    |   x 2       |     +--------------+
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
- Streaming state is per worker: a subscriber reaches the hub of the worker that
  served its request, and each worker holds its own broker connection

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
