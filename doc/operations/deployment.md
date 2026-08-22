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
the processor only build. The application header shows the same state.

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
