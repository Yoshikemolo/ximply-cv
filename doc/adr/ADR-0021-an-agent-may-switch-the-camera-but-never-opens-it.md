# ADR-0021: An agent may switch the camera, but never opens it

- **Status**: Accepted. Amends
  [ADR-0016](ADR-0016-read-only-protocol-server.md), which decided that no tool
  writes. Its reasoning about the catalog stands unchanged and is reinforced
  here. What changes is that one thing outside the catalog can now be asked for.
- **Related**: [ADR-0016](ADR-0016-read-only-protocol-server.md),
  [ADR-0017](ADR-0017-scoped-tokens-for-machine-clients.md),
  [SEC-0009](../sec/SEC-0009-integration-tokens.md),
  [SEC-0010](../sec/SEC-0010-remote-camera-activation.md),
  [FEAT-0014](../features/FEAT-0014-integrations.md),
  [API Reference, Model Context Protocol](../infrastructure/api.md#model-context-protocol)

## Context

[ADR-0016](ADR-0016-read-only-protocol-server.md) argues that an agent steered
by text it did not author must not be able to change what a camera remembers
about people. That argument is about the catalog and the record, and it is
correct.

It does not settle a different question. An agent that can read what the camera
saw cannot do anything when the camera is off, and turning it on is not a change
to any record. Every use of the protocol that involves acting rather than
reporting runs into this: a schedule that should start watching at opening time,
an assistant asked to check the room, anything at all when nobody is sitting in
front of the screen.

The two are not the same kind of act, and collapsing them under "read only"
loses a capability for a reason that does not apply to it.

They are not the same in the other direction either, and this matters more.
Editing a catalog entry is a change to data that can be reviewed and reversed.
Switching on a camera in somebody's room is neither. It is a privacy decision
about a physical space, taken remotely, and no undo exists for the seconds it
was on.

## Decision

The protocol offers three camera tools. They are held to a different standard
from everything else it serves, in four ways.

| Tool | Does | Needs |
| --- | --- | --- |
| `get_camera` | Reports the state a camera is wanted in and whether it is running | `events:read` |
| `start_camera` | Asks for a camera to run | `camera:control`, by name |
| `stop_camera` | Asks for a camera to stop | `camera:control`, by name |

### An agent records a wish; it does not open a device

The camera belongs to the browser. Frames are captured there with the device
APIs the browser exposes and posted for detection, and nothing in the server
process can open a camera however the API is shaped.

So `start_camera` writes a row saying the camera is wanted on. An open interface
polls that state and honours it. If none is open, nothing happens.

This is a constraint of the architecture rather than a policy, but it is a good
constraint and it is written down as part of the decision, because a later
change that put a capture device on the server would quietly remove a property
this decision depends on: there is always a browser, on somebody's machine, that
has to be running and has to have been granted the camera by its user.

### The reply says what happened, not what was asked for

`running` is never taken on trust from whoever made the request. It is decided
by frames arriving for detection, within `CAMERA_LIVE_GRACE_SECONDS`. A request
with no interface listening comes back `pending` with a note saying so.

An agent told "started" for a camera that never started will report a room it
cannot see. Being told "requested, and nothing is listening" is the answer that
lets it say something true.

### The permission is granted by name or not at all

`token_allows()` treats an empty scope list as "whatever the owner holds", which
is a reasonable default for reading. Control does not use it. `_require_explicit()`
demands `camera:control` be listed on the token.

The reason is specific: every token issued before this existed has an empty or
narrower scope list, and reading consent into that silence would hand a camera
switch to integrations created to watch events. A permission that appears on
credentials written before anybody could have considered it was never granted.

`CAMERA_CONTROL_ENABLED` removes the ability from a deployment entirely.

### The protocol itself can be closed from the interface

A switch in the footer opens and closes the protocol at runtime, behind
`events:manage`. Closing it leaves both transports mounted and refuses them with
503, so a connected agent gets an answer rather than a hole.

This belongs with the decision above rather than beside it. Granting a remote
capability without a way to revoke it quickly means the only way to stop an
agent is to redeploy. The state is held in the process, like the acceleration
preference in [ADR-0018](ADR-0018-acceleration-assigned-per-backend.md), and is
thrown per worker for the same reason.

## Consequences

- The protocol is no longer read only, and describing it that way is now wrong.
  The tools that read still only read: the catalog cannot be edited, a person
  cannot be enrolled or renamed, nothing can be deleted, and no capture can be
  fetched. Every word of [ADR-0016](ADR-0016-read-only-protocol-server.md) about
  the record holds.
- An agent can cause a camera to start recording a physical space. This is the
  serious consequence and it is treated as a security decision in
  [SEC-0010](../sec/SEC-0010-remote-camera-activation.md).
- Requests survive restarts because they are rows, and are reached from any
  worker for the same reason. They also persist across a closed browser: a
  camera asked to start while nobody was looking starts when somebody opens the
  page, which may be much later. `stop_camera` clears it, and the interface
  records the state when somebody uses the button, so the two never disagree.
- The interface polls every two seconds, so that is the delay between asking and
  the camera opening. A stream would be tighter; a boolean is not worth one.
- `requested_by` names the token behind a request, so a camera that turned itself
  on can be traced. The heartbeat that decides `running` is throttled to
  `CAMERA_HEARTBEAT_SECONDS`, so a frame is never a write.
- The browser may still refuse. A page that has not been granted the camera by
  its own user cannot open it, and no request from here changes that. The
  interface records the failure so the state does not read as running.
