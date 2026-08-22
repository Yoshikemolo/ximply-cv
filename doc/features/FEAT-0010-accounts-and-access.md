# FEAT-0010: Accounts and access control

- **Related**: [SEC-0002](../sec/SEC-0002-authentication-and-authorization.md),
  [SEC-0006](../sec/SEC-0006-default-credentials-and-secrets.md),
  [API Reference, Authentication](../infrastructure/api.md#authentication),
  [Architecture, Authentication Flow](../infrastructure/architecture.md#authentication-flow)

## What it does

Registration and login, several users, roles that group permissions, and an
admin section for managing both.

## How it is implemented

Passwords are hashed with bcrypt. A login issues a short lived access token and
a longer lived refresh token, both JSON Web Tokens. The access token carries the
roles and the resolved permission list, so an authorization decision needs no
database round trip.

Permissions follow a `resource:action` shape and are seeded on first start
alongside the default roles and the administrator account.

## Patterns and interfaces

- **Authorization as a route dependency.** A route declares the permissions it
  requires and the dependency rejects the request before the handler runs.
  Declaring it rather than checking by hand is what keeps it from being
  forgotten on a new endpoint.
- **Route guards on the client** mirror the same permissions, so a section the
  user cannot use is not offered. The server check is the one that matters; the
  guard is a courtesy.
- **An HTTP interceptor** attaches the token and handles refresh, so no
  component deals with authentication.

## Known gaps

Token revocation, permission freshness and login rate limiting are covered in
[SEC-0002](../sec/SEC-0002-authentication-and-authorization.md). The default
credentials and what must be changed before exposure are in
[SEC-0006](../sec/SEC-0006-default-credentials-and-secrets.md).
