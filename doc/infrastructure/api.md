# XIMPLY Vision - API Reference

## Overview

A REST API built with FastAPI. Every endpoint is versioned and requires a bearer
token unless stated otherwise.

- **Base URL**: `/api/v1`
- **Authentication**: bearer token, see [Authentication](#authentication)
- **Interactive documentation**: `/api/v1/docs`, and `/api/v1/redoc`
- **Serialisation**: responses are camelCase. Most request bodies are too, but
  the webhook and integration token bodies take their fields in snake_case,
  because those models are declared without the camelCase alias the rest use.
  Query parameters are snake_case everywhere, `page_size` rather than
  `pageSize`, with `type` on the event list the one aliased exception.

Related reading:

- [Accounts and access control](../features/FEAT-0010-accounts-and-access.md)
- [Authentication and authorization](../sec/SEC-0002-authentication-and-authorization.md)
- [System architecture](architecture.md)

## Authentication

Tokens are JSON Web Tokens. The access token carries the subject, the roles and
the resolved permission list, so authorization needs no database round trip.
Its limits, including the absence of revocation, are recorded in
[SEC-0002](../sec/SEC-0002-authentication-and-authorization.md#known-gaps).

Permissions follow a `resource:action` pattern and are named per route below.
The event layer adds two of them: `events:read`, which reads events and their
captures, and `events:manage`, which prunes events, manages webhook
subscriptions and issues integration tokens. Both are seeded like every other
permission and granted to the administrator role.

A machine client does not use a JWT. The protocol mounts described under
[Model Context Protocol](#model-context-protocol) are authenticated with an
integration token instead, a long lived credential bound to one client and one
set of scopes. Why the two are different, and how a token is handled, is in
[ADR-0017](../adr/ADR-0017-scoped-tokens-for-machine-clients.md) and
[SEC-0009](../sec/SEC-0009-integration-tokens.md).

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
| GET | `/detection/camera` | Read the state a camera is wanted in |
| PUT | `/detection/camera` | Ask a camera to start or stop |
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

### Camera control

The camera runs in the browser, so nothing here opens a device. These routes
hold the state a camera is wanted in; the live view polls the first every two
seconds and honours it, and calls the second when somebody uses the button so
that a state chosen at the screen and one asked for elsewhere never disagree.
See [ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)
and [SEC-0010](../sec/SEC-0010-remote-camera-activation.md).

```http
GET /api/v1/detection/camera?camera_id=default
Authorization: Bearer <token>
```

```json
{
  "cameraId": "default",
  "desiredOn": true,
  "running": true,
  "pending": false,
  "viewers": 0,
  "requestedBy": "token:night watch",
  "requestedAt": "2026-08-23T00:31:33.604528Z",
  "lastFrameAt": "2026-08-23T00:34:07.513067Z"
}
```

`desiredOn` is what was asked for. `running` is what is happening, decided by
frames arriving for detection within `CAMERA_LIVE_GRACE_SECONDS`, never by
anything asserting it. `pending` is the pair that matters: asked for and not
running, which means no interface is open to honour it. `viewers` is how many
subscribers are reading this camera's live frames over HTTP
([Streaming](#streaming)), counted when the state is read rather than stored.

Reading needs `detection:view`. Writing needs `camera:control`:

```http
PUT /api/v1/detection/camera
Authorization: Bearer <token>
Content-Type: application/json

{ "on": true, "cameraId": "default" }
```

The reply is the state after the request, in the shape above.

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

## Events

What the camera observed, recorded on a transition rather than per frame. See
[FEAT-0013](../features/FEAT-0013-events-and-webhooks.md),
[ADR-0013](../adr/ADR-0013-events-as-opentelemetry-records.md) and
[ADR-0014](../adr/ADR-0014-events-on-transition-not-per-frame.md).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/events` | `events:read` | List, newest first, paginated |
| GET | `/events/otlp` | `events:read` | Export in the OTLP logs envelope |
| GET | `/events/types` | `events:read` | The types this instance can raise |
| GET | `/events/{id}` | `events:read` | Read one |
| GET | `/events/{id}/capture` | `events:read` | The frame that produced it |
| DELETE | `/events/prune` | `events:manage` | Delete events older than a cutoff |

Every route is scoped to the authenticated owner, so another user's event is a
`404` rather than a `403`.

### List

```http
GET /api/v1/events?type=person&since=2026-08-22T18:00:00Z&page=1&page_size=50
Authorization: Bearer <token>
```

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | `1` | |
| `page_size` | `50` | Maximum 200 |
| `type` | none | A whole type, `person.departed`, or a family, `person` |
| `since` | none | Events with `occurredAt` after this instant |
| `subject_id` | none | Events about one catalog entry |

`since` is the usual way to poll: ask for everything after the last event
already seen.

The response is the paginated envelope, `items`, `total`, `page`, `pageSize` and
`totalPages`. One item is an OpenTelemetry log record, so the field names are the
ones the specification uses:

```json
{
  "id": "0699...",
  "eventName": "person.recognised",
  "timestampNanos": 1755885851123456789,
  "observedTimestampNanos": 1755885851123456789,
  "traceId": null,
  "spanId": null,
  "severityNumber": 9,
  "severityText": "INFO",
  "body": {
    "type": "person.recognised",
    "subject": {
      "id": "0699...",
      "name": "Jorge",
      "class": "person",
      "confidence": 0.9812
    },
    "camera": "front-door",
    "occurredAt": "2026-08-22T18:04:11+00:00"
  },
  "attributes": {
    "event.name": "person.recognised",
    "ximply.owner.id": "0699...",
    "ximply.subject.id": "0699...",
    "ximply.subject.name": "Jorge",
    "ximply.subject.confidence": 0.9812,
    "ximply.camera.id": "front-door"
  },
  "resource": {
    "service.name": "XIMPLY Vision",
    "service.version": "1.0.0",
    "service.namespace": "ximply"
  },
  "scopeName": "app.services.event_service",
  "scopeVersion": "1.0.0",
  "subjectId": "0699...",
  "subjectName": "Jorge",
  "confidence": 0.9812,
  "cameraId": "front-door",
  "capturePath": "events/0699.../0699....jpg",
  "captureUrl": "/api/v1/events/0699.../capture",
  "occurredAt": "2026-08-22T18:04:11Z"
}
```

`attributes` is the source of truth. The flat fields after `scopeVersion` are
projections of it, offered because reading a dotted key out of a map is tedious
for a client that only wants the subject. `traceId` and `spanId` are part of the
record shape and are currently never populated; see
[ADR-0013](../adr/ADR-0013-events-as-opentelemetry-records.md).

### Types

```json
{
  "types": [
    "person.enrolled",
    "person.recognised",
    "person.departed",
    "object.recognised",
    "scene.changed"
  ],
  "families": ["object", "person", "scene"]
}
```

### OTLP export

`GET /events/otlp` takes an optional `since` and a `limit`, 500 by default and
5000 at most. It returns `resourceLogs`, grouped by resource and by
instrumentation scope, with values wrapped in the OTLP `AnyValue` shape, so the
result can be posted to a collector without a translation step.

### Capture

`GET /events/{id}/capture` streams the JPEG frame that produced the event, and
requires `events:read`. This is deliberately unlike the catalog image proxy at
`/objects/files/{path}`, which requires no authentication
([SEC-0003](../sec/SEC-0003-object-storage-exposure.md)): an event capture is a
photograph of whoever was in front of the camera. `404` when the event has no
capture, when the stored object is missing, or when it belongs to another owner.

### Prune

`DELETE /events/prune?older_than_days=7` deletes events older than the cutoff and
answers with how many went. Omitting the parameter uses
`EVENTS_RETENTION_DAYS`. Nothing prunes on a schedule, so a deployment with a
retention obligation calls this itself.

## Webhooks

Subscriptions that receive events as they are raised. Every route requires
`events:manage`. See
[ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md) and
[SEC-0008](../sec/SEC-0008-webhook-signing.md).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/webhooks` | `events:manage` | List subscriptions |
| POST | `/webhooks` | `events:manage` | Create one and generate its secret |
| PUT | `/webhooks/{id}` | `events:manage` | Update, including enable and disable |
| POST | `/webhooks/{id}/rotate` | `events:manage` | Replace the secret |
| POST | `/webhooks/{id}/test` | `events:manage` | Send a signed test delivery |
| DELETE | `/webhooks/{id}` | `events:manage` | Remove one |
| GET | `/webhooks/headers` | `events:manage` | The headers a delivery carries |

### Create

```http
POST /api/v1/webhooks
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Door controller",
  "url": "https://example.internal/hooks/ximply",
  "event_types": ["person"]
}
```

The request takes `event_types` in snake_case and the response returns
`eventTypes`, because the request model is declared without the alias the
response model uses. `PUT /webhooks/{id}` takes the same fields, all optional,
plus `is_active`.

```json
{
  "id": "0699...",
  "name": "Door controller",
  "url": "https://example.internal/hooks/ximply",
  "eventTypes": ["person"],
  "isActive": true,
  "lastDeliveryAt": null,
  "lastStatus": null,
  "lastError": null,
  "failureCount": 0,
  "createdAt": "2026-08-22T18:00:00Z",
  "secret": "9f2c..."
}
```

An empty `eventTypes` means every type. An entry may be a whole type or a
family, so `person` delivers every person event including ones added in a later
version. An unknown entry is a `422`.

`secret` appears only here and in the rotate response. It is never returned
again, so it has to be copied now or rotated later.

### Delivery

A delivery is a `POST` of the whole log record, with these headers:

| Header | Value |
| --- | --- |
| `X-Ximply-Signature` | `sha256=` followed by the hex HMAC |
| `X-Ximply-Timestamp` | Unix seconds at which it was signed |
| `X-Ximply-Event` | The event type |
| `X-Ximply-Delivery` | The delivery id, which is the event id, for deduplication |

The signature is HMAC-SHA256 over the timestamp, a full stop, and the exact
bytes of the body, keyed with the subscription secret. How to verify it, and why
it is built that way, is in
[SEC-0008](../sec/SEC-0008-webhook-signing.md#verifying-a-delivery).

Non 2xx responses and transport errors are retried up to
`WEBHOOK_MAX_ATTEMPTS` times with a backoff between attempts. The outcome is
recorded on the subscription as `lastStatus`, `lastError` and `failureCount`,
and a subscription reaching `WEBHOOK_DISABLE_AFTER_FAILURES` consecutive
failures is switched off. Re-enabling it through `PUT` clears the count.

### Test

`POST /webhooks/{id}/test` sends a signed delivery with a small test body rather
than a real event, updates the subscription's delivery health, and answers with
a message saying whether it was accepted. It answers `200` either way: a failed
test is a result, not an error.

### Headers

`GET /webhooks/headers` names the headers a delivery carries and the algorithm
that signs it, so a receiver can be written without reading the source:

```json
{
  "signature": "X-Ximply-Signature",
  "timestamp": "X-Ximply-Timestamp",
  "event": "X-Ximply-Event",
  "delivery": "X-Ximply-Delivery",
  "algorithm": "HMAC-SHA256 over the timestamp, a full stop, and the raw body"
}
```

## Integration tokens

Credentials issued to machine clients, one per client. Every route requires
`events:manage`. See
[ADR-0017](../adr/ADR-0017-scoped-tokens-for-machine-clients.md) and
[SEC-0009](../sec/SEC-0009-integration-tokens.md).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/integration-tokens` | `events:manage` | List tokens, without their values |
| POST | `/integration-tokens` | `events:manage` | Issue one and return its value |
| PUT | `/integration-tokens/{id}` | `events:manage` | Switch one on or off |
| DELETE | `/integration-tokens/{id}` | `events:manage` | Revoke one permanently |

### Issue

```http
POST /api/v1/integration-tokens
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Home assistant",
  "scopes": ["events:read"],
  "expires_in_days": 365
}
```

```json
{
  "id": "0699...",
  "name": "Home assistant",
  "prefix": "xvt_8Kd2Qa",
  "scopes": ["events:read"],
  "isActive": true,
  "lastUsedAt": null,
  "expiresAt": "2027-08-22T18:00:00Z",
  "createdAt": "2026-08-22T18:00:00Z",
  "token": "xvt_8Kd2Qa..."
}
```

As with a webhook secret, the request body is snake_case and the response is
camelCase. `expires_in_days` is optional, between 1 and 3650; omitting it
issues a token that lasts until it is revoked.

`token` appears only in this response and is never returned again. What is
stored is a SHA-256 digest and the ten character `prefix`, which is all the
list endpoint returns.

`scopes` may name `events:read`, `objects:read` and `events:manage`, and is
rejected with `403` when it asks for a permission the issuing user does not
hold. An empty list is not a narrow token but a wide one: every permission
check then passes.

### Switch off, and revoke

```http
PUT /api/v1/integration-tokens/{id}?is_active=false
Authorization: Bearer <token>
```

`is_active` is a query parameter rather than a body field, and it is the only
thing this route changes: a token's scopes are fixed when it is issued.

`DELETE /integration-tokens/{id}` removes the record, so the value can never
resolve again. Both take effect on the next call the client makes, because a
token is looked up in the database every time it is presented.

## Streaming

A subscriber connects to this instance instead of running a server for it to
call. The records are the ones a webhook delivers, on two transports the
subscriber chooses between: a broker, or a connection held open over HTTP. See
[FEAT-0015](../features/FEAT-0015-streaming.md),
[ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md),
[ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)
and [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/stream/info` | `events:read` | What is available: broker state, endpoints, topics and scopes |
| GET | `/stream/events` | `events:read` | Every event as it is raised, as server sent events |
| GET | `/stream/camera/{cameraId}` | `camera:view`, by name | The live frames of one camera, as multipart JPEG |

`STREAM_ENABLED` decides whether these routes serve at all and is read at
startup. Frames need `CAMERA_VIEW_ENABLED` as well, and the broker needs
`MQTT_ENABLED`. The three are separate settings because a deployment that wants
event records carried live usually does not want the room carried with them.

### The credential

A user session and an integration token both authenticate these routes, which is
the first time a token reaches a route outside the protocol mounts. The scope
rules are the ones the protocol applies: `events:read` is carried by an empty
scope list, and `camera:view` has to be written on the token by name
([ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)).

The credential travels in `Authorization` and is not accepted anywhere else. A
token in the query string would make an `img` tag work, at the cost of putting a
live credential into browser history, proxy logs and referrer headers
([SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md)). That also rules
out `EventSource`, which cannot send a header, so a browser client reads the
event stream with `fetch` and a `ReadableStream`.

### What is available

```http
GET /api/v1/stream/info
Authorization: Bearer xvt_8Kd2Qa...
```

```json
{
  "enabled": true,
  "owner": "06946e01-4492-7889-8000-aeaa0655f533",
  "broker": {
    "enabled": true,
    "connected": true,
    "host": "mosquitto",
    "port": 1883,
    "instance": "default",
    "publishesCaptures": true,
    "publishesFrames": false,
    "published": 412,
    "dropped": 0,
    "topics": {
      "events": "ximply/default/events/{owner}/{type}",
      "captures": "ximply/default/captures/{owner}/{event}",
      "camera": "ximply/default/camera/{owner}/{camera}/frame",
      "status": "ximply/default/status"
    }
  },
  "endpoints": {
    "events": {
      "path": "/api/v1/stream/events",
      "mediaType": "text/event-stream",
      "scope": "events:read"
    },
    "camera": {
      "path": "/api/v1/stream/camera/{cameraId}",
      "mediaType": "multipart/x-mixed-replace; boundary=ximplyframe",
      "scope": "camera:view",
      "enabled": false,
      "maxFps": 4.0,
      "maxSide": 640
    }
  },
  "keepaliveSeconds": 15.0,
  "subscribers": 0,
  "dropped": 0
}
```

The topic templates come back with the instance already substituted, so what is
shown is what will run. The streaming tab of the integrations page renders its
table and its examples from this response rather than hard coding them, which is
why a topic added to the backend appears there with no frontend change.

`dropped` counts what a full queue discarded since the process started, once at
the top level for the HTTP fan-out and once under `broker` for the outbound
queue. It is the one number that says a subscriber is losing data. `subscribers`
is how many connections are reading this account's events on this worker.

`enabled` under `endpoints.camera` is `CAMERA_VIEW_ENABLED`, so a client can
tell a deployment that will refuse frames from one that will serve them before
it opens a connection.

### The event stream

`GET /stream/events` holds the connection open and writes one message per event.
The SSE `event` field carries the event type, so a browser can use
`addEventListener` per type, and `data` is the same full OpenTelemetry log
record a webhook delivery carries, built by the same function:

```
event: person.recognised
data: {"id": "0699...", "eventName": "person.recognised", "attributes": { ... }}

: keepalive
```

A comment line is written every `STREAM_KEEPALIVE_SECONDS` so an idle connection
survives a proxy. The generator checks whether the client is still connected on
every iteration and ends when it is not, because an endless generator and a
shutdown that waits for open connections leave the port bound.

```bash
curl -N -H "Authorization: Bearer xvt_8Kd2Qa..." \
  http://localhost:8000/api/v1/stream/events
```

Nothing is replayed. A subscriber that connects late receives what happens next;
what happened before is in `GET /events` and is still delivered by webhook.

### Watching a camera

`GET /stream/camera/{cameraId}` answers `multipart/x-mixed-replace` with one
JPEG per part, the format every player already reads. Frames
are downscaled to `STREAM_CAMERA_MAX_SIDE`, encoded at `STREAM_CAMERA_QUALITY`
and rate limited to `STREAM_CAMERA_MAX_FPS`, independently of what detection
runs at: a viewer cannot make the camera capture faster and cannot pull a larger
image than the browser is already sending.

```bash
ffplay -headers "Authorization: Bearer xvt_8Kd2Qa..." \
  http://localhost:8000/api/v1/stream/camera/default
```

- `403` when the token does not list `camera:view`. The empty scope list that
  means "whatever the owner holds" does not carry it, so a token issued before
  this existed cannot watch.
- `404` when `CAMERA_VIEW_ENABLED` is false, because the capability is absent
  from the deployment rather than refused to this caller.

No frame is stored, and none is encoded at all while nobody is subscribed. The
camera state reports how many subscribers are watching, so being watched shows
on the screen in the room; see [Camera control](#camera-control).

### The broker

With `MQTT_ENABLED` on, the same records are published to MQTT. The topic tree
is fixed, and the owner id is in the path so a broker ACL can be written per
account:

| Topic | Payload | QoS | Retained |
| --- | --- | --- | --- |
| `ximply/<instance>/events/<owner>/<type>` | The log record, as JSON | 1 | No |
| `ximply/<instance>/captures/<owner>/<event>` | The capture, as JPEG | 0 | No |
| `ximply/<instance>/camera/<owner>/<camera>/frame` | The live frame, as JPEG | 0 | No |
| `ximply/<instance>/status` | `online` or `offline` | 1 | Yes |

`<instance>` is `MQTT_INSTANCE`, so several deployments share one broker without
colliding, and the first segment is `MQTT_TOPIC_PREFIX`. Events are QoS 1
because a subscriber that misses an arrival has missed what it subscribed for;
images are QoS 0 because a frame that arrives late is worth nothing. Nothing
carrying an observation is retained. The status topic is the exception and is
registered as a last will, so a subscriber can tell "nothing is happening" from
"nothing is running" without asking.

```bash
mosquitto_sub -h localhost -p 1883 -v -t 'ximply/default/events/#'
```

Add `-u` and `-P` when the broker requires an account.

Publishing never delays a frame. Records are handed to a bounded queue of
`MQTT_QUEUE_SIZE` and written by one background task, which drops the oldest
entry and counts it when the broker is unreachable; detection does not wait and
does not fail. Captures are published only when `MQTT_PUBLISH_CAPTURES` is on,
and live frames only when `MQTT_PUBLISH_FRAMES` is on as well as
`CAMERA_VIEW_ENABLED`. Frames on the broker are opt in on their own because a
broker does not tell a publisher who is subscribed, so once they are on they
flow whether or not anybody is listening; that is the one path here that
publishes without knowing
([SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md)).
`MQTT_ENABLED` is read at startup, so there is no runtime switch for the broker
the way there is for the protocol.

The broker is a second process with its own accounts and its own log, and the
shipped configuration writes no per-owner ACL. What that costs, and what has to
be done before the port leaves the machine, is
[SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

## Model Context Protocol

An agent can read what the camera observed instead of waiting to be told, and
can ask the camera to start or stop. The server is mounted outside the versioned
API, because it brings its own application rather than a set of routes. See
[ADR-0016](../adr/ADR-0016-read-only-protocol-server.md),
[ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)
and [FEAT-0014](../features/FEAT-0014-integrations.md).

| Mount | Transport | Auth |
| --- | --- | --- |
| `/mcp` | Streamable HTTP | Bearer integration token |
| `/mcp/sse` | Server sent events, with messages at `/mcp/sse/messages/` | Bearer integration token |

Both are switched off together by `MCP_ENABLED`, and their paths are set by
`MCP_PATH` and `MCP_SSE_PATH`. Server sent events is offered for clients
written before streamable HTTP; the tool set behind the two is the same.

Authentication is a header, checked by a middleware in front of both mounts, so
a request without a usable token reaches no tool:

```http
POST /mcp/
Authorization: Bearer xvt_8Kd2Qa...
Content-Type: application/json
Accept: application/json, text/event-stream
```

A missing, unknown, inactive or expired token is a `401` with a `detail`
message. The response to a successful `initialize` carries an `mcp-session-id`
header, which subsequent calls send back.

### Tools

| Tool | Returns | Scope |
| --- | --- | --- |
| `list_events` | Events newest first. Optional `event_type`, whole type or family; `since_minutes`; `limit`, at most 200 | `events:read` |
| `get_current_scene` | The last scene change with its age in seconds, who is present, and the description when one was written | `events:read` |
| `list_known_subjects` | Catalog entries, people separated from objects. Optional `include_people` | `objects:read` |
| `export_events_otlp` | The OTLP logs envelope. Optional `since_minutes`, 60 by default, and `limit`, at most 1000 | `events:read` |
| `get_status` | Acceleration, description model and segmentation status | `events:read` |
| `get_camera` | Whether a camera is wanted on and whether it is running | `events:read` |
| `start_camera` | Asks for a camera to run. Optional `camera_id` | `camera:control`, by name |
| `stop_camera` | Asks for a camera to stop. Optional `camera_id` | `camera:control`, by name |
| `get_camera_frame` | The most recent frame of a camera, as base64 JPEG. Optional `camera_id` | `camera:view`, by name |
| `get_stream_info` | Where to subscribe: the broker address and topics, and the streaming endpoints | `events:read` |

`list_events` returns records in the same shape a webhook delivery carries, and
`export_events_otlp` produces exactly what `GET /events/otlp` produces, from
the same function. Every tool is filtered by the owner of the token that called
it, and a tool whose scope the token does not carry is refused rather than
answered.

No reading tool writes anything. The catalog cannot be edited through any tool,
a person cannot be enrolled or renamed, and nothing can be deleted. A stored
capture stays behind `GET /events/{id}/capture` and a user session: no tool
returns one.

The four camera tools are the exception, and are gated differently from the
rest. Neither `camera:control` nor `camera:view` is ever inherited: a token with
no scopes carries whatever its owner carries for reading, but each of these has
to appear on the token by name, so credentials issued before they existed cannot
use them. `CAMERA_CONTROL_ENABLED` and `CAMERA_VIEW_ENABLED` remove the
corresponding tools from a deployment entirely.

`get_camera_frame` is the one tool that answers with an image, and it is a live
frame rather than a stored one. It shows a room instead of reporting on it,
which is why it is held to the standard in
[ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)
rather than the one the reading tools follow.

They record a request rather than opening a device. An open interface polls the
state and honours it; when none is open the reply comes back with `pending`
true and a note saying nothing was listening, rather than reporting a camera
that never started.

### Switching the protocol off

`MCP_ENABLED` decides whether the mounts exist at all, and is read at startup.
Once running, the protocol is opened and closed from `GET` and
`PUT /health/mcp`, which is what the footer switch in the interface calls. A
closed protocol keeps both transports mounted and answers every call with a
`503` and a `detail` message, so a connected agent gets an answer rather than a
hole. The state is held in the process, so a deployment running several workers
switches it per worker.

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

Reading these needs no authentication, because they describe the server rather
than any user data. Changing something does, and those are the two routes here
that are not public.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | No | Service and dependency status |
| GET | `/health/live` | No | Liveness probe |
| GET | `/health/ready` | No | Readiness probe, checks the database |
| GET | `/health/acceleration` | No | What each backend can use and is using |
| PUT | `/health/acceleration` | `detection:configure` | Move one backend between the processor and the accelerator |
| GET | `/health/mcp` | No | Whether the protocol is built in and currently open |
| PUT | `/health/mcp` | `events:manage` | Open or close the protocol |

### Protocol switch

```json
{
  "available": true,
  "enabled": true,
  "path": "/mcp",
  "ssePath": "/mcp/sse"
}
```

`available` is whether the deployment was started with `MCP_ENABLED`, which is
read once at startup and cannot be changed from here. `enabled` is the switch on
the wall, thrown while the application runs:

```http
PUT /api/v1/health/mcp
Authorization: Bearer <token>
Content-Type: application/json

{ "enabled": false }
```

The reply is the status above. Closing the protocol cuts off every connected
agent, not just the caller's, which is why it sits behind `events:manage` like
the rest of the integration configuration. A deployment started without the
protocol answers `409`: there is nothing to open, and saying so is better than
reporting a state it cannot reach.

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
    {
      "key": "detection",
      "name": "Object detection",
      "accelerated": true,
      "device": "cuda",
      "detail": "2.6.0+cu124",
      "supported": true,
      "enabled": true
    },
    {
      "key": "face",
      "name": "Face recognition",
      "accelerated": true,
      "device": "cuda",
      "detail": "1.20.1",
      "supported": true,
      "enabled": true
    },
    {
      "key": "landmarks",
      "name": "Skeleton and mesh",
      "accelerated": false,
      "device": "cpu",
      "detail": "GPU delegate available. It needs a real graphics context, which a container usually lacks, and falls back to the processor when it cannot start.",
      "supported": true,
      "enabled": false
    }
  ]
}
```

Each backend is reported separately because they fail independently. Three
fields describe each one rather than a single flag, and they are not the same
question:

| Field | Means |
| --- | --- |
| `supported` | This machine could accelerate this backend |
| `enabled` | It has been asked to |
| `accelerated` | It is actually happening |

The landmark row above is the case that needs all three: supported by the
hardware, deliberately switched off, and therefore on the processor. `key` is
stable and is what the `PUT` sends back. `available` is whether the machine has
an accelerator at all; `active` is whether any backend is using it, so
switching every backend off makes `active` false while `available` stays true.

### Changing where a backend runs

```http
PUT /api/v1/health/acceleration
Authorization: Bearer <token>
Content-Type: application/json

{ "backend": "landmarks", "enabled": true }
```

`backend` is one of `detection`, `face` or `landmarks`; an unknown key is a
`422`. The response is the whole status document above, after the change,
rather than an acknowledgement: the setting is server wide, so it decides what
every viewer's frames run on and not just the caller's, and the client should
draw what the server holds rather than what it hoped for.

The models the backend owns are dropped and rebuilt on the next frame that
needs them, which takes a moment. A rebuild that fails does not fail the
request, because the preference was applied either way; the backend then
reports `enabled` true and `accelerated` false. See
[ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md),
[ADR-0018](../adr/ADR-0018-acceleration-assigned-per-backend.md) and
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

## The Postman collection

`postman/ximply-vision.postman_collection.json` covers every operation here. It
is generated rather than maintained, from the document the server publishes:

```bash
curl -s http://localhost:8000/api/v1/openapi.json -o openapi.json
python postman/generate.py openapi.json
```

Editing the collection by hand is how it drifted before, to describing half the
routes and sending a JSON body to one that reads query parameters. Example
bodies worth keeping go in `EXAMPLES` inside `postman/generate.py`, and
descriptions the summary does not cover go in `NOTES` beside them; anything
written into the collection itself is discarded by the next run.

## Elsewhere

- [Features](../features/README.md)
- [Architecture decisions](../adr/README.md)
- [Security decisions](../sec/README.md)
- [Deployment guide](../operations/deployment.md)
