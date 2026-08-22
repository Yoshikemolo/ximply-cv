# ADR-0013: Record events as OpenTelemetry log records

- **Status**: Accepted
- **Related**: [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md),
  [ADR-0015](ADR-0015-signed-webhook-delivery.md),
  [FEAT-0013](../features/FEAT-0013-events-and-webhooks.md),
  [API Reference, Events](../infrastructure/api.md#events)

## Context

An event layer only earns its keep if something else consumes it. The consumers
are other people's systems: a collector, a log backend, an automation rule, a
dashboard. Every one of those already knows how to read a log record.

A shape invented here would have been quicker to write and would have pushed the
cost onto everyone downstream. Each consumer would need a translation layer, and
each translation layer would be written slightly differently. It also throws away
correlation: a record with no trace and span fields cannot be lined up against
the traces the rest of a system emits, so an event is stuck being an isolated
fact rather than a point in a request.

## Decision

An event is stored as an OpenTelemetry log record. The top level fields map one
to one onto the specification:

| Field | Column | Notes |
| --- | --- | --- |
| EventName | `event_name` | The event type, for example `person.recognised` |
| Timestamp | `timestamp_nanos` | Nanoseconds since the Unix epoch |
| ObservedTimestamp | `observed_timestamp_nanos` | Same, as observed here |
| TraceId | `trace_id` | Nullable |
| SpanId | `span_id` | Nullable |
| TraceFlags | `trace_flags` | Defaults to 0 |
| SeverityNumber | `severity_number` | Defaults to 9 |
| SeverityText | `severity_text` | Defaults to `INFO` |
| Body | `body` | The human readable payload |
| Attributes | `attributes` | Flat, dotted keys |
| Resource | `resource` | What emitted the record |
| InstrumentationScope | `scope_name`, `scope_version` | What produced it |

Timestamps are kept in nanoseconds because that is what the specification
requires and what a trace timestamp is compared against. A timestamp column
cannot hold that precision, so the nanosecond value is stored alongside the
ordinary `occurred_at` column used for ordering and filtering.

Severity follows the specified bands. Nine to twelve is the informational band,
and an observation is informational, so every event this instance raises carries
severity number 9 with the text `INFO`. Leaving room above means a later
condition that genuinely is a warning can be raised as one without renumbering
anything.

Attributes are flat and dotted, as the semantic conventions require, rather than
nested objects. Application specific keys sit under a `ximply` namespace so they
cannot collide with a convention that gets standardised later:

```json
{
  "event.name": "person.recognised",
  "ximply.owner.id": "0699...",
  "ximply.subject.id": "0699...",
  "ximply.subject.name": "Jorge",
  "ximply.subject.confidence": 0.9812,
  "ximply.camera.id": "front-door",
  "ximply.capture.path": "events/0699.../0699....jpg"
}
```

Resource carries the standard service attributes, `service.name`,
`service.version` and `service.namespace`, so a collector groups these records
with everything else the same deployment sends instead of treating them as an
unrelated stream.

## Consequences

- An OTLP envelope export exists at `GET /api/v1/events/otlp`. It groups records
  by resource and by instrumentation scope, which is the structure an OTLP
  consumer expects, so the result can be posted to a collector or read by a
  backend that already ingests logs with no translation step.
- The domain columns below the standard ones, `owner_id`, `subject_id`,
  `subject_name`, `confidence`, `camera_id` and `capture_path`, duplicate values
  that are also in attributes. They exist only so the database can index and
  filter on them, which it does poorly against a JSON blob. Attributes remain
  the source of truth for anything delivered: a webhook payload and the OTLP
  export both read attributes, not columns.
- That duplication has to be maintained. When a capture is attached after the
  record is built, both the column and the attribute are updated, and any future
  field that is projected into a column has to do the same.
- The trace and span columns are present, indexed and currently never populated.
  Nothing in this application starts a trace, so every event has a null trace id
  today. The columns are there so that correlation becomes a matter of filling
  them in rather than a migration.
- The shape is more verbose than a bespoke one. A consumer that only wants to
  know who walked in reads `body`, and the interface offers the same values as
  flat convenience fields on the event response, so the verbosity is a cost paid
  by the store rather than by a simple client.
