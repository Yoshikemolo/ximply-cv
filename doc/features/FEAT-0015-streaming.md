# FEAT-0015: Streaming

- **Related**: [FEAT-0013](FEAT-0013-events-and-webhooks.md),
  [FEAT-0014](FEAT-0014-integrations.md),
  [ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md),
  [ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md),
  [ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md),
  [API Reference, Streaming](../infrastructure/api.md#streaming)

## What it does

Lets something subscribe to this instance instead of being subscribed to. A
webhook needs the receiver to be a server
([FEAT-0013](FEAT-0013-events-and-webhooks.md)); this needs a terminal.

Two ways in, carrying the same records:

- **A broker.** Events, captures and live frames are published to MQTT, where
  `mosquitto_sub` reads them without any code being written.
- **An HTTP stream.** `GET /stream/events` is server sent events and
  `GET /stream/camera/{id}` is a multipart JPEG stream, so `curl -N` and
  `ffplay` are enough and no broker has to be deployed.

Both are off unless a deployment turns them on, and the frames are off
separately from the events.

## The broker

**The topic tree** is fixed, and the owner id is in the path so a broker ACL can
be written per account:

| Topic | Payload | QoS | Retained |
| --- | --- | --- | --- |
| `ximply/<instance>/events/<owner>/<type>` | The log record, as JSON | 1 | No |
| `ximply/<instance>/captures/<owner>/<event>` | The capture, as JPEG | 0 | No |
| `ximply/<instance>/camera/<owner>/<camera>/frame` | The live frame, as JPEG | 0 | No |
| `ximply/<instance>/status` | `online` or `offline` | 1 | Yes |

`<instance>` is `MQTT_INSTANCE`, so several deployments can share one broker
without colliding. The event payload is the same record a webhook delivery
carries, built by the same function, so a receiver written for one reads the
other.

**The status topic is a last will.** The broker publishes `offline` on it if the
connection drops without a goodbye, so a subscriber can tell "nothing is
happening" from "nothing is running" without asking.

**Publishing never delays a frame.** Records are handed to a bounded queue and
written by one background task. A broker that is unreachable fills the queue,
drops the oldest entries and counts them; detection does not wait and does not
fail ([ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md)).

## The HTTP stream

**`GET /stream/events`** is server sent events. Each message is one record, the
same JSON as the broker payload, with the event type in the SSE `event` field so
a browser can use `addEventListener` per type. A comment line is sent every
`STREAM_KEEPALIVE_SECONDS` so an idle connection survives a proxy.

**`GET /stream/camera/{camera_id}`** is `multipart/x-mixed-replace`, the format
every browser and every player already reads. Frames are downscaled to
`STREAM_CAMERA_MAX_SIDE`, encoded at `STREAM_CAMERA_QUALITY` and rate limited to
`STREAM_CAMERA_MAX_FPS`, independently of what detection runs at.

**`GET /stream/info`** describes what is available: whether the broker is
connected, its address, the topic templates, the endpoint paths and which scopes
they need. The interface builds its examples from it rather than hard coding
them.

**Both authenticate with an integration token or a session.** The token goes in
`Authorization`, and only there: accepting it in the query string would make an
`img` tag work at the cost of putting a live credential in browser history and
proxy logs ([SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md)). This
is the first time an integration token reaches a route outside the protocol
mounts, and the scope rules are the same ones the protocol applies.

**A disconnected client ends the stream.** Both generators check
`request.is_disconnected()` on every iteration, for the reason the detection
stream already does: an endless generator and a graceful shutdown that waits for
open connections leaves the port bound.

## Watching a camera

Reaching a frame needs `camera:view` written on the token by name, and
`CAMERA_VIEW_ENABLED` true in the deployment. It is a separate scope from
`camera:control` because showing a room and switching a camera on are different
acts wanted by different integrations
([ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)).

Frames are not stored anywhere and are not encoded at all when nobody is
subscribed. The camera state gained a `viewers` count next to `running` and
`pending`, and the interface shows it wherever it shows the camera is on, so
being watched is visible on the screen in the room.

## The streaming tab

A third tab on `/integrations`, beside Webhooks and MCP, behind the same
`events:manage`.

**The status line** reports whether the broker is connected and how many records
have been dropped, which is the one number that says a subscriber is losing
data.

**The address field** works like the one on the MCP tab: it starts as the
address the browser is using and rewrites every example below when it is edited,
so what gets copied is what will run.

**The topic table** is rendered from `/stream/info`, so a topic added to the
backend appears here with no frontend change.

**The examples** cover the shell first, because that is the point of the
feature: `mosquitto_sub` for the broker, `curl -N` for the events, `ffplay` for
the camera. Then Angular, React and plain JavaScript, each consuming the same
two endpoints, and each written so the credential is substituted when a token
has just been issued.

The JavaScript and React examples use `fetch` with a `ReadableStream` rather
than `EventSource`, because `EventSource` cannot send an `Authorization` header
and the endpoint does not accept a token any other way. The Angular example uses
the same approach inside a service returning a signal, which is how the rest of
this frontend is written.

## How it is implemented

**`StreamHub`** (`app/services/stream_service.py`) is the in-process fan-out: a
set of bounded queues per owner for events, and per owner and camera for frames.
`offer_frame` returns immediately without encoding when the subscriber set is
empty, which is what makes the "nothing is published to nobody" rule cheap
rather than aspirational. It holds one frame per camera and overwrites it.

**`MqttPublisher`** (`app/services/mqtt_service.py`) owns the connection and the
outbound queue. The topic builders are plain functions taking the prefix, the
instance and the ids, so they are tested without a broker, and the payload comes
from `webhook_service._delivery_payload`, which is why the two transports cannot
drift apart.

**The seam** is the existing guard block in the detection route
([ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md)). After the webhook
dispatch, the same `raised` list is handed to the hub and to the publisher, both
of which return without awaiting any network. Frames are offered next to the
camera heartbeat, a few lines above.

**`stream_principal`** (`app/core/stream_auth.py`) is the dependency that
accepts either credential. It resolves an `xvt_` value through the same
`resolve_token`, applies `token_allows` for reading and an explicit membership
check for `camera:view`, and falls back to the JWT user when the header carries
one.

**Nothing was added to the schema.** The hub, the queues and the connection are
per process and in memory, like the protocol switch and the acceleration
preference, and `viewers` is computed when the camera state is read rather than
stored.

## Patterns and interfaces

- **One payload builder, two transports.** The broker and the webhook path
  serialise the same dictionary. A change to the record shape is one edit.
- **The scope is checked the way the protocol checks it.** `camera:view` uses
  the explicit membership test written for `camera:control`
  ([ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)),
  so an empty scope list never inherits it.
- **The interface reads `/stream/info`.** Topics, paths and scopes are described
  by the server, in the same way the event type chips are
  ([FEAT-0014](FEAT-0014-integrations.md)).
- **Bounded and lossy on purpose.** Every queue has a size and drops the oldest.
  A slow subscriber degrades itself and nothing else.
- **Examples are data.** The streaming snippets are entries in
  `integration-examples.ts` like the others, built by a function taking the
  address and the credential.

## Behaviour worth knowing

- **The stream is not a record.** A dropped publish is not retried and nothing
  reconciles it later. Anything that must not miss an event reads the event list
  or registers a webhook.
- **Ordering holds within a topic, not across them.** A capture can arrive
  before the event that names it, so a consumer joining them keys on the event
  id.
- **A frame stream with no interface open carries nothing.** There is no
  server-side capture. The connection stays open and silent until a browser
  starts sending frames again.
- **The broker cannot count its viewers.** MQTT does not tell a publisher who is
  subscribed, so a camera watched over the broker shows `viewers` of zero. This
  is the weakest point of the design and is written down as such in
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).
- **Per worker, like everything else in memory here.** Several workers mean
  several hubs and several broker connections, each publishing what its own
  requests raised.
- **`MQTT_ENABLED` is read at startup.** There is no runtime switch for the
  broker the way there is for the protocol; turning it on is a restart.
- **Captures are published only when `MQTT_PUBLISH_CAPTURES` is on.** A
  deployment that wants event records on the broker without images gets that by
  leaving it off, and `CAMERA_VIEW_ENABLED` off separately keeps live frames out
  of both transports.
- **A token issued before this cannot watch.** Scopes are fixed at issue, so
  watching means issuing a new token with `camera:view` ticked.
