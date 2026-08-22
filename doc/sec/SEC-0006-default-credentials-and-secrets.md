# SEC-0006: Default credentials and secrets

- **Status**: Accepted for local use, must be changed before exposure
- **Related**: [SEC-0002](SEC-0002-authentication-and-authorization.md),
  [SEC-0007](SEC-0007-container-hardening.md),
  [Deployment, Pre-deployment Checklist](../operations/deployment.md#pre-deployment-checklist),
  [Readme, Install with Docker](../../README.md#install-with-docker)

## Why defaults exist at all

The stack starts with a single command and no configuration file. That is a
deliberate property: an install that requires filling in secrets before it will
run is an install most people abandon. The cost is that every unconfigured
deployment shares the same credentials.

## The defaults

- **Administrator account**, seeded on first start with a known address and
  password, both documented in the readme.
- **Object store credentials**, the vendor defaults.
- **Database credentials**, a conventional pair.
- **JWT signing key**, a placeholder string that says it is one.

## The behaviour to be aware of

The seeding routine runs on every start, and it resets the administrator
password to the default rather than leaving a changed one alone. A password
changed through the interface does not survive a restart. Until that is fixed,
treat the administrator account as having a fixed, published password and
protect it with a real account for day to day use.

## Required before exposing the stack

Copy the environment template and set, at minimum:

- A generated `JWT_SECRET_KEY`. With the placeholder in place, anyone can mint a
  token for any user with any permission, which defeats
  [SEC-0002](SEC-0002-authentication-and-authorization.md) entirely.
- Real database and object store credentials.
- A different administrator address, and a real password for it.

The production compose override deliberately has no fallback values for these,
so it refuses to start rather than starting insecurely.
