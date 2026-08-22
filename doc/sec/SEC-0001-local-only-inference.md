# SEC-0001: All inference is local

- **Status**: Enforced
- **Related**: [ADR-0001](../adr/ADR-0001-run-every-model-locally.md),
  [ADR-0010](../adr/ADR-0010-local-vision-language-model.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [Readme](../../README.md)

## Position

No camera frame, crop, embedding or description leaves the host. Every model
runs in the backend container. There is no hosted inference API, no API key and
no telemetry.

## What this protects

The frames handled here contain identifiable faces, and the catalog accumulates
those identities deliberately. Sending them to a third party would move the
most sensitive data in the system outside the operator's control and outside
whatever agreement covers the people in front of the camera.

## What it does not protect

Local is not the same as private. The data is still stored, and the risks move
to the host:

- Anyone with database access reads the embeddings. See
  [SEC-0004](SEC-0004-biometric-data.md).
- Anyone who can reach the object store reads the portraits. See
  [SEC-0003](SEC-0003-object-storage-exposure.md).
- Anyone with an account reads whatever their role allows. See
  [SEC-0002](SEC-0002-authentication-and-authorization.md).

## Outbound connections that do exist

Model weights are downloaded from their publishers on first use and cached. The
hosts involved are the model publishers' distribution endpoints, reached once
per model. After the caches are warm the application runs with no outbound
network access, which is a supported way to deploy it and the simplest way to
verify this position.

The frontend loads no third party scripts, fonts or analytics.
