# FEAT-0013: Events and webhooks

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [FEAT-0003](FEAT-0003-person-recognition.md),
  [FEAT-0010](FEAT-0010-accounts-and-access.md),
  [FEAT-0014](FEAT-0014-integrations.md),
  [ADR-0013](../adr/ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0014](../adr/ADR-0014-events-on-transition-not-per-frame.md),
  [ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md),
  [SEC-0008](../sec/SEC-0008-webhook-signing.md),
  [API Reference, Events](../infrastructure/api.md#events)

## What it does

Turns what the camera sees into records another system can act on. When a known
person appears, an unknown one is enrolled, a catalog object is recognised, a
subject leaves, or the set of things in view changes, an event is recorded and
pushed to whoever asked for it.

Five types are raised, and the first segment of each is its family:

| Type | Raised when |
| --- | --- |
| `person.enrolled` | A person is seen for the first time and enrolled |
| `person.recognised` | A known person appears in view |
| `person.departed` | A subject that had been announced leaves view |
| `object.recognised` | A catalog object appears in view |
| `scene.changed` | The set of subjects present is different |

## How it is implemented

Two services sit behind one call in the detection route. Emission happens on
every detected frame; delivery happens only when emission produced something.

**The event service** compares the frame against the last one for the same owner
and camera and records the difference. It is the whole of
[ADR-0014](../adr/ADR-0014-events-on-transition-not-per-frame.md): a subject is
identified by its catalog entry when recognised and by its class otherwise, an
arrival raises one of the three recognition types, a departure raises
`person.departed` once the subject has been missing for longer than the absence
grace period, and the sorted set of names present is compared as a signature to
decide a `scene.changed`, with a floor between two of those.

The floor delays an announcement rather than cancelling one. The remembered
signature advances only when the event is actually raised, so a change blocked
by the floor is still waiting to be found and the next frame past it raises the
scene as it stands by then. Advancing the signature in both cases, which is what
the service used to do, marked a change as told while nothing was told, and
since the scene then stayed as it was the transition was lost for good; see
[ADR-0020](../adr/ADR-0020-an-event-carries-the-time-it-was-observed.md).

An unrecognised class raises nothing on its own. A bottle nobody taught the
catalog appears in the `present` list of a scene change and nowhere else, and
because it never raised an arrival it never raises a departure either.

Each record is stored as an OpenTelemetry log record, described in
[ADR-0013](../adr/ADR-0013-events-as-opentelemetry-records.md). The event body is
the readable half:

```json
{
  "type": "person.recognised",
  "subject": {
    "id": "0699...",
    "name": "Jorge",
    "class": "person",
    "confidence": 0.9812
  },
  "camera": "front-door",
  "occurredAt": "2026-08-22T18:04:11+00:00",
  "capture": "events/0699.../0699....jpg"
}
```

**The capture** is the frame that produced the event, stored as JPEG in the
object store under `events/{ownerId}/{eventId}.jpg`. An event saying a stranger
appeared is worth far more with the picture attached, and a subscriber cannot
ask for it afterwards because the frame is gone by then. It is downscaled so its
longest side is at most `EVENTS_CAPTURE_MAX_SIDE` pixels, since a capture is
evidence rather than a source image, and a failure to store one is logged and
otherwise ignored: the event is still recorded without it.

One capture is stored per frame, not per event, and attached to the first event
that frame raised. A frame that raises an arrival and a scene change together
puts the picture on the arrival.

**The webhook service** takes the events the frame raised and delivers each to
every active subscription that asked for that type, signed and retried, as
described in [ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md) and
[SEC-0008](../sec/SEC-0008-webhook-signing.md). Failures are counted on the
subscription and an endpoint that keeps failing is switched off. Subscriptions
themselves are created and looked after from the Integrations page, described
in [FEAT-0014](FEAT-0014-integrations.md); this document stays with what is
raised and how it is delivered.

The whole block is guarded. Anything that raises inside it rolls back the event
transaction, logs a warning, and lets the detection response return unchanged.

## The API

Events, all requiring `events:read` except the prune:

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/events` | `events:read` |
| GET | `/events/otlp` | `events:read` |
| GET | `/events/types` | `events:read` |
| GET | `/events/{id}` | `events:read` |
| GET | `/events/{id}/capture` | `events:read` |
| DELETE | `/events/prune` | `events:manage` |

Subscriptions, all requiring `events:manage`:

| Method | Path |
| --- | --- |
| GET | `/webhooks` |
| POST | `/webhooks` |
| PUT | `/webhooks/{id}` |
| POST | `/webhooks/{id}/rotate` |
| POST | `/webhooks/{id}/test` |
| DELETE | `/webhooks/{id}` |
| GET | `/webhooks/headers` |

Both permissions are seeded like every other one and granted to the
administrator role. The full request and response shapes are in the
[API reference](../infrastructure/api.md#events).

## Patterns and interfaces

- **Emission separated from delivery.** The event service knows about scenes and
  transitions and nothing about subscribers; the webhook service knows about
  subscribers and reads what the event service wrote. Adding a second transport
  means adding a reader, not touching emission.
- **Singletons behind an accessor.** Both services are reached through
  `get_event_service()` and `get_webhook_service()`, because the transition
  state has to be the same object across requests.
- **The caller owns the transaction.** Neither service commits. The detection
  route commits once the events are recorded and again after delivery has
  updated the subscription health, so a failure anywhere in the block leaves
  nothing half written.
- **Family based filtering.** A subscription entry may be a family rather than a
  type, so `person` covers every person event including ones added later. The
  same rule applies to the `type` filter when listing events.
- **Signing and verification in one place.** `sign()` and `verify()` sit beside
  each other in the webhook service, so a documented example can be tested
  against the code that produces the signature rather than against a second
  implementation that might disagree with it.
- **Self describing delivery contract.** `GET /webhooks/headers` returns the
  header names and the algorithm, so a receiver can be written without reading
  the source.

## Behaviour worth knowing

- **A capture requires the read permission**, unlike the catalog image proxy at
  `/objects/files/{path}`, which requires no authentication at all
  ([SEC-0003](../sec/SEC-0003-object-storage-exposure.md)). An event capture is
  a photograph of whoever happened to be in front of the camera, and there is no
  reason for it to be readable by anyone holding the URL. The event is also
  filtered by owner, so another user's capture is a `404`.
- **`since` is the polling contract.** Ask for everything after the last event
  already seen. It compares against `occurredAt`, and results are newest first.
- **`occurredAt` is the moment of the observation.** Every timestamp on a record
  comes from one instant taken where the record is built, so events raised by
  one frame are distinct and ordered. Records written before
  [ADR-0020](../adr/ADR-0020-an-event-carries-the-time-it-was-observed.md) hold
  the start of the transaction that wrote them, which every event in that
  transaction shared, so old rows can cluster on identical values and cannot be
  ordered against each other.
- **Retention is manual.** Nothing prunes events on its own.
  `DELETE /events/prune` deletes everything older than the cutoff, defaulting to
  `EVENTS_RETENTION_DAYS`, and a deployment with a retention obligation has to
  call it on a schedule of its own.
- **A restart re-announces the room.** Transition state is in memory by design;
  see [ADR-0014](../adr/ADR-0014-events-on-transition-not-per-frame.md).
- **The scene description is not included.** The event service accepts one and
  puts it in the `scene.changed` body, but the detection route does not pass it,
  so `description` is currently always null. Descriptions come from a separate
  request ([FEAT-0007](FEAT-0007-scene-description.md)).
- **Subscriptions are managed from the Integrations page.** Registering a
  client, filtering its event types, testing it, rotating its secret and
  reading its delivery health all happen there, and that screen is described in
  [FEAT-0014](FEAT-0014-integrations.md). Events themselves still have no
  screen: they are read over the API, or through the protocol server
  ([ADR-0016](../adr/ADR-0016-read-only-protocol-server.md)).
- **Everything is scoped to the owner.** An event belongs to whoever's camera
  raised it and a subscription to whoever created it, so two users of the same
  instance never see each other's events or deliver to each other's endpoints.
- **The whole layer can be switched off.** `EVENTS_ENABLED` stops emission,
  `WEBHOOKS_ENABLED` stops delivery while still recording, and
  `EVENTS_STORE_CAPTURES` stops the pictures without stopping the events.
