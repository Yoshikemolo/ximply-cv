# ADR-0022: Carry the live stream on a broker and on a socket

- **Status**: Accepted
- **Related**: [ADR-0013](ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md),
  [ADR-0015](ADR-0015-signed-webhook-delivery.md),
  [ADR-0017](ADR-0017-scoped-tokens-for-machine-clients.md),
  [ADR-0023](ADR-0023-a-live-frame-is-never-stored-and-never-implied.md),
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md),
  [FEAT-0015](../features/FEAT-0015-streaming.md),
  [API Reference, Streaming](../infrastructure/api.md#streaming)

## Context

[ADR-0015](ADR-0015-signed-webhook-delivery.md) pushes each event to a URL the
receiver runs. That is the right shape for a system integration and the wrong
shape for everything else, because it requires the subscriber to be a server:
a reachable address, a certificate, a handler that verifies a signature before
it reads the body. Somebody who wants to watch what the camera is seeing has to
deploy a web service first.

The people who ask for this are not building an integration. They are at a
terminal, or writing a twenty line script, or standing in front of a dashboard
that has to show the room. For them the useful question is not "where do I
receive a POST" but "what do I connect to".

Polling the event list answers it badly, for the reasons already written down in
[ADR-0015](ADR-0015-signed-webhook-delivery.md): almost every request returns
nothing, because [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md)
makes events rare on purpose.

There is also a second thing to carry, which webhooks never carried. An event
says a person arrived. It does not show the room. Anything that wants to look
at the room needs the frames themselves, and frames are not records: they are
large, they are continuous, and they are the most sensitive thing this system
touches.

## Decision

The same records travel on two transports, chosen by the subscriber rather than
by this instance.

### A broker, for a subscription that outlives the connection

Events are published to MQTT. The topic tree is fixed and flat enough to filter
with a wildcard:

| Topic | Payload | QoS | Retained |
| --- | --- | --- | --- |
| `ximply/<instance>/events/<owner>/<type>` | The full log record, as JSON | 1 | No |
| `ximply/<instance>/captures/<owner>/<event>` | The capture, as JPEG bytes | 0 | No |
| `ximply/<instance>/camera/<owner>/<camera>/frame` | The live frame, as JPEG bytes | 0 | No |
| `ximply/<instance>/status` | `online` or `offline` | 1 | Yes |

The record on the events topic is the one
[ADR-0015](ADR-0015-signed-webhook-delivery.md) already defined, unchanged, so a
receiver written for a webhook body reads a broker message without a translation
step.

Events are sent at QoS 1 because a subscriber that misses an arrival has missed
the thing it subscribed for, and receivers are already required to be idempotent
on the delivery id. Images are sent at QoS 0 because a frame that arrives late
is worth nothing and paying for its redelivery costs the frames behind it.

Nothing carrying an observation is retained. A retained event would be handed to
every subscriber that connected afterwards, which reads as "this is happening"
for something that happened at a time the record itself names
([ADR-0020](ADR-0020-an-event-carries-the-time-it-was-observed.md)). The status
topic is retained, and is the exception that proves the rule: it is a state
rather than an observation, and a subscriber needs it before anything else
happens.

The owner id sits in the topic so a broker can be given an ACL per account. This
instance does not enforce that separation at the broker, and what that costs is
[SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

### A socket, for a subscriber that has no broker

`GET /stream/events` is server sent events over the same records, and
`GET /stream/camera/{camera_id}` is `multipart/x-mixed-replace` over the frames.
Both are reachable with an integration token, and both were chosen because they
are consumable with a program that is already installed: `curl -N` reads the
first, any browser and `ffplay` read the second.

This exists so the broker is optional. A deployment that does not want to run
one, or a person who wants to see something working in the next ten seconds,
should not have to.

Serving those endpoints to a machine client means an integration token has to
authenticate a REST route, which until now it could not: tokens reached the
protocol mounts and nothing else. The dependency that accepts one applies the
same scope rules as the protocol, including
[ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)'s rule
that a capability outside reading is granted by name or not at all.

### Publishing does not happen on the detection path

[ADR-0015](ADR-0015-signed-webhook-delivery.md) awaits each webhook inside the
detection request, and accepts the latency because the outcome of that delivery
is recorded on the subscription and shown on screen. A broker publish has no
per-subscriber outcome to record and nothing to show, so it buys nothing with
the same wait.

Events are handed to a bounded queue and published by one background task. When
the queue is full the oldest entry is dropped and counted. A broker that is
down, slow or gone therefore costs a bounded amount of memory and no detection
latency at all, which is the property that matters: the camera keeps working
when the thing listening to it does not.

One task rather than several, because ordering within a topic is worth more here
than throughput. Frames are already lossy by design and events are already rare.

## Consequences

- The stream is a live view, not a second record. A dropped publish is not
  retried and nothing reconciles it afterwards. What was observed is in the
  database and is still delivered by webhook; a subscriber that needs every
  event without exception reads the event list or registers a subscription.
- Ordering holds within a topic and not across topics. A capture may reach a
  subscriber before the event that refers to it, so a consumer that joins the
  two keys on the event id rather than on arrival order.
- Running a broker is a deployment decision. With `MQTT_ENABLED` false the
  publisher is never started, the HTTP stream still works, and the rest of the
  application does not know the difference.
- Two transports mean two places a change to the record shape has to be thought
  about. They are fed from one payload builder, the same one the webhook path
  uses, so the shape cannot drift between them.
- Frames on the broker are the serious consequence, and they are held to a
  different standard than the rest of this record. What that standard is, is
  [ADR-0023](ADR-0023-a-live-frame-is-never-stored-and-never-implied.md).
