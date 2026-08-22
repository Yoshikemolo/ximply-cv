# SEC-0008: Webhook signing

- **Status**: Accepted
- **Related**: [SEC-0002](SEC-0002-authentication-and-authorization.md),
  [SEC-0006](SEC-0006-default-credentials-and-secrets.md),
  [ADR-0015](../adr/ADR-0015-signed-webhook-delivery.md),
  [FEAT-0013](../features/FEAT-0013-events-and-webhooks.md),
  [API Reference, Webhooks](../infrastructure/api.md#webhooks)

## The position

Every webhook delivery is signed with HMAC-SHA256 over the timestamp, a full
stop, and the exact bytes of the request body, using a secret unique to the
subscription. The signature travels in `X-Ximply-Signature`, prefixed with the
algorithm that produced it, and the timestamp it was signed at travels in
`X-Ximply-Timestamp`.

A receiver that checks the signature knows two things: the request came from an
instance holding that subscription's secret, and the body is byte for byte what
that instance sent.

## Why not a shared token in a header

The cheaper option is to put a token in a header and have the receiver compare
it. That proves one thing only: the sender knew the token. It says nothing about
the request the token arrived with.

The consequences are ordinary rather than exotic:

- Anything that saw one request holds a credential that works on every future
  request. A reverse proxy, an access log with header capture, an error tracker,
  a screenshot of a debugging session.
- The token is not bound to the body, so a party sitting between the two ends
  can change the body and forward it with the same header. A receiver that acts
  on `person.recognised` can be made to act on a different person.
- There is nothing to replay against. The same request can be sent back
  unchanged as many times as the attacker likes and remains valid forever.

HMAC removes the first two. The secret is never transmitted, so capturing a
request does not yield it, and the signature covers the body, so a modified body
fails. The third is dealt with by the timestamp below.

## Why not SHA-1

SHA-1 is still the default in some webhook implementations, which is the only
argument for it. Chosen prefix collisions against it have been practical since
the SHAttered work in 2017, and the cost has fallen every year since. It is
unsuitable for anything where an attacker has influence over the input, which is
exactly the situation a signature is for.

The stronger digest costs nothing here. A delivery is a few kilobytes of JSON
sent at most a few times a minute, and the difference between the two hashes at
that size is not measurable against the network round trip. Choosing the weaker
one would buy nothing and would have to be undone later.

## Why the timestamp is inside the signed material

The timestamp is part of what is hashed, not merely sent next to it:

```
material = timestamp + "." + body
```

Signing the body alone produces a signature that is valid forever. Anyone who
captured one delivery can send it again next week and the receiver has no way to
tell. Binding the time into the digest means the receiver can compare the
timestamp header against its own clock and reject anything stale, and cannot be
fooled by editing the header, because editing it breaks the signature.

The tolerance used by the reference verifier is 300 seconds, which allows for
clock skew between the two machines and for a delivery that was retried. A
receiver is free to narrow it.

## Constant time comparison

The signature check uses `hmac.compare_digest` rather than `==`. A comparison
that returns as soon as two bytes differ leaks how many leading bytes were
correct through how long it took, which turns forging a signature from
infeasible into a few thousand requests per byte. Constant time comparison takes
the same time whatever the input, so there is nothing to measure.

## The secrets themselves

- 32 random bytes from the operating system's cryptographic source, hex encoded
  to 64 printable characters, so a secret can be pasted into a receiver's
  configuration without encoding questions.
- Generated per subscription. One compromised receiver does not let anything
  forge deliveries to another.
- Returned exactly once, in the response that creates the subscription or the
  response that rotates it. Every other response omits it. A value that can be
  read back at any time is a value that leaks through every screen that displays
  it and every log that records the response.

## Verifying a delivery

This is the check a receiver should perform, and it matches the signing code in
`backend/app/services/webhook_service.py` exactly:

```python
import hashlib
import hmac
import time


def verify(secret: str, timestamp: str, body: bytes, signature: str,
           tolerance: int = 300) -> bool:
    """Check a XIMPLY Vision webhook delivery."""
    try:
        age = abs(time.time() - float(timestamp))
    except (TypeError, ValueError):
        return False

    if age > tolerance:
        return False

    material = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), material,
                      hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)
```

Two details decide whether this works:

- `body` must be the raw bytes as received. Parsing the JSON and re-serialising
  it produces a different byte string and the check fails. In most frameworks
  this means reading the raw body before any JSON middleware touches it.
- `timestamp` is the value of `X-Ximply-Timestamp`, Unix seconds as a string,
  and is used as a string in the material. Converting it to a number and back
  can change it.

## Known gaps

- **The secret is stored so it can be used.** Signing every delivery requires
  the original value, so it is kept in the `webhook_subscriptions` table in a
  readable form. It cannot be hashed the way a password is. Anyone with read
  access to the database can therefore forge deliveries to that subscription.
  Protecting it is protecting the database, which is the subject of
  [SEC-0006](SEC-0006-default-credentials-and-secrets.md) and
  [SEC-0007](SEC-0007-container-hardening.md).
- **There is no idempotency key beyond the delivery id.** Deliveries are retried
  on failure and a timed out attempt may still have been processed, so a
  receiver can see the same event twice. `X-Ximply-Delivery` carries the event
  id and is the only thing to deduplicate on. There is no separate per attempt
  identifier, so a receiver cannot distinguish a retry of one delivery from a
  genuine resend.
- **Rotation invalidates deliveries in flight.** The new secret takes effect
  immediately and there is no overlap window where both the old and the new
  secret verify. A delivery already being retried when the secret is rotated
  will be signed with the new one, and any receiver not yet updated rejects it.
  Update the receiver first, then rotate.
- **The subscription URL is not constrained.** Only its length is validated. It
  may be plain `http`, in which case the payload, including any subject name in
  it, crosses the network in the clear and the signature protects integrity but
  not confidentiality. It may also point at an address inside the deployment's
  own network, which makes an account holding `events:manage` able to direct
  requests from the backend at internal hosts. Treat `events:manage` as an
  administrative permission and prefer `https` endpoints.
