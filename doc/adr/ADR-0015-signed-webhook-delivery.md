# ADR-0015: Deliver events over signed, retried webhooks

- **Status**: Accepted
- **Related**: [ADR-0013](ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md),
  [SEC-0008](../sec/SEC-0008-webhook-signing.md),
  [FEAT-0013](../features/FEAT-0013-events-and-webhooks.md),
  [API Reference, Webhooks](../infrastructure/api.md#webhooks)

## Context

Events exist to be acted on by something else. Polling the event list works and
is the fallback, but it trades latency against load: a client that wants to know
within a second that someone walked in has to ask every second, and almost every
one of those requests returns nothing, because
[ADR-0014](ADR-0014-events-on-transition-not-per-frame.md) makes events rare on
purpose.

Pushing instead raises three questions that a naive implementation gets wrong.
The receiver has to be able to tell a genuine delivery from anything else that
can reach its URL. A receiver that is briefly down has to not lose the event.
And the camera has to keep working when the receiver misbehaves.

## Decision

A subscription is a name, a URL, an optional list of event types and a secret.
Every delivery to it is signed, retried, and isolated from detection.

### Signed with a per subscription secret

The secret is 32 random bytes, hex encoded, generated when the subscription is
created and returned exactly once in that response. It can be replaced through
the rotate endpoint, which returns the new value once in the same way, and is
never readable afterwards.

Each request carries the signature, the timestamp it was signed at, the event
type and the delivery id in headers, and the signature is HMAC-SHA256 over the
timestamp, a full stop, and the exact body bytes. Why that construction and not
a bearer token or SHA-1 is the whole subject of
[SEC-0008](../sec/SEC-0008-webhook-signing.md).

The body is serialised once, with sorted keys and no whitespace, and those bytes
are what is both signed and sent. Re-encoding before sending would produce a
different byte string and invalidate the signature, which is the usual way this
kind of scheme is broken.

### Retried with backoff, then disabled

A delivery is attempted up to `webhook_max_attempts` times, three by default,
with a timeout of `webhook_timeout_seconds` on each. Between attempts it backs
off, one second then two, so a receiver that is restarting is given room rather
than being hit three times in a row. Any 2xx status ends the attempt loop
successfully; anything else is a failure and is retried.

The outcome is recorded on the subscription: the time of the last delivery, the
last status code, the last error and a count of consecutive failures. A success
resets the count to zero. Once the count reaches
`webhook_disable_after_failures`, twenty by default, the subscription is
switched off. An endpoint that has been gone for twenty events is not coming
back on its own, and continuing to retry it wastes a request budget on every
event forever. Re-enabling a subscription clears the failure count, so a
subscription disabled for failing does not switch itself off again on the first
subsequent error.

### Delivery never changes the detection result

Event emission and delivery sit inside a guard in the detection route. If
anything in that block raises, the transaction is rolled back, a warning is
logged, and the detection response is returned as if no event layer existed. A
broken subscriber cannot fail a frame, and cannot change a single detection or
confidence in the response.

### The payload is the whole record

A delivery carries the full log record, not just its body: id, event name, both
nanosecond timestamps, severity number and text, trace and span ids, body,
attributes, resource and scope. A receiver that already handles OpenTelemetry
data consumes it without a translation step, and one that does not reads `body`
and ignores the rest.

### Filtering is by family or by type

An empty `eventTypes` list means every event. An entry matches either a whole
type, `person.departed`, or a family, `person`, which matches every event whose
type starts with that family, including types added to it in a later version.
Subscribing to `person` is therefore a durable subscription to people rather
than a list that has to be revisited when a new person event is introduced.
Unknown entries are rejected with `422` when the subscription is created.

## Consequences

- A receiver can be written against the headers alone. `GET
  /api/v1/webhooks/headers` names them and the algorithm, and `POST
  /api/v1/webhooks/{id}/test` sends a signed test delivery, so an endpoint can
  be proved to work before it has to.
- Delivery is awaited within the detection request that raised the event, so a
  slow subscriber delays that one response even though it cannot change it. The
  worst case is bounded by the attempt count, the timeout and the backoff, and
  is around thirty three seconds per matching subscription at the defaults. A
  deployment with a subscriber that answers slowly should lower
  `webhook_timeout_seconds` rather than rely on the receiver behaving.
- Retries mean a receiver can be delivered the same event twice, since an
  attempt that timed out may still have been processed. Receivers must be
  idempotent, keyed on the delivery id.
- Every subscription is delivered every matching event separately. Deliveries
  are not batched, so a scene change that also raised two arrivals is three
  requests.
- Rotating a secret takes effect from the next event onwards, so the receiver
  has to be updated first or it will reject the deliveries in between. This and
  the other limits are written down in
  [SEC-0008](../sec/SEC-0008-webhook-signing.md#known-gaps).
