# SEC-0003: Stored images are served without authentication

- **Status**: Accepted risk, mitigation required before public exposure
- **Related**: [SEC-0002](SEC-0002-authentication-and-authorization.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [API Reference, Objects](../infrastructure/api.md#objects),
  [Architecture, MinIO Object Storage](../infrastructure/architecture.md#minio-object-storage)

## The decision

Training images and person portraits are served through a backend proxy at
`/api/v1/objects/files/{path}`. That endpoint declares no authentication
dependency: any client that knows the path receives the image.

It exists because presigned object store URLs were producing signature
mismatches between the browser and the container network. Proxying the bytes
through the backend removed a class of deployment problem.

## Why it was accepted

Paths contain two identifiers generated as UUID version 7. Guessing one is not
practical.

## Why that is not enough

This is security through obscurity. It fails in the ordinary ways:

- A path appears in browser history, in proxy and server logs, and in the
  referrer of anything the page links to.
- Anyone who is shown one image URL keeps access to it after their account is
  removed, since nothing about the request is checked.
- UUID version 7 embeds a timestamp, so paths are ordered rather than uniformly
  random. This does not make guessing practical, but it does mean the values
  carry information.

The material at stake is photographs of identifiable people, which
[SEC-0004](SEC-0004-biometric-data.md) treats as sensitive.

## Required before exposing the stack beyond localhost

Either restore the authentication dependency on the proxy route and have the
frontend fetch images with its token, or issue short lived signed URLs scoped to
one object and one recipient. The first is the smaller change.
