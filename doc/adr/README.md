# Architecture Decision Records

Each record describes one decision, why it was taken, and what it costs. They
are numbered in the order they were made and are not rewritten when superseded:
a later record supersedes an earlier one and says so.

Security decisions are recorded separately, in [doc/sec](../sec/README.md).

| Record | Decision |
| --- | --- |
| [ADR-0001](ADR-0001-run-every-model-locally.md) | Run every model locally |
| [ADR-0002](ADR-0002-people-as-catalog-entries.md) | People are catalog entries in a system category |
| [ADR-0003](ADR-0003-dual-embedding-person-reidentification.md) | Identify people with two embeddings, not one |
| [ADR-0004](ADR-0004-segmentation-never-replaces-detection.md) | Segmentation never replaces detection |
| [ADR-0005](ADR-0005-two-confidences.md) | Report detection confidence and match confidence separately |
| [ADR-0006](ADR-0006-class-aware-suppression.md) | Suppress only boxes that describe the same thing |
| [ADR-0007](ADR-0007-view-filters-applied-server-side.md) | Apply the view filters before deduplication, on the server |
| [ADR-0008](ADR-0008-published-landmark-layouts.md) | Use published landmark layouts and send the edges with the points |
| [ADR-0009](ADR-0009-discover-acceleration-at-runtime.md) | Discover hardware acceleration at runtime |
| [ADR-0010](ADR-0010-local-vision-language-model.md) | Describe scenes with a local vision language model |
| [ADR-0011](ADR-0011-cache-model-weights-in-volumes.md) | Cache model weights in named volumes |
| [ADR-0012](ADR-0012-automatic-enrolment-of-unknown-people.md) | Enrol an unknown person automatically |
| [ADR-0013](ADR-0013-events-as-opentelemetry-records.md) | Record events as OpenTelemetry log records |
| [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md) | An event marks a transition, never a frame |
| [ADR-0015](ADR-0015-signed-webhook-delivery.md) | Deliver events over signed, retried webhooks |
| [ADR-0016](ADR-0016-read-only-protocol-server.md) | Serve observations over a read only protocol server |
| [ADR-0017](ADR-0017-scoped-tokens-for-machine-clients.md) | Authenticate machine clients with scoped tokens |
| [ADR-0018](ADR-0018-acceleration-assigned-per-backend.md) | Assign acceleration per backend at runtime |
| [ADR-0019](ADR-0019-confirm-a-person-before-enrolling-them.md) | Confirm an unknown person before enrolling them |
| [ADR-0020](ADR-0020-an-event-carries-the-time-it-was-observed.md) | An event carries the time it was observed |
| [ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md) | An agent may switch the camera, but never opens it |
| [ADR-0022](ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md) | Carry the live stream on a broker and on a socket |
| [ADR-0023](ADR-0023-a-live-frame-is-never-stored-and-never-implied.md) | A live frame is never stored, and never implied |

## Elsewhere

- [Readme](../../README.md), what the application does and the models it uses
- [System architecture](../infrastructure/architecture.md), the components and
  how they fit together
- [API reference](../infrastructure/api.md)
- [Deployment guide](../operations/deployment.md)
- [Security decisions](../sec/README.md)
