# SEC-0010: Remote camera activation

- **Related**: [ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  [ADR-0016](../adr/ADR-0016-read-only-protocol-server.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [SEC-0005](SEC-0005-consent-and-lawful-basis.md),
  [SEC-0009](SEC-0009-integration-tokens.md)

## The position

A camera can be asked to start by something that is not a person in the room.
That is a deliberate capability
([ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)),
and it is the most privacy-sensitive thing this application can be asked to do.

It is worth being plain about what it is. Everything else here concerns records
of what a camera already saw: who can read them, how long they are kept, how
they are protected. This concerns whether the camera is looking at all. A record
can be deleted. Seconds of a room being watched cannot be un-watched.

## What protects it

**The permission has to be written on the credential.** `camera:control` is
never implied. A token with no scopes carries whatever its owner carries for
reading; for control that inheritance does not apply, and the scope must appear
by name. This is not defence in depth, it is the primary control: it means every
credential in existence before this capability was built is unable to use it,
including ones whose holder has long since stopped thinking about them.

**A token cannot exceed its issuer.** Scopes are checked against the permissions
the issuing user holds, at issue and on every request
([SEC-0009](SEC-0009-integration-tokens.md)). A user without `camera:control`
cannot mint a token that has it.

**The deployment can remove it.** `CAMERA_CONTROL_ENABLED` set to false refuses
the tools regardless of any token.

**The protocol can be shut without a redeploy.** The footer switch closes both
transports at runtime behind `events:manage`. A capability that can only be
revoked by editing an environment variable and restarting is, in the minutes
that matter, not revocable.

**The browser is still in the way.** No request from here opens a device. It
records a wish that an open interface honours, and that interface can only open
a camera its own user has granted it. A machine with no page open, or a page
whose camera permission was refused, does not start recording no matter what
was asked.

**It is attributable.** `requested_by` records the token behind the current
state, so a camera found running can be traced to what asked for it.

## What does not protect it

**There is no notice in the room.** Nothing signals to a person present that a
camera has been started remotely. The interface shows its own state to whoever
is looking at the screen, which is not the same thing and may be nobody. A
deployment watching a space that other people enter needs a physical indicator,
and this application does not provide one.

**There is no confirmation step.** A request with a valid token is honoured. No
human approves it and nobody is asked at the moment it happens.

**A request outlives the moment it was made.** The state persists. A camera
asked to start while nothing was listening starts whenever an interface next
opens, which may be hours later and may surprise whoever opened the page. The
state is visible in `get_camera` and cleared by `stop_camera`, but nothing
expires it on its own.

**The audit is a column, not a log.** `requested_by` holds the most recent
request. The history of who switched a camera on and off over time is not
recorded as events, so a pattern of activation is not reconstructable after the
fact.

**An agent can be persuaded.** This is the argument
[ADR-0016](../adr/ADR-0016-read-only-protocol-server.md) makes about writable
tools, and it applies here with the catalog swapped for a room. An agent reading
event bodies, catalog names, or anything its user pasted into it can be talked
into calling a tool. The mitigation is that the tool it would be talked into
calling does something visible and reversible rather than something silent and
permanent, and that the permission to call it at all has to have been granted
deliberately. It is not that the agent cannot be fooled.

## Before granting this

1. Do not grant `camera:control` to a token that also does routine reading.
   Issue a separate one, so the credential that can start a camera is not the
   credential pasted into every integration.
2. Decide whether the space has people in it who have not agreed to be recorded,
   and treat remote activation as part of the lawful basis and the notice, not
   as a technical detail ([SEC-0005](SEC-0005-consent-and-lawful-basis.md)).
3. Provide a physical indicator if anyone other than the operator can be in
   view. Most cameras have one; this application cannot rely on it.
4. Leave `CAMERA_CONTROL_ENABLED` false in any deployment that has no use for
   it. An unused capability that is switched on is an unused capability that can
   be misused.
