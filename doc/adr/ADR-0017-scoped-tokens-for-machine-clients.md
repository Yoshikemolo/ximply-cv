# ADR-0017: Authenticate machine clients with scoped tokens

- **Status**: Accepted
- **Related**: [ADR-0016](ADR-0016-read-only-protocol-server.md),
  [SEC-0002](../sec/SEC-0002-authentication-and-authorization.md),
  [SEC-0009](../sec/SEC-0009-integration-tokens.md),
  [FEAT-0014](../features/FEAT-0014-integrations.md),
  [API Reference, Integration tokens](../infrastructure/api.md#integration-tokens)

## Context

Everything else in this application is called by a person with a browser open,
and the credential fits that: a JSON Web Token, thirty minutes long, refreshed
by a client that is sitting there to refresh it, carrying the whole permission
list of whoever signed in
([SEC-0002](../sec/SEC-0002-authentication-and-authorization.md)).

The protocol server in [ADR-0016](ADR-0016-read-only-protocol-server.md) is
called by something else. An agent is configured once, in a file, and runs for
months without anybody watching it. Handing it a user's access token fails in
three ways at once. It stops working in half an hour and there is nobody to
refresh it. It carries every permission the user holds, so an agent that only
ever reads events is given the ability to delete the catalog if it is ever
persuaded to try. And it cannot be taken away: a JWT is valid until it expires,
so the only way to cut off one misbehaving client is to change the signing key
and log everybody out.

The other easy answer, a single shared secret in the configuration, is worse
still. It cannot be revoked for one client without revoking it for all of them,
and there is no record of which client used it.

## Decision

A machine client is issued its own integration token, bearing only the
permissions it was granted.

### One credential per client, not per person

A token is created with a name, so it can be recognised in a list a year later,
and it belongs to the user who issued it. Every read a tool performs is
filtered by that owner, so a token reaches exactly the events and catalog
entries its issuer could have read and nothing else.

Being separate from the session is what makes it manageable. It can be switched
off with `is_active` or deleted outright, and both take effect on the very next
call, because the token is resolved against the database on every request
rather than being trusted on the strength of a signature. That is the property
a JWT cannot have and the reason not to reuse one here.

It also has no fixed short life. An optional expiry can be set at issue, from a
day to ten years, and a token without one lasts until somebody removes it,
which is what a service credential has to do to be useful.

### Only what the client needs

A token carries a subset of `events:read`, `objects:read` and `events:manage`.
Every tool calls `_require()` with the permission it needs and refuses when the
token's scopes do not cover it, so an agent that was given `events:read` alone
is refused by `list_known_subjects` and never sees the catalog. Scopes are also
checked when the token is issued, against the permissions the issuing user
actually holds, so a token cannot be minted with more authority than the person
minting it.

The narrowing matters because a token lives in a configuration file on somebody
else's machine, which is a far worse place for a credential than a browser's
memory. What leaks with it should be the least that makes the client work.

### Shown once, stored as a hash

The value is returned in the response that creates it and never again. What is
stored is a SHA-256 digest of it plus a ten character prefix for display. Why a
plain digest is right for a token and wrong for a password, and what the prefix
buys, is the subject of
[SEC-0009](../sec/SEC-0009-integration-tokens.md).

Reveal once is not a convenience trade. A credential the interface can display
whenever it is asked is a credential that ends up in a screen recording, a
support screenshot and the response body of a routine list call. Showing it at
issue and never afterwards keeps the number of places it has ever existed to
the two that are unavoidable: the response, and wherever the operator pasted
it.

### Rejected before a tool is reached

`IntegrationTokenMiddleware` in `backend/app/main.py` resolves the header on
both mounts. A request without a usable token is answered `401` by the
middleware, so an unauthenticated call never reaches a tool and there is no
code path where a tool has to remember to check.

## Consequences

- A token is not a session and does not appear in any of the user facing
  account screens. It is managed from the Integrations page
  ([FEAT-0014](../features/FEAT-0014-integrations.md)) by a holder of
  `events:manage`, which is the administrative permission for this whole layer.
- Scopes are fixed at issue and are not re-checked against the owner
  afterwards. A user who later loses `objects:read` leaves behind a token that
  still carries it. Removing authority from a person means reviewing the tokens
  they issued.
- An empty scope list is not a narrower token, it is a wider one: `_require()`
  succeeds for every permission asked of it. The interface selects
  `events:read` by default so the wide case takes deliberate deselection, but
  it can be reached, and a token in that state is bounded only by what tools
  exist.
- `last_used_at` is written whenever a token is resolved, which makes a token
  nobody remembers issuing identifiable by never having been used, or by having
  been used at three in the morning. It costs a write on every protocol
  request.
- Losing a token value means issuing a new one. There is no recovery path, by
  design, and a client whose token was lost has to be reconfigured rather than
  reminded.
- The token authenticates the protocol mounts only. The REST API still expects
  a JWT, so a client that needs both an agent connection and an ordinary API
  call needs two credentials.
