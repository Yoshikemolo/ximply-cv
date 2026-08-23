# XIMPLY Vision - Deployment Guide

## Prerequisites

- Docker Engine 24 or later, with the Compose v2 plugin
- A video source: the built in webcam, a USB camera or a capture device
- Roughly 6 GB of disk for images, model weights and volumes, and more if the
  catalog grows
- 8 GB of RAM, since the models are held in memory once loaded
- For production: a domain name and a certificate
- Optionally an NVIDIA GPU with the NVIDIA Container Toolkit, which the
  application uses when it finds one. See [GPU deployment](#gpu-deployment)

Related reading:

- [Hardware acceleration](../features/FEAT-0011-hardware-acceleration.md)
- [Streaming](../features/FEAT-0015-streaming.md), and
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md) before running a
  broker or enabling live frames
- [Security decisions](../sec/README.md), and in particular what must change
  before exposing the stack
- [System architecture](../infrastructure/architecture.md)

## Development Deployment

### Quick Start

1. Clone the repository:
```bash
git clone https://github.com/your-org/ximply-vision.git
cd ximply-vision
```

2. Create environment file:
```bash
cp .env.development.example .env
```

3. Start services:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

4. Verify services:
```bash
docker-compose ps
```

5. Access application:
- Frontend: http://localhost:4200
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/api/v1/docs
- MinIO Console: http://localhost:9001

### Development Commands

```bash
# View logs
docker-compose logs -f backend

# Rebuild after code changes
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v

# Shell into container
docker-compose exec backend bash
```

## Production Deployment

### Pre-deployment Checklist

Configuration:

- [ ] Domain name configured
- [ ] Certificate obtained. Camera access needs a secure context: on any host
      other than localhost the browser refuses to open the camera over plain HTTP
- [ ] `JWT_SECRET_KEY` generated. With the placeholder in place anyone can mint
      a token for any user with any permission
      ([SEC-0006](../sec/SEC-0006-default-credentials-and-secrets.md))
- [ ] Database and object store credentials changed from the defaults
- [ ] Administrator address changed, and a real password set. Note that the seed
      resets the default account's password on every start
- [ ] Firewall rules configured, and the published ports bound to the loopback
      address rather than every interface
      ([SEC-0007](../sec/SEC-0007-container-hardening.md))
- [ ] Backup strategy defined, covering the database and the object store
- [ ] `CAMERA_VIEW_ENABLED` and `MQTT_ENABLED` left off unless something needs
      them, and the broker port bound to the loopback address if one runs
      ([SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md))

Before any member of the public is recorded:

- [ ] The image proxy authenticated, or replaced with scoped signed URLs
      ([SEC-0003](../sec/SEC-0003-object-storage-exposure.md))
- [ ] A lawful basis, a notice and a retention period decided. The software
      enrols people automatically and has no retention policy of its own
      ([SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md))

### Environment Setup

1. Create production environment file:
```bash
cp .env.production.example .env
```

2. Generate secure secrets:
```bash
# Generate JWT secret
openssl rand -hex 64

# Generate database password
openssl rand -base64 32

# Generate MinIO keys
openssl rand -base64 24
```

3. Update .env with secure values:
```env
DB_PASSWORD=<generated-password>
MINIO_ACCESS_KEY=<generated-key>
MINIO_SECRET_KEY=<generated-secret>
JWT_SECRET_KEY=<generated-64-char-string>
CORS_ORIGINS=["https://your-domain.com"]
```

### Deploy Services

1. Build and start:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

2. Run database migrations:
```bash
docker-compose exec backend alembic upgrade head
```

3. Seed initial data:
```bash
docker-compose exec backend python -m app.core.seed
```

4. Verify deployment:
```bash
curl https://your-domain.com/api/v1/health
```

### Reverse Proxy Setup

If using nginx as external reverse proxy:

```nginx
upstream ximply-frontend {
    server 127.0.0.1:4200;
}

upstream ximply-backend {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/ssl/certs/your-domain.crt;
    ssl_certificate_key /etc/ssl/private/your-domain.key;

    location / {
        proxy_pass http://ximply-frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://ximply-backend/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_buffering off;
    }
}
```

## GPU deployment

Reserving a GPU device fails outright on a machine without one, so it lives in a
separate override rather than the base configuration
([ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md)).

Check the toolkit is in place first:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

Then add the override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Combine it with the development override when needed:

```bash
docker compose -f docker-compose.yml                -f docker-compose.dev.yml                -f docker-compose.gpu.yml up -d --build
```

Confirm what is actually accelerated:

```bash
curl -s http://localhost:8000/api/v1/health/acceleration
```

Each backend is reported separately because they fail independently: a machine
can have a working CUDA runtime for PyTorch while the ONNX runtime installed is
the processor only build. Each carries `supported`, whether this machine could
accelerate it, `enabled`, whether it has been asked to, and `accelerated`, what
is happening. The badge in the application header shows the same state and
opens a panel with a switch per backend.

The override is what puts a device inside the container. Which of the three
backends uses it is decided at runtime, from that panel or with a `PUT` to the
same endpoint, and takes effect on the next frame rather than at the next
restart ([ADR-0018](../adr/ADR-0018-acceleration-assigned-per-backend.md)):

```bash
curl -s -X PUT http://localhost:8000/api/v1/health/acceleration \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"backend": "landmarks", "enabled": true}'
```

Two things to know before relying on it. The preferences are held in memory, so
a restart returns to the defaults and `ACCELERATION_MEDIAPIPE_GPU` is what sets
where the landmark models start. And the service is a singleton per process
while the production override runs four workers, so a change reaches one worker
only: move a backend with a single worker running.

The GPU image additionally installs a C compiler, which the processor only image
does not; the reason is in
[SEC-0007](../sec/SEC-0007-container-hardening.md#accepted-exceptions).

## Model weights

Weights are downloaded from their publishers on first use and cached in named
volumes, so a redeploy is fast and works with no network access once the caches
are warm ([ADR-0011](../adr/ADR-0011-cache-model-weights-in-volumes.md)).

| Volume | Holds |
| --- | --- |
| `ximply-vision-models` | Detection, pose, segmentation and landmark weights |
| `ximply-vision-face-models` | The face recognition bundle |
| `ximply-vision-vlm-models` | The description model |

Deleting a volume forces a re-download, which is the intended way to pick up new
weights. The first request that needs a model pays its download, so the first
detection and the first description of a fresh deployment are slow.

## Streaming

Something can subscribe to this instance instead of running a server for it to
call: an event stream and a live camera stream over HTTP, and the same records
on an MQTT broker. What each transport is for is in
[FEAT-0015](../features/FEAT-0015-streaming.md) and
[ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md);
the endpoints themselves are in
[the API reference](../infrastructure/api.md#streaming).

Live frames and the broker are off in a fresh deployment and are turned on
separately, so a deployment can carry event records live without carrying the
room with them.

### The stream

| Variable | Default | Sets |
| --- | --- | --- |
| `STREAM_ENABLED` | `true` | Whether the stream routes serve at all. Read at startup |
| `STREAM_KEEPALIVE_SECONDS` | `15` | Seconds between comment lines on an idle event stream, so a proxy does not close it |
| `STREAM_QUEUE_SIZE` | `256` | Records held for one subscriber before the oldest is dropped |
| `CAMERA_VIEW_ENABLED` | `false` | Whether a live frame can be reached at all, by any credential |
| `STREAM_CAMERA_MAX_FPS` | `4.0` | Frames a second sent to a viewer, independently of what detection runs at |
| `STREAM_CAMERA_MAX_SIDE` | `640` | Longest side of a streamed frame, in pixels |
| `STREAM_CAMERA_QUALITY` | `70` | JPEG quality of a streamed frame |

Watching a camera also needs `camera:view` written on the token by name. The
three camera settings bound what a viewer costs and what it can see: a
subscriber cannot make the camera capture faster and cannot pull a larger image
than the browser is already sending.

### The broker

| Variable | Default | Sets |
| --- | --- | --- |
| `MQTT_ENABLED` | `false` | Whether the publisher starts and connects. Read at startup |
| `MQTT_HOST` | `mosquitto` | Broker host, which is the Compose service name by default |
| `MQTT_PORT` | `1883` | Broker port |
| `MQTT_USERNAME` | empty | Broker user, if the broker requires one |
| `MQTT_PASSWORD` | empty | Broker password |
| `MQTT_CLIENT_ID` | `ximply-vision` | Client id this instance connects with |
| `MQTT_INSTANCE` | `default` | The instance segment of every topic, so several deployments share one broker |
| `MQTT_TOPIC_PREFIX` | `ximply` | The first segment of every topic |
| `MQTT_PUBLISH_CAPTURES` | `true` | Whether event captures are published as well as the records |
| `MQTT_PUBLISH_FRAMES` | `false` | Whether live camera frames are published. Needs `CAMERA_VIEW_ENABLED` as well |
| `MQTT_KEEPALIVE` | `60` | Seconds between keepalives on the broker connection |
| `MQTT_QUEUE_SIZE` | `512` | Records held for the broker before the oldest is dropped |

`MQTT_ENABLED` is read at startup, so turning the broker on or off is a restart
rather than a switch in the interface.

### Running the broker

The broker service sits behind a Compose profile, so it is not started unless it
is asked for:

```bash
docker compose --profile broker up -d
```

Set `MQTT_ENABLED=true` in `.env` and restart the backend, then check that a
subscriber sees traffic:

```bash
mosquitto_sub -h localhost -p 1883 -v -t 'ximply/default/#'
```

Publish the broker port to the loopback address rather than to every interface,
as with every other port here
([SEC-0007](../sec/SEC-0007-container-hardening.md)):

```yaml
ports:
  - "127.0.0.1:1883:1883"
```

The shipped broker configuration assumes one account on one host: it has no TLS
and no per-owner topic ACL, and the owner id in the topic tree is a shape to
write those rules into rather than a rule this application enforces. Before that
port is reachable from anywhere else, work through what must be in place first
in [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

## Scaling

### Horizontal Scaling

Scale backend replicas:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --scale backend=3
```

### Load Balancing

With multiple backend instances, configure nginx:
```nginx
upstream ximply-backend {
    least_conn;
    server backend_1:8000;
    server backend_2:8000;
    server backend_3:8000;
}
```

## Backup Procedures

### Database Backup

```bash
# Create backup
docker-compose exec db pg_dump -U postgres ximply_vision > backup_$(date +%Y%m%d).sql

# Restore backup
cat backup_20240115.sql | docker-compose exec -T db psql -U postgres ximply_vision
```

### MinIO Backup

```bash
# Install MinIO client
mc alias set minio http://localhost:9000 $MINIO_ACCESS_KEY $MINIO_SECRET_KEY

# Sync to backup location
mc mirror minio/ximply-vision /path/to/backup/
```

## Monitoring

### Health Checks

- Liveness: `GET /api/v1/health/live`
- Readiness: `GET /api/v1/health/ready`
- Full status: `GET /api/v1/health`

### Logs

```bash
# All logs
docker-compose logs

# Specific service
docker-compose logs backend

# Follow logs
docker-compose logs -f --tail=100 backend

# With timestamps
docker-compose logs -t backend
```

## Troubleshooting

### Service Not Starting

1. Check logs: `docker-compose logs <service>`
2. Verify environment variables
3. Check port conflicts
4. Verify volume permissions

### Database Connection Issues

1. Verify PostgreSQL is healthy
2. Check connection string
3. Verify credentials
4. Test connection: `docker-compose exec db psql -U postgres`

### MinIO Issues

1. Check MinIO logs
2. Verify credentials
3. Check bucket exists
4. Test with MinIO client

### Frontend Not Loading

1. Check nginx logs
2. Verify build completed
3. Check network configuration
4. Verify API URL in environment

## Maintenance

### Update Application

```bash
# Pull latest changes
git pull origin main

# Rebuild and restart
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Run migrations
docker-compose exec backend alembic upgrade head
```

### Clear Caches

```bash
# Clear Docker build cache
docker builder prune

# Remove unused images
docker image prune -a
```

### Rotate Secrets

1. Generate new secrets
2. Update .env file
3. Restart services
4. Verify functionality

## Elsewhere

- [Readme](../../README.md)
- [Features](../features/README.md)
- [Architecture decisions](../adr/README.md)
- [Security decisions](../sec/README.md)
- [API reference](../infrastructure/api.md)
