# SEC-0002: Authentication and authorization

- **Status**: Enforced, with the gaps noted below
- **Related**: [SEC-0006](SEC-0006-default-credentials-and-secrets.md),
  [API Reference, Authentication](../infrastructure/api.md#authentication),
  [Architecture, Authentication Flow](../infrastructure/architecture.md#authentication-flow)

## Authentication

Passwords are hashed with bcrypt. Plaintext passwords are never stored and never
logged.

Sessions use JSON Web Tokens signed with HS256: a short lived access token and a
longer lived refresh token, both with expiry claims. The access token carries
the subject, the email, the roles and the resolved permission list, so an
authorization decision needs no database round trip.

## Authorization

Access is role based. Roles hold permissions, users hold roles, and the
permission list is embedded in the token at issue time.

Routes declare what they need rather than checking by hand. A route that reads
the catalog declares the read permission, one that writes declares the write
permission, and the dependency rejects the request before the handler runs.
Applying it as a route dependency is what keeps it from being forgotten on a new
endpoint.

## Known gaps

These are accepted for the current stage and listed so they are not mistaken for
oversights.

- **No token revocation.** There is no deny list. A token stays valid until it
  expires, so a logout or a role change does not take effect until then. Short
  access token lifetimes limit the window; the refresh token lifetime is the
  real exposure and should be reduced for any deployment reachable beyond
  localhost.
- **Permissions are a snapshot.** Because they are embedded at issue time, a
  permission removed from a role applies only to tokens issued afterwards.
- **No rate limiting on the login endpoint.** Nothing slows an offline guessing
  attack against a reachable instance. Put a reverse proxy in front of it before
  exposing the stack.
- **One unauthenticated endpoint** serves stored images. See
  [SEC-0003](SEC-0003-object-storage-exposure.md).
