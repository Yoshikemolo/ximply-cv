# SEC-0009: Integration tokens

- **Status**: Accepted
- **Related**: [SEC-0002](SEC-0002-authentication-and-authorization.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [SEC-0006](SEC-0006-default-credentials-and-secrets.md),
  [SEC-0008](SEC-0008-webhook-signing.md),
  [ADR-0016](../adr/ADR-0016-read-only-protocol-server.md),
  [ADR-0017](../adr/ADR-0017-scoped-tokens-for-machine-clients.md),
  [FEAT-0014](../features/FEAT-0014-integrations.md),
  [API Reference, Integration tokens](../infrastructure/api.md#integration-tokens)

## The position

An external client that connects to the protocol server presents an integration
token as a bearer credential. The token is generated from the operating
system's cryptographic random source, is stored only as a SHA-256 digest, is
shown to a person exactly once, carries only the permissions it was granted,
and can be switched off or removed at any time with effect on the next call.

It is not a session and is not a password. It is a long lived credential handed
to a machine, and the handling below follows from that rather than from the
rules that apply to the other two.

## Generation

```
value = "xvt_" + secrets.token_urlsafe(32)
```

Thirty two bytes from `secrets`, which reads the operating system's
cryptographic source, encoded to forty three URL safe characters. That is 256
bits of entropy, which is the number the rest of this document depends on: it
is why the storage below is safe, and why nothing about the token has to resist
guessing.

`secrets` rather than `random` is the whole of the choice. The general purpose
generator is seeded predictably and its output can be reconstructed from a
short run of samples, which is fine for shuffling a list and disqualifying for
issuing a credential.

## The prefix

Every token starts with `xvt_`, and the ten characters kept in the clear for
display are that marker followed by the first six of the random part.

The marker is there for the moment something goes wrong. A credential that
looks like every other opaque string is one nobody notices in a commit, a
pasted log or a support ticket, and the first job during an incident is working
out what leaked. A recognisable marker makes a token findable: a secret scanner
can be given one pattern, a `grep` over a repository answers in a second, and
anyone reading a configuration file can see at a glance which line is the
credential.

The six characters after it exist so a person can tell two tokens apart in a
list without the value being readable. Six characters of the random part
narrows 256 bits to a shade over 220, which is not a number anybody searches.

## Why the digest is a plain SHA-256

The stored value is `sha256(token)`, with no salt and no work factor. That
looks wrong next to
[SEC-0006](SEC-0006-default-credentials-and-secrets.md), where a user password
is put through a slow password hash, and the difference between the two cases
is the reason.

A password is chosen by a person. Its real entropy is somewhere between twenty
and forty bits whatever its length, it is drawn from a distribution an attacker
holds a copy of, and it is probably reused somewhere else. A stolen password
database is therefore worth attacking offline, and the only defence is to make
each guess expensive. That is what argon2 and bcrypt sell, and the price is
paid once per login by a human who is not counting milliseconds.

A token is chosen by the operating system, from the whole 256 bit space, with
no distribution to exploit and no dictionary to try. There is no offline attack
to slow down: an attacker holding the digest has nothing better than enumerating
a space that will not be enumerated. Adding a work factor would buy none of the
resistance it was designed for and would charge for it on every single protocol
request, where an agent may make dozens in a conversation. A salt buys nothing
either, since it exists to stop one precomputed table covering many users and
there is no table that covers random 256 bit strings.

The digest also has to be looked up, not merely verified. A presented token is
hashed and matched against an indexed column, which a deliberately slow hash
would turn into a slow operation on the request path for no gain.

## Shown once

The value is returned in the response that issues the token and never appears
in any response afterwards. Listing tokens returns the name, the prefix, the
scopes, whether it is active and when it was last used. The value is not in the
database in a readable form, so there is nothing to return even by mistake.

This is the one property that separates a token here from a webhook secret,
which has to be kept readable so deliveries can be signed with it
([SEC-0008](SEC-0008-webhook-signing.md#known-gaps)). Nothing in this
application ever needs the token value again, so nothing keeps it, and read
access to the database does not yield a usable credential.

## Scopes

A token carries a subset of `events:read`, `objects:read`, `events:manage` and
`camera:control`, and every tool checks the one it needs before doing anything.
The scopes requested at issue are checked against the permissions the issuing
user holds, so a token cannot be created with more authority than its creator.

`camera:control` is not read at all. It lets an agent ask a camera to start,
which is why it is checked differently from the rest and is the subject of
[SEC-0010](SEC-0010-remote-camera-activation.md).

Grant the least that makes the client work. An agent that summarises arrivals
needs `events:read` and nothing else, and giving it `objects:read` as well
means a leaked token also lists every person the instance has ever recognised.
The narrowing is worth doing precisely because the token lives somewhere the
deployment does not control: a configuration file on the machine running the
agent, often synchronised, often backed up.

## Revocation, deactivation and use

- **Deactivating** a token sets `is_active` to false. It stays in the list and
  can be switched back on. Use this when a client is suspected rather than
  confirmed, or is simply being paused.
- **Revoking** deletes the record. The digest is gone, so the value can never
  resolve again.

Both take effect on the next request. The token is looked up in the database
every time it is presented, unlike a JWT, which is trusted on its signature
until it expires and cannot be withdrawn at all
([SEC-0002](SEC-0002-authentication-and-authorization.md#known-gaps)).

`last_used_at` is written on every successful resolution. It answers the two
questions that come up when reviewing a list of tokens: which of these is
nobody using, and is any of them being used when it should not be. A token
issued eight months ago and never used is one to remove. A token belonging to a
nightly job that was used at four in the afternoon is one to look into.

An expiry can be set at issue, from one day to ten years. A token past its
expiry stops resolving without anybody having to remember it.

## What a leaked token gets an attacker

Read access, bounded by the scopes on it and by the events and catalog entries
of the user who issued it. Concretely, with the usual scopes: every event this
instance has recorded, including the names of the people it recognised and when
each of them was seen, the current contents of the room, the full list of
people and objects it can recognise, and which models are loaded.

That is a record of who was in a physical space and when, tied to named
individuals. It is derived from biometric processing and carries the same
weight as the material behind it
([SEC-0004](SEC-0004-biometric-data.md)). A leaked token is a privacy incident
even though nothing was modified and no image was fetched.

What it does not get: no capture image, since no tool returns one; no change to
any record, since no tool performs one
([ADR-0016](../adr/ADR-0016-read-only-protocol-server.md)); and nothing
belonging to another user of the same instance.

A token carrying `camera:control` gets one thing more, and it is of a different
order: the ability to start a camera in a physical space. That is not read
access and it is not bounded by what was already recorded. It is the reason the
scope is granted by name rather than inherited, and the reason it belongs on a
token of its own ([SEC-0010](SEC-0010-remote-camera-activation.md)).

## Known gaps

- **An empty scope list is the widest token, not the narrowest.** When no
  scopes are selected, every permission check passes. The interface preselects
  `events:read` so reaching that state takes deliberate deselection, but a
  token created through the API with `"scopes": []` is bounded only by which
  tools exist. Always issue a token with its scopes named. The camera tools are
  the one exception: they refuse a token whose scope list does not name
  `camera:control`, precisely so that a capability added later cannot be
  acquired by a credential written before it existed.
- **`events:manage` is offered as a scope and no tool requires it.** Granting
  it to a token confers nothing over the protocol today. It will if a tool that
  needs it is ever added, so a token holding it now would gain authority from a
  future release without anybody revisiting it.
- **Scopes are not re-checked against the issuer.** They are validated when the
  token is created and read from the token record thereafter. A user who later
  loses a permission leaves behind tokens that still carry it, so removing
  authority from a person means reviewing what they issued.
- **The token travels in a header on every request.** Over plain `http` it
  crosses the network in the clear, and anything between the two ends holds a
  working credential. Serve the instance over `https` before an agent connects
  from another machine, which is the same requirement
  [SEC-0007](SEC-0007-container-hardening.md) already makes of the stack.
- **There is no rotation, only reissue.** Unlike a webhook secret, a token
  cannot be replaced in place. Replacing one means issuing a second, moving the
  client over and revoking the first, and there is no window during which both
  are known to belong to the same client.
- **Use is recorded as a timestamp and nothing else.** There is no per call
  log, no source address and no client identifier beyond the token itself, so a
  stolen token used alongside the legitimate client is indistinguishable from
  it. `last_used_at` finds a token nobody is using; it does not find a token
  two parties are.
