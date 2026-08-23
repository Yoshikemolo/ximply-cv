# ADR-0016: Serve observations over a read only protocol server

- **Status**: Accepted. Amended by
  [ADR-0021](ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  which adds three camera tools behind a permission that must be granted by
  name. The server is no longer read only. Everything below about the catalog
  and the record still holds: no tool edits an entry, enrols or renames a
  person, deletes anything, or returns a capture.
- **Related**: [ADR-0013](ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md),
  [ADR-0015](ADR-0015-signed-webhook-delivery.md),
  [ADR-0017](ADR-0017-scoped-tokens-for-machine-clients.md),
  [SEC-0009](../sec/SEC-0009-integration-tokens.md),
  [FEAT-0014](../features/FEAT-0014-integrations.md),
  [API Reference, Model Context Protocol](../infrastructure/api.md#model-context-protocol)

## Context

[ADR-0015](ADR-0015-signed-webhook-delivery.md) gives the event layer a push
surface. A subscriber says once which events it wants and is told when they
happen. That covers a receiver whose job is to react, and it covers nothing
else, because a webhook is a statement and not a conversation. There is no way
to ask one whether the person at the door this morning has been here before.

An agent works the other way round. It has a question at the moment it has it,
and the question is not known in advance. It could be answered by polling the
REST API, but that needs a user's session, and it needs somebody to write a
client against these particular routes and keep it in step with them.

The Model Context Protocol removes the second half of that. A client connects,
asks what tools exist, reads the description of each, and calls them. Nothing
has to be written per agent and per version, and an agent that has never seen
this application can work out what it can ask.

## Decision

A protocol server is mounted alongside the API and offers five tools. Every one
of them reads. None of them writes.

### The tools

| Tool | Answers | Needs |
| --- | --- | --- |
| `list_events` | What happened, newest first, filtered by type or family | `events:read` |
| `get_current_scene` | What is in view now, from the last scene change | `events:read` |
| `list_known_subjects` | The people and objects this instance can recognise | `objects:read` |
| `export_events_otlp` | The same events in the OTLP logs envelope | `events:read` |
| `get_status` | Which models are loaded and whether they are accelerated | `events:read` |

`get_current_scene` returns the age of the record it read alongside its
contents. The most recent scene change may be four seconds old or four days
old, and an agent that is told only what was present has no way to tell those
apart and will report a room that emptied last week as the room now.

### Nothing here writes

The catalog cannot be edited through a tool, a person cannot be enrolled or
renamed, nothing can be deleted, and no subscription or token can be created.
This is the point of the design rather than an unfinished part of it.

An instance of this application watches a physical space and remembers who was
in it. An agent connected to it is steered by text it did not author: the body
of an event, the name somebody gave a catalog entry, whatever the user of the
agent pasted into it. Giving that agent a writable tool means a sentence
arriving from outside can change what a camera remembers about a person. Read
only makes that impossible rather than discouraged, and it is enforced by there
being no such tool to call, which is the only form of enforcement that cannot
be forgotten in a later change.

The integration loses nothing by it. The catalog is taught by standing in front
of the camera and naming what is there
([FEAT-0008](../features/FEAT-0008-teaching-the-catalog.md)), which is work for
the person in the room and not for a remote agent.

### The same record a subscriber receives

`list_events` returns the OpenTelemetry log record described in
[ADR-0013](ADR-0013-events-as-opentelemetry-records.md), field for field as the
webhook delivers it, and `export_events_otlp` calls `build_otlp_envelope()` in
`backend/app/api/routes_events.py`, the same function behind
`GET /api/v1/events/otlp`.

Serving a second shape here would have been easy and would have cost something
real. An agent and a subscriber looking at one arrival would hold two
descriptions of it, and anybody correlating them would have to know which
producer they were reading. Sharing the envelope builder rather than writing a
second one is the same argument at the level of code: two implementations of
one envelope drift, and the drift is discovered by a consumer rather than by a
test.

### Both transports are mounted

Streamable HTTP is served at `/mcp` and server sent events at `/mcp/sse`. The
first is what current clients negotiate; the second is what clients written
before it understand. The server exposes both from the same tool set, so the
choice costs two mounts and no duplicated logic, and offering only the newer
one would have excluded a share of the agents that could otherwise connect for
no benefit at all.

### Mounted rather than routed

The protocol library brings its own ASGI application, so it is mounted rather
than added as a router. That has one consequence worth writing down: Starlette
does not run the lifespan of a mounted application, and the session manager
owns a task group that has to be running before any call is served. It is
entered from the main application's lifespan in `backend/app/main.py`, and
without that every call fails on an uninitialised task group.

## Consequences

- Everything a tool returns is filtered by the owner of the token that called
  it, the same way the REST routes filter on the authenticated user. Two users
  of one instance cannot read each other's events through an agent any more
  than they can through the API.
- The mount is registered at import and its session manager is started during
  the lifespan. If the manager cannot start, the failure is logged and the rest
  of the application serves normally, but calls to the protocol endpoints fail
  rather than being absent. The symptom is a working API and a protocol
  endpoint that answers every call with an error.
- `MCP_ENABLED` set to false skips the mount and the import, so a deployment
  that does not want the protocol does not load the library at all.
- Results are capped: `list_events` returns at most 200 records and
  `export_events_otlp` at most 1000. An agent cannot pull the whole history in
  one call, and one that wants more has to page by time.
- No tool returns an image. A capture is a photograph of whoever was in front
  of the camera, and it stays behind `GET /api/v1/events/{id}/capture` and a
  user session ([SEC-0004](../sec/SEC-0004-biometric-data.md)). An agent is
  told a capture exists and cannot fetch it.
- `get_status` is gated on `events:read` because there is no narrower scope for
  it. Anything that can read events can also see which models are loaded and
  whether they are running on a GPU. That is deployment information rather than
  observation, and it is readable by a token that was only meant to read
  events.
- Each tool opens its own database session rather than sharing one with the
  request, so a call is several independent reads and not a snapshot. Two tools
  called in sequence can see the room in two different states.
