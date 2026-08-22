# Security Decisions

Each record states a position, what it protects, and what it does not. The gaps
are written down rather than left out: a security document that lists only the
controls is a document that will be trusted further than it deserves.

Architecture decisions are recorded separately, in [doc/adr](../adr/README.md).

| Record | Subject |
| --- | --- |
| [SEC-0001](SEC-0001-local-only-inference.md) | All inference is local |
| [SEC-0002](SEC-0002-authentication-and-authorization.md) | Authentication and authorization |
| [SEC-0003](SEC-0003-object-storage-exposure.md) | Stored images are served without authentication |
| [SEC-0004](SEC-0004-biometric-data.md) | Biometric data |
| [SEC-0005](SEC-0005-consent-and-lawful-basis.md) | Consent and lawful basis |
| [SEC-0006](SEC-0006-default-credentials-and-secrets.md) | Default credentials and secrets |
| [SEC-0007](SEC-0007-container-hardening.md) | Container hardening |

## Before exposing this beyond localhost

The short version of what the records above require:

1. Set a generated JWT signing key and real credentials
   ([SEC-0006](SEC-0006-default-credentials-and-secrets.md)).
2. Authenticate the image proxy, or replace it with scoped signed URLs
   ([SEC-0003](SEC-0003-object-storage-exposure.md)).
3. Put a reverse proxy in front and bind the published ports to the loopback
   address ([SEC-0007](SEC-0007-container-hardening.md)).
4. Decide a lawful basis, a notice and a retention period before any member of
   the public is recorded ([SEC-0005](SEC-0005-consent-and-lawful-basis.md)).

## Elsewhere

- [Readme](../../README.md)
- [Architecture decisions](../adr/README.md)
- [System architecture](../infrastructure/architecture.md)
- [API reference](../infrastructure/api.md)
- [Deployment guide](../operations/deployment.md)
