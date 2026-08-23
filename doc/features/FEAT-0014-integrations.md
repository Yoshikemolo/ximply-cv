# FEAT-0014: Integrations

- **Related**: [FEAT-0010](FEAT-0010-accounts-and-access.md),
  [FEAT-0013](FEAT-0013-events-and-webhooks.md),
  [FEAT-0015](FEAT-0015-streaming.md),
  [ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md),
  [ADR-0016](../adr/ADR-0016-read-only-protocol-server.md),
  [ADR-0017](../adr/ADR-0017-scoped-tokens-for-machine-clients.md),
  [ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  [ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md),
  [SEC-0008](../sec/SEC-0008-webhook-signing.md),
  [SEC-0009](../sec/SEC-0009-integration-tokens.md),
  [SEC-0010](../sec/SEC-0010-remote-camera-activation.md),
  [SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md),
  [API Reference, Webhooks](../infrastructure/api.md#webhooks)

## What it does

Gives the event layer a screen. Everything
[FEAT-0013](FEAT-0013-events-and-webhooks.md) describes was managed over HTTP
and nowhere else; this is where a client is registered, tested, rotated and
switched off, and where an agent is given a way in.

It lives at `/integrations`, behind `events:manage`, and appears in the
navigation only for an account that holds it
([FEAT-0010](FEAT-0010-accounts-and-access.md)). Three tabs, presented as
alternatives rather than steps, because a deployment usually wants one of them:

- **Webhooks**, where this instance pushes each event to an endpoint you run.
- **MCP**, where an agent connects and pulls what it wants to know.
- **Streaming**, where a broker or a terminal subscribes to what is happening
  as it happens, described in [FEAT-0015](FEAT-0015-streaming.md).

Each tab carries a count of what is registered and an indicator that reads
Active when at least one client on that tab is switched on.

## The webhooks tab

**A registered client** is a name and a URL. Register one and its signing secret
is generated and shown, once, in a panel below the form. It is stored hashed
and cannot be displayed again, which the panel says plainly; copy it into the
receiver before leaving the page.

**Event filtering** is a row of chips under the form, families first and then
whole types, read from `GET /events/types` rather than hard coded. Selecting
`person` subscribes to every person event including ones added in a later
version. Selecting nothing sends everything.

**Each client in the list** shows a toggle, its name and URL, and its delivery
health as chips: the event types it asked for or "All events", the HTTP status
of the last delivery, and the number of consecutive failures when there have
been any. That is enough to answer the question somebody actually has, which is
whether the endpoint is working, without opening a log.

**Three actions** sit on each client:

- **Test** sends a signed delivery with a small test body rather than a real
  event, records the outcome in the same delivery health fields, and reports
  back what the endpoint answered. A failure is reported as a message, not an
  error: a test that fails has told you what you asked.
- **Rotate secret** replaces the secret and reveals the new one the same way.
  Deliveries are signed with it from the next event onwards and there is no
  overlap window, so the receiver has to be updated first
  ([SEC-0008](../sec/SEC-0008-webhook-signing.md#known-gaps)).
- **Delete** removes the subscription.

**The receiver examples** are complete, ready to paste, and cover Node.js,
NestJS, Python with FastAPI, Java Spring and .NET 9. Every one of them verifies
the signature before it looks at the body: it computes HMAC-SHA256 over the
timestamp, a full stop and the raw request bytes, rejects a delivery more than
300 seconds old, and compares the result in constant time. That is not
decoration. An example that skipped the check would teach people to run an
endpoint anyone on the network can feed, and the verification is the whole
point of the delivery being signed. When a secret has just been issued it is
substituted into the snippet, so the code can be copied and run without editing
anything.

## The MCP tab

**A token** is issued with a name and a set of scopes, chosen from
`events:read`, `objects:read`, `events:manage`, `camera:control` and
`camera:view`, with `events:read` selected to begin with. The first three read
or manage records. The last two are different in kind: one lets an agent ask the
camera to start and the other lets it watch what the camera sees, and both are
decisions about a room rather than queries, so neither is ever implied by the
others and each has to be ticked deliberately. Issue them on tokens of their own
rather than on the one pasted into every integration; the reasoning is in
[SEC-0010](../sec/SEC-0010-remote-camera-activation.md) and
[SEC-0011](../sec/SEC-0011-broker-and-live-frame-exposure.md).

The value is shown once, in the same reveal panel with the same warning, and
afterwards the list shows only the first ten characters. Grant the narrowest set
that works: the reasoning, and what a leaked token reaches, is in
[SEC-0009](../sec/SEC-0009-integration-tokens.md).

**Each token in the list** shows a toggle, its name, its prefix, its scopes or
"All scopes", and whether it has ever been used. Switching a token off leaves
it in the list and stops it working immediately; revoking deletes it. Both take
effect on the next call the agent makes.

**The address field** is where the agent should reach this instance. It starts
as the address the browser is using, which is right when the agent runs on this
machine and wrong the moment it does not: a container or another host cannot
resolve `localhost` here. Editing it rewrites every configuration example
below, so the snippet that gets copied is the one that will work.

**The client configurations** cover Claude, ChatGPT and Gemini, a variant for
clients that predate streamable HTTP and connect over server sent events at
`/mcp/sse`, and a pair of `curl` commands that open a session and list the
tools. The last one exists so the connection can be proved before an agent is
configured against it, which turns "the agent cannot see my camera" into two
commands rather than a debugging session.

**The tools** are listed at the bottom of the tab with one line each, reading
tools first and the camera tools after them, marked with the scope they need.
The page ends by saying what the boundary is: the reading tools cannot change
any record, the camera tools can only ask for a camera to start or stop and
never open one, and the one tool that answers with an image answers with a live
frame rather than anything the instance kept. What that boundary is for is
[ADR-0016](../adr/ADR-0016-read-only-protocol-server.md) and
[ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md).

## The switch in the footer

The protocol is opened and closed from a switch in the application footer,
present on every page, behind the same `events:manage` that gates this page. A
lit dot means agents can connect; grey means the door is shut and every call is
refused with a `503` while both transports stay mounted.

It is in the footer rather than on this page on purpose. Wanting the camera to
stop being reachable is not something that happens while administering
integrations, and a control that can only be reached by navigating to the right
tab is a control that is not there when it is needed. A deployment built without
the protocol shows nothing at all, since there is no switch to offer.

Whoever lacks `events:manage` still sees the state. Knowing whether the camera
is reachable is not the same as deciding it, and the first matters to anyone
looking at the screen.

## How it is implemented

One standalone component, `IntegrationsPageComponent`, over one service,
`IntegrationsService`, which wraps the webhook, token and event type endpoints
together. Three services would have moved the joins into the component for no
gain: the page presents all of this as one subject.

State is signals throughout. The lists are loaded on init and updated in place
after a change rather than refetched, except after a test, which reloads
because the delivery health it just changed lives on the server.

A revealed credential is held in its own signal rather than on the record it
belongs to. The record is refreshed from the server and the value is not part
of it, so attaching it there would mean losing it on the next update or
carrying a field that is null in every other case.

The examples are in `integration-examples.ts`, separate from the component,
because they are content rather than behaviour and four hundred lines of sample
code in front of the logic is a component nobody maintains. Both example sets
are built by a function taking the value to substitute, so the same snippet
renders with a placeholder before a credential exists and with the real one
after.

## Patterns and interfaces

- **Reveal once, everywhere.** The secret and the token are handled identically:
  returned in the response that issues them, held in a signal, shown in a panel
  with a warning and a Hide button, and never fetched again. One rule rather
  than two, so neither can drift into being readable.
- **The permission gates the route and the navigation.** `events:manage` is
  checked by the route guard and by the header and side menu, so an account
  without it does not see the entry and cannot reach the page by typing the
  address.
- **Event types come from the server.** The chips are built from
  `GET /events/types`, so a type added to the backend appears here with no
  frontend change.
- **The toggle is the state.** Enabling and disabling both go through the same
  update call that changes anything else about a client, so there is no
  separate enable endpoint to keep in step.
- **Examples are data.** An `Example` is an id, a label, a language, a caption
  and a body, rendered by the shared code snippet component. Adding a framework
  is adding an entry.

## Behaviour worth knowing

- **Delete and revoke ask nothing.** Neither action has a confirmation step. A
  deleted subscription and a revoked token are gone, and the token cannot be
  recovered even by the person who issued it.
- **A token's scopes cannot be changed after issue.** The update endpoint takes
  only the active flag. Narrowing or widening a token means issuing a new one
  and revoking the old. A token issued before `camera:control` existed therefore
  cannot acquire it, which is intended rather than incidental.
- **`camera:control` and `camera:view` are never inherited.** A token with no
  scopes carries whatever its owner carries for reading; the camera tools and
  the frame stream refuse it unless the scope is on the token by name.
- **Scopes cannot exceed the issuer.** A user who does not hold a permission
  cannot put it on a token. After a new permission is added to the system, an
  existing session has to sign in again before it can grant it, because the
  check reads the permissions in the current token.
- **A client disabled by repeated failures reappears as off.** Twenty
  consecutive failures switch a subscription off on the server
  ([ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md)). The toggle shows
  that state, and switching it back on clears the failure count.
- **The test result is a message, not a status.** It reports the HTTP code the
  endpoint answered, or the transport error, in the banner at the top of the
  page.
- **The footer switch is per process.** The state is held in memory, like the
  acceleration preference, so a deployment running several workers throws it per
  worker. `MCP_ENABLED` is the deployment-wide answer and is read at startup.
- **This page does not show events.** There is still no screen that lists what
  was observed; events are read over the API, or through an agent. The tabs
  here are about who receives them.
- **Everything is scoped to the owner.** A subscription and a token belong to
  whoever created them, and so do the events they carry, so two users of one
  instance never see each other's clients.
- **The protocol tab is useful only when the server is mounted.** `MCP_ENABLED`
  set to false leaves the tab working and the tokens issuable, with nothing at
  the other end to connect to.
