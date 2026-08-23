# SEC-0011: Broker and live frame exposure

- **Related**: [ADR-0022](../adr/ADR-0022-carry-the-live-stream-on-a-broker-and-a-socket.md),
  [ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md),
  [ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md),
  [SEC-0003](SEC-0003-object-storage-exposure.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [SEC-0005](SEC-0005-consent-and-lawful-basis.md),
  [SEC-0009](SEC-0009-integration-tokens.md),
  [SEC-0010](SEC-0010-remote-camera-activation.md)

## The position

Streaming adds two exposures that did not exist before, and they are not the
same size.

The first is a second front door. Until now every way into this application went
through its own HTTP layer, where a token is resolved, a scope is checked and an
owner is attached to the query. A broker is a separate process with its own
accounts, its own access rules and its own log, and this application is one
publisher on it. Whatever the broker lets a subscriber do is what that
subscriber can do, and none of the checks written elsewhere in this repository
apply once a message has been handed over.

The second is that images of a room now move continuously rather than one at a
time. [SEC-0010](SEC-0010-remote-camera-activation.md) drew the line between a
record of what a camera saw and the camera looking at all. A live stream is on
the far side of that line: it is watching, by somebody who is not in the room,
for as long as they care to.

Neither is on by default.

## What protects it

**Watching is granted by name.** `camera:view` must be listed on the token. The
empty scope list that means "whatever the owner holds" for reading does not
carry it, so no credential issued before this existed can watch a camera
([ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)).
It is separate from `camera:control`: a dashboard that shows the room cannot
switch the camera on, and a scheduler that switches it on cannot watch.

**A token cannot exceed its issuer.** Unchanged from
[SEC-0009](SEC-0009-integration-tokens.md), and it applies to both new scopes. A
user who does not hold `camera:view` cannot mint a token that has it.

**Two flags, and neither defaults to reachable.** `MQTT_ENABLED` false never
starts the publisher and never connects to a broker. `CAMERA_VIEW_ENABLED` false
refuses every frame path regardless of any token. A deployment that wants events
on a broker and no images gets that combination by leaving the second off.

**The frames are not kept.** One frame per camera is held in memory and
overwritten by the next. Nothing is written to object storage, to the database
or to a log, and no topic carrying an image is retained, so a subscriber that
connects later receives nothing about the past
([ADR-0023](../adr/ADR-0023-a-live-frame-is-never-stored-and-never-implied.md)).

**Nothing is published to nobody.** With no subscribers, a camera is not encoded
and not published. A deployment cannot quietly broadcast a room for months
because the feature was switched on once.

**The count is on the screen.** The camera state reports how many subscribers
are watching, next to whether it is running, so somebody looking at the
interface can see that somebody else is looking through it.

**The credential travels in a header.** The HTTP stream reads `Authorization`
and nothing else. It deliberately does not accept a token in the query string,
which would put a live credential into browser history, proxy logs and referrer
headers in exchange for making an `img` tag work.

**The browser is still the only camera.** No frame exists unless an interface
somewhere is capturing and sending one
([ADR-0021](../adr/ADR-0021-an-agent-may-switch-the-camera-but-never-opens-it.md)).
A subscriber cannot cause capture to begin; it can only receive what is already
being captured.

## Known gaps

**The broker does not separate owners.** The owner id is in the topic so an ACL
can be written per account, and the shipped broker configuration does not write
one. A credential that can subscribe to every topic receives every account's
events, captures and frames on that instance. Deployments with more than one
user must configure per-user broker accounts and topic ACLs, or run a broker per
user, or not run one.

**Broker traffic is not encrypted or signed by default.** The compose service
listens without TLS, which is tolerable only because the port is bound to the
loopback address. Webhook deliveries carry an HMAC a receiver can verify
([SEC-0008](SEC-0008-webhook-signing.md)); broker messages carry nothing
equivalent. A subscriber trusts the broker, and anything with write access to
the broker can publish a message that looks exactly like an observation this
instance made.

**The shipped broker accepts anonymous connections.** It is bound to the
loopback address, and that binding is the only thing standing between it and
anyone on the network. The configuration carries a commented password file and
ACL file for that reason, and both have to be filled in before the port is
opened. Credentials, once set, sit in the environment with the same handling
and the same weaknesses as everything in
[SEC-0006](SEC-0006-default-credentials-and-secrets.md): no rotation, and no
per-message authentication to fall back on.

**Images pass through a process this application does not control.** The
shipped configuration turns persistence off, so the broker holds messages in
memory and writes none of them to disk, and that is a setting rather than a
guarantee. A broker configured elsewhere, or replaced with a managed one, may
log messages or persist a queue. The rule that no frame is written down is a
rule about this application, not about the broker it publishes to.

**A viewer is counted, not identified.** The camera state says how many
subscribers are watching. It does not say which token, and the broker side
cannot be counted at all, because a broker does not tell a publisher who is
subscribed. A frame stream running over the broker is therefore invisible to the
count, which is the weakest point in the notice this design offers.

**There is still no notice in the room.** Unchanged from
[SEC-0010](SEC-0010-remote-camera-activation.md), and more consequential now. A
number on a screen nobody is looking at is not a notice to the person being
watched.

**The stream is not rate limited per token.** Any credential that can watch can
open as many connections as it likes, bounded only by the process. A malicious
or looping client is a resource problem this application does not currently
solve.

## Before enabling this

1. Leave `MQTT_ENABLED` and `CAMERA_VIEW_ENABLED` off unless something needs
   them. The order to enable them in is events first, images only when events
   turn out not to be enough.
2. Bind the broker port to the loopback address, or put TLS and per-user
   accounts in front of it before it leaves the machine. The shipped
   configuration assumes a single account on a single host.
3. Write topic ACLs before a second user exists on the instance. The topic tree
   is shaped for it; nothing enforces it.
4. Issue `camera:view` on its own token, separate from the one doing routine
   reading and separate from any token holding `camera:control`.
5. Treat a live stream as part of the lawful basis and the notice, not as a
   technical detail ([SEC-0005](SEC-0005-consent-and-lawful-basis.md)). Somebody
   watching a room remotely is what a data subject would want to be told about.
6. Provide a physical indicator if anyone other than the operator can be in
   view. This is the second record to ask for one
   ([SEC-0010](SEC-0010-remote-camera-activation.md)), and the reason is
   stronger here.
