# ADR-0023: A live frame is never stored, and never implied

- **Status**: Accepted. Extends
  [ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  which held remote control of a camera to a different standard from reading.
  The same standard is applied here to seeing through one.
- **Related**: [ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  [ADR-0022](ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md),
  [ADR-0017](ADR-0017-scoped-tokens-for-machine-clients.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md),
  [FEAT-0015](../features/FEAT-0015-streaming.md)

## Context

[ADR-0022](ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md) puts the
frames on a topic and behind an endpoint, and that sentence hides how large a
change it is.

Everything this system published before was a description. An event says a
person was recognised at a time, with a confidence, and a capture of the moment
it happened can be fetched by whoever already has permission to read the event.
A frame stream is not that. It is the room, continuously, to whoever is
listening, for as long as they listen.

[ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md) drew
this distinction once already, between changing a record and switching on a
camera, and concluded that the second is a decision about a physical space with
no undo. Watching that space is the same kind of act. It is quieter, which makes
it worse rather than better: a camera that turns on is at least visible to
somebody in the room.

The convenient thing to do would be to let `events:read` carry it, since a frame
is only ever read. That is exactly the reasoning
[ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)
refused, and refusing it again is the point of this record.

## Decision

A live frame is subject to four rules. Each one is a property somebody can check
rather than a promise.

### It is granted by name

Reaching a frame, on the broker or over HTTP or through a tool, requires
`camera:view` listed on the token. The empty scope list that
`token_allows()` reads as "whatever the owner holds" does not carry it, for the
reason written down in
[ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md): every
token issued before this existed would otherwise acquire a capability nobody
could have considered when they issued it.

It is a separate scope from `camera:control` rather than an extension of it.
They are different acts, they are wanted by different integrations, and a
dashboard that displays the room has no business being able to switch the camera
on. `CAMERA_VIEW_ENABLED` removes the ability from a deployment entirely.

### It is never written down

A frame reaching this system for detection is held in memory, in a slot of one
frame per camera that the next frame overwrites, and is never persisted. It is
not written to object storage, not put in the database, not logged, and not
retained on any topic
([ADR-0022](ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md)).

Event captures are the deliberate exception and they are a different thing: one
image, at a moment something happened, stored against the event that explains
why it was kept, readable by whoever can read that event.

### It flows only while somebody is watching

Nothing is published when nothing is subscribed. The relay counts its
subscribers, and a camera with none does not encode, does not publish and does
not touch the broker. This is what keeps a deployment that enabled the feature
once from broadcasting a room for months because nobody remembered.

It also bounds the cost honestly: the frames are already arriving for detection,
so a viewer adds an encode and a publish and nothing else.

### It says so, where the room can see it

The camera state reports how many subscribers are watching, alongside the
`desiredOn` and `running` it already reported. The interface shows it on the
same screen that shows the camera is on.

A remote viewer that nobody in the room can detect is the failure mode this rule
exists to prevent. It is a weaker guarantee than a hardware indicator and it is
written down as weaker in
[SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md), but a number on
the screen is what this architecture can honestly offer, and offering nothing
was the alternative.

## Consequences

- A token issued before this record cannot watch a camera, and cannot be made
  to. Scopes are fixed at issue
  ([FEAT-0014](../features/FEAT-0014-integrations.md)), so watching means
  issuing a new token deliberately.
- The frame relay is per process and holds one frame per camera, so a deployment
  running several workers serves whichever worker took the last detection
  request. Frames arrive from one browser to one worker at a time in practice,
  and the alternative is putting images through a shared store, which is exactly
  what the second rule forbids.
- A subscriber sees frames only while a browser somewhere is capturing them.
  There is no server-side capture to fall back on
  ([ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)),
  so a stream with the interface closed is an open connection carrying nothing,
  which is the truthful answer rather than a broken one.
- The stream is throttled and downscaled independently of what detection uses.
  A viewer cannot make the camera capture faster, and cannot pull a
  higher resolution image than the one the browser is already sending.
- Counting subscribers is not the same as identifying them. The state says how
  many, and `requested_by` on the camera row still names only who asked it to
  start. Attributing a viewer to a token is a gap and is recorded as one.
