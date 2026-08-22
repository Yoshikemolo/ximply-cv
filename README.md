# XIMPLY Vision

Real-time object detection, custom object recognition and catalog management.

XIMPLY Vision streams a camera feed, detects objects with YOLO, matches them against a
catalog of objects you have taught it, and lets you manage that catalog with full
metadata. The backend is FastAPI, the frontend is Angular 19, and the whole stack runs
with a single Docker command.

## Features

- **View**: real-time detection from a camera feed, with bounding boxes, labels and
  confidence percentages. Barcode and QR reading through ZBar.
- **Learn**: teach new objects from uploads or live capture, with annotation tools
  (draw, resize and move bounding boxes) and rich metadata: name, description, weight,
  dimensions, price, reference, color and materials.
- **Catalog**: full CRUD over learned objects, retraining with new images, merging
  duplicates, search and filtering.
- **Admin**: user management with role-based access control.
- **i18n and theming**: English and Spanish, dark and light themes.

## Requirements

- Docker Engine 24 or later with the Compose v2 plugin (`docker compose version`)
- Roughly 6 GB of free disk space for images, model weights and volumes
- A webcam, and a browser that grants camera access to `http://localhost`

Nothing else is needed. Python, Node and the ML dependencies all live inside the images.

## Install with Docker

```bash
git clone https://github.com/Yoshikemolo/ximply-cv.git
cd ximply-cv
docker compose up -d --build
```

That is the whole install. The first build takes several minutes because it compiles the
Python ML stack and builds the Angular bundle. The stack starts without a `.env` file:
every variable falls back to a working local default.

Then open:

| Service       | URL                                | Notes                       |
| ------------- | ---------------------------------- | --------------------------- |
| Application   | http://localhost:4200              | Main entry point            |
| API docs      | http://localhost:8000/api/v1/docs  | Swagger UI                  |
| API redoc     | http://localhost:8000/api/v1/redoc | ReDoc                       |
| MinIO console | http://localhost:9001              | `minioadmin` / `minioadmin` |

Sign in with the seeded administrator:

```
Email:    admin@ximply.com
Password: Admin1234
```

Change that password from the Admin section right after the first login.

### What happens on first start

The backend bootstraps itself: it creates the database schema, seeds permissions, roles
and the administrator user, and creates the MinIO bucket. YOLO weights are downloaded on
first detection into a named volume, so later restarts are fast.

### Customising the install

Copy the template and edit what you need:

```bash
cp .env.example .env
docker compose up -d --build
```

`.env.example` documents every variable: host ports, database and MinIO credentials, the
JWT secret, and which YOLO model to load (`yolo11n` through `yolo11x`).

### Everyday commands

```bash
docker compose logs -f backend     # follow backend logs
docker compose ps                  # service status
docker compose restart backend     # restart one service
docker compose down                # stop the stack, keep the data
docker compose down -v             # stop and delete all data volumes
```

### Development mode

Hot reload for the backend, development build for the frontend:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

### Production mode

Resource limits, log rotation and no debug. This override has no fallback defaults, so a
`.env` file with real credentials is required:

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Set a real `JWT_SECRET_KEY` and real database and MinIO credentials before exposing the
stack. Camera access also requires a secure context: on anything other than `localhost`,
serve the frontend over HTTPS or the browser will refuse to open the camera.

## Running without Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[ml,dev]"
uvicorn app.main:app --reload
```

On Windows, activate with `.venv\Scripts\activate` instead. A reachable PostgreSQL and
MinIO are required; point `DATABASE_URL` and `MINIO_ENDPOINT` at them through
`backend/.env`.

### Frontend

```bash
cd frontend
npm install
npm start
```

## Technology stack

| Layer           | Technology                                               |
| --------------- | -------------------------------------------------------- |
| Backend         | Python 3.11, FastAPI, SQLAlchemy async, Pydantic v2       |
| Computer vision | Ultralytics YOLO11, OpenCV, ORB feature matching, pyzbar  |
| Database        | PostgreSQL 16                                             |
| Object storage  | MinIO                                                     |
| Frontend        | Angular 19 standalone components, Signals, SCSS           |
| Auth            | JWT with refresh rotation and RBAC                        |
| Infrastructure  | Docker Compose, Nginx                                     |

## Project structure

```
ximply-cv/
├── backend/          FastAPI application
├── frontend/         Angular 19 application
├── docker/           Dockerfiles and nginx configuration
├── doc/              Architecture, API and feature documentation
├── planning/         Milestones
├── postman/          API collection
└── models/           ML model weights
```

## Documentation

- [Architecture](doc/infrastructure/architecture.md)
- [API reference](doc/infrastructure/api.md)
- [Deployment](doc/operations/deployment.md)
- [View feature](doc/features/view.md)
- [Learn feature](doc/features/learn.md)

All API endpoints are versioned under `/api/v1/`.

## Troubleshooting

**The camera does not open.** Grant camera permission in the browser and use
`http://localhost:4200`. Any other host needs HTTPS.

**Port already in use.** Copy `.env.example` to `.env` and change `FRONTEND_PORT`,
`BACKEND_PORT`, `DB_PORT` or `MINIO_PORT`.

**The backend restarts on startup.** Check `docker compose logs backend`. It usually
means PostgreSQL or MinIO is not healthy yet; the backend waits for both health checks.

**Detection is slow.** Switch to a lighter model with `DETECTION_MODEL=yolo11n` in
`.env`, then rebuild.

**Starting from scratch.** `docker compose down -v` removes the database, the stored
images and the downloaded weights.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

1. Branch off `main`.
2. Follow the conventions in [CONTRIBUTING.md](CONTRIBUTING.md): Conventional Commits,
   written in English.
3. Run the tests: `pytest` in `backend/`, `npm test` in `frontend/`.
4. Open a pull request.

## License

Released under the [MIT License](LICENSE).

## Author

Jorge Rodríguez - Yoshikemolo
