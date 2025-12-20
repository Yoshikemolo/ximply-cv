# XIMPLY Vision - API Reference

## Overview

The XIMPLY Vision API is a RESTful API built with FastAPI. All endpoints are versioned and require authentication unless otherwise noted.

**Base URL:** `/api/v1`

**Authentication:** Bearer Token (JWT)

## Authentication

### Login
Authenticate user and receive JWT tokens.

**Endpoint:** `POST /auth/login`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123"
}
```

**Response:**
```json
{
  "accessToken": "eyJ...",
  "refreshToken": "eyJ...",
  "tokenType": "bearer",
  "expiresIn": 1800,
  "user": {
    "id": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
    "email": "user@example.com",
    "fullName": "John Doe",
    "status": "active",
    "roles": [{"id": "...", "name": "operator"}]
  }
}
```

### Register
Create a new user account.

**Endpoint:** `POST /auth/register`

**Request:**
```json
{
  "email": "newuser@example.com",
  "password": "SecurePass123",
  "fullName": "Jane Smith"
}
```

### Refresh Token
Get a new access token using refresh token.

**Endpoint:** `POST /auth/refresh`

**Request:**
```json
{
  "refreshToken": "eyJ..."
}
```

### Get Current User
Get authenticated user information.

**Endpoint:** `GET /auth/me`

**Headers:** `Authorization: Bearer <token>`

## Objects

### List Objects
Get paginated list of objects.

**Endpoint:** `GET /objects`

**Query Parameters:**
- `page` (int): Page number (default: 1)
- `pageSize` (int): Items per page (default: 20, max: 100)
- `search` (string): Search by name or reference
- `categoryId` (UUID): Filter by category
- `status` (string): Filter by status

**Response:**
```json
{
  "items": [
    {
      "id": "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
      "name": "Sample Object",
      "reference": "REF001",
      "status": "active",
      "thumbnailPath": "objects/.../thumb.jpg",
      "trainingSamples": 15,
      "modelConfidence": 0.92,
      "createdAt": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 100,
  "page": 1,
  "pageSize": 20,
  "totalPages": 5
}
```

### Create Object
Create a new catalog object.

**Endpoint:** `POST /objects`

**Request:**
```json
{
  "name": "New Product",
  "description": "Product description",
  "reference": "PROD001",
  "categoryId": "0190a1b2-...",
  "weight": 1.5,
  "weightUnit": "kg",
  "dimensions": {
    "width": 10,
    "height": 20,
    "depth": 5,
    "unit": "cm"
  },
  "price": 29.99,
  "currency": "EUR",
  "color": "Blue",
  "materials": ["plastic", "metal"]
}
```

### Get Object
Get single object by ID.

**Endpoint:** `GET /objects/{objectId}`

### Update Object
Update object properties.

**Endpoint:** `PUT /objects/{objectId}`

### Delete Object
Delete object and associated images.

**Endpoint:** `DELETE /objects/{objectId}`

### Upload Object Image
Upload training image for object.

**Endpoint:** `POST /objects/{objectId}/images`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `file`: Image file (JPEG, PNG, WebP)
- `isPrimary`: Set as primary image (boolean)

### List Object Images
Get all images for an object.

**Endpoint:** `GET /objects/{objectId}/images`

### Delete Object Image
Delete specific image.

**Endpoint:** `DELETE /objects/{objectId}/images/{imageId}`

## Categories

### List Categories
Get all categories.

**Endpoint:** `GET /categories`

### Create Category
Create new category.

**Endpoint:** `POST /categories`

**Request:**
```json
{
  "name": "Electronics",
  "description": "Electronic devices",
  "parentId": null
}
```

### Update Category
**Endpoint:** `PUT /categories/{categoryId}`

### Delete Category
**Endpoint:** `DELETE /categories/{categoryId}`

## Detection

### Start Detection
Start detection session.

**Endpoint:** `POST /detection/start`

**Request:**
```json
{
  "cameraId": "default"
}
```

### Stop Detection
Stop detection session.

**Endpoint:** `POST /detection/stop`

### Detection Stream (SSE)
Real-time detection events.

**Endpoint:** `GET /detection/stream`

**Event Format:**
```
event: detection
data: {"detections":[{"label":"object","confidence":0.95,"bbox":{"x":100,"y":100,"width":200,"height":150}}],"timestamp":"2024-01-15T10:30:00Z"}
```

### Get Detection Config
**Endpoint:** `GET /detection/config`

### Update Detection Config
**Endpoint:** `PUT /detection/config`

**Request:**
```json
{
  "confidenceThreshold": 0.5,
  "iouThreshold": 0.45
}
```

## Training

### Start Training
Start model training for object.

**Endpoint:** `POST /training/start`

**Request:**
```json
{
  "objectId": "0190a1b2-...",
  "epochs": 10,
  "batchSize": 16,
  "learningRate": 0.001
}
```

### Get Training Status
**Endpoint:** `GET /training/{jobId}/status`

**Response:**
```json
{
  "jobId": "0190a1b2-...",
  "objectId": "0190a1b2-...",
  "status": "training",
  "progress": 0.45,
  "currentEpoch": 5,
  "totalEpochs": 10,
  "startedAt": "2024-01-15T10:30:00Z"
}
```

### Cancel Training
**Endpoint:** `POST /training/{jobId}/cancel`

## Users (Admin)

### List Users
**Endpoint:** `GET /users`

**Required Permission:** `users:read`

### Create User
**Endpoint:** `POST /users`

**Required Permission:** `users:write`

### Get User
**Endpoint:** `GET /users/{userId}`

### Update User
**Endpoint:** `PUT /users/{userId}`

### Delete User
**Endpoint:** `DELETE /users/{userId}`

**Required Permission:** `users:delete`

## Health

### Health Check
**Endpoint:** `GET /health`

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "healthy",
  "minio": "healthy",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Liveness Probe
**Endpoint:** `GET /health/live`

### Readiness Probe
**Endpoint:** `GET /health/ready`

## Error Responses

All errors follow this format:
```json
{
  "detail": "Error message",
  "code": "ERROR_CODE"
}
```

### HTTP Status Codes
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `409` - Conflict
- `422` - Validation Error
- `500` - Internal Server Error
