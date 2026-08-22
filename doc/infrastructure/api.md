# XIMPLY Vision - API Reference

## Overview

A REST API built with FastAPI. Every endpoint is versioned and requires a bearer
token unless stated otherwise.

- **Base URL**: `/api/v1`
- **Authentication**: bearer token, see [Authentication](#authentication)
- **Interactive documentation**: `/api/v1/docs`, and `/api/v1/redoc`
- **Serialisation**: request and response bodies use camelCase

Related reading:

- [Accounts and access control](../features/FEAT-0010-accounts-and-access.md)
- [Authentication and authorization](../sec/SEC-0002-authentication-and-authorization.md)
- [System architecture](architecture.md)

## Authentication

Tokens are JSON Web Tokens. The access token carries the subject, the roles and
the resolved permission list, so authorization needs no database round trip.
Its limits, including the absence of revocation, are recorded in
[SEC-0002](../sec/SEC-0002-authentication-and-authorization.md#known-gaps).

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/login` | No | Exchange credentials for tokens |
| POST | `/auth/register` | No | Create an account |
| POST | `/auth/refresh` | No | Exchange a refresh token for a new access token |
| GET | `/auth/me` | Yes | The authenticated user |
| POST | `/auth/logout` | Yes | End the session on the client |

### Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "email": "admin@ximply.com", "password": "Admin1234" }
```

```json
{
  "accessToken": "eyJhbGciOiJIUzI1NiIs...",
  "refreshToken": "eyJhbGciOiJIUzI1NiIs...",
  "tokenType": "bearer",
  "expiresIn": 1800,
  "user": { "id": "...", "email": "...", "fullName": "...", "roles": ["admin"] }
}
```

The default administrator credentials are documented, shared by every
unconfigured deployment, and reset on each start. See
[SEC-0006](../sec/SEC-0006-default-credentials-and-secrets.md).

## Detection

The endpoints behind the live view. See
[FEAT-0001](../features/FEAT-0001-live-detection.md).

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/detection/detect` | Detect in one frame |
| POST | `/detection/capture` | Save a detection into the catalog |
| POST | `/detection/describe` | Describe the scene in a frame |
| GET | `/detection/describe/status` | Whether the description model is usable |
| GET | `/detection/status` | Detection service status |
| GET | `/detection/config` | Read the detection configuration |
| PUT | `/detection/config` | Update the detection configuration |
| POST | `/detection/catalog/load` | Load every catalog entry into the matcher |
| POST | `/detection/catalog/refresh/{objectId}` | Reload one entry |
| GET | `/detection/stream` | Server sent event stream |
| POST | `/detection/start` | Start a detection session |
| POST | `/detection/stop` | Stop a detection session |

### Detect

```http
POST /api/v1/detection/detect
Authorization: Bearer <token>
Content-Type: application/json

{
  "image": "data:image/jpeg;base64,...",
  "confidenceThreshold": 0.6,
  "hidePersonDetections": false,
  "showOnlyCustomObjects": false,
  "includeSkeletons": true,
  "includeFaceMesh": true,
  "detectionModel": "sam",
  "segmentationTightness": 0.6,
  "segmentationExcludeSiblings": true
}
```

The view toggles travel with the request rather than filtering the response.
Filtering afterwards is not equivalent, and an overlay that is switched off is
not computed at all; see
[ADR-0007](../adr/ADR-0007-view-filters-applied-server-side.md).

```json
{
  "detections": [
    {
      "label": "person",
      "confidence": 0.94,
      "bbox": { "x": 338, "y": 29, "width": 415, "height": 631 },
      "classId": 0,
      "objectId": "0699...",
      "objectName": "Jorge",
      "matchConfidence": 0.98,
      "polygon": [[344, 31], [352, 44]]
    }
  ],
  "barcodes": [],
  "skeletons": [],
  "frameWidth": 1000,
  "frameHeight": 667,
  "processingTimeMs": 48.2,
  "timestamp": "2026-08-22T18:04:11Z"
}
```

Two confidences are reported because two models answer two questions.
`confidence` is how sure the detector is that something is there;
`matchConfidence` is how sure the matcher is that it is this particular entry.
See [ADR-0005](../adr/ADR-0005-two-confidences.md).

`polygon` is present only when `detectionModel` is `sam` and the outline could
be traced. Its absence means the bounding box is what should be drawn. See
[FEAT-0004](../features/FEAT-0004-silhouettes.md).

`skeletons` carries body, hand and face landmarks with the edges connecting
them. Edges are sent on the first skeleton of each kind per frame and reused for
the rest; see [ADR-0008](../adr/ADR-0008-published-landmark-layouts.md).

### Capture

Saves a detected region into the catalog. A name that already exists adds an
image to that entry rather than creating a duplicate, and the entry's
descriptors are reloaded immediately so it is recognisable on the next frame.
See [FEAT-0008](../features/FEAT-0008-teaching-the-catalog.md).

### Describe

```http
POST /api/v1/detection/describe
Authorization: Bearer <token>
Content-Type: application/json

{ "image": "data:image/jpeg;base64,...", "detections": [] }
```

The detections already on screen are passed as context so the description uses
the names in the catalog. A model that cannot be loaded answers with
`available: false` and the reason, rather than an error. See
[FEAT-0007](../features/FEAT-0007-scene-description.md).

## Objects

Catalog entries. People are entries too, in a system category; see
[ADR-0002](../adr/ADR-0002-people-as-catalog-entries.md).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/objects` | `objects:read` | List, paginated and filterable |
| POST | `/objects` | `objects:write` | Create |
| GET | `/objects/{id}` | `objects:read` | Read one |
| PATCH | `/objects/{id}/name` | `objects:write` | Rename |
| PUT | `/objects/{id}` | `objects:write` | Update |
| DELETE | `/objects/{id}` | `objects:delete` | Delete one |
| DELETE | `/objects/all` | `objects:delete` | Delete every entry |
| POST | `/objects/merge` | `objects:write` | Merge several into one |
| POST | `/objects/{id}/images` | `objects:write` | Upload a training image |
| GET | `/objects/{id}/images` | `objects:read` | List images |
| DELETE | `/objects/{id}/images/{imageId}` | `objects:delete` | Delete an image |
| GET | `/objects/files/{path}` | **None** | Serve a stored image |

### Rename

```http
PATCH /api/v1/objects/{id}/name
Content-Type: application/json

{ "name": "Jorge" }
```

- `422` when the name is empty.
- `409` when another entry of the same owner already uses it. Comparison ignores
  case and surrounding spaces, because two entries differing only in those are
  indistinguishable in a list.

Both caches are updated on success, since a cache keyed by name that is not
updated keeps announcing the old one. See
[FEAT-0009](../features/FEAT-0009-catalog-management.md#renaming).

### List

`GET /objects` returns `categoryName` alongside `categoryId`, so a client can
tell a person from an object without a request per row.

### Serving stored images

`GET /objects/files/{path}` requires no authentication. This is a deliberate
decision with a real cost, recorded in
[SEC-0003](../sec/SEC-0003-object-storage-exposure.md), and it must be changed
before exposing the stack beyond localhost.

## Users

Administration. See
[FEAT-0010](../features/FEAT-0010-accounts-and-access.md).

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/users` | `users:read` |
| POST | `/users` | `users:write` |
| GET | `/users/{id}` | `users:read` |
| PUT | `/users/{id}` | `users:write` |
| DELETE | `/users/{id}` | `users:delete` |

## Health

Unauthenticated, because they describe the server rather than any user data.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Service and dependency status |
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe, checks the database |
| GET | `/health/acceleration` | Which backends run on dedicated hardware |

### Acceleration

```json
{
  "available": true,
  "active": true,
  "deviceName": "NVIDIA GeForce RTX 5090",
  "deviceMemoryMb": 32606,
  "driver": "13.0",
  "computeCapability": "12.0",
  "backends": [
    { "name": "Object detection", "accelerated": true, "device": "cuda" },
    { "name": "Face recognition", "accelerated": true, "device": "cuda" },
    { "name": "Skeleton and mesh", "accelerated": false, "device": "cpu" }
  ]
}
```

Each backend is reported separately because they fail independently. See
[ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md) and
[FEAT-0011](../features/FEAT-0011-hardware-acceleration.md).

## Error responses

```json
{ "detail": "Object not found" }
```

| Status | Meaning |
| --- | --- |
| 400 | The request could not be parsed, or an image could not be decoded |
| 401 | Missing, malformed or expired token |
| 403 | Authenticated, but the role lacks the required permission |
| 404 | No such resource, or it belongs to another owner |
| 409 | Conflict, such as a duplicate name |
| 422 | The body failed validation |
| 500 | Unhandled error, logged with a stack trace |
| 503 | A model or dependency is unavailable |

Ownership is enforced by filtering on the owner rather than by a separate check,
so a request for another user's entry is a `404` rather than a `403`. This is
deliberate: a `403` would confirm the entry exists.

## Elsewhere

- [Features](../features/README.md)
- [Architecture decisions](../adr/README.md)
- [Security decisions](../sec/README.md)
- [Deployment guide](../operations/deployment.md)
