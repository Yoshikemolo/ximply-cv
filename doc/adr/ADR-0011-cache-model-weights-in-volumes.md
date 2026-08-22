# ADR-0011: Cache model weights in named volumes

- **Status**: Accepted
- **Related**: [ADR-0001](ADR-0001-run-every-model-locally.md),
  [ADR-0009](ADR-0009-discover-acceleration-at-runtime.md),
  [SEC-0007](../sec/SEC-0007-container-hardening.md),
  [Deployment, Development Deployment](../operations/deployment.md#development-deployment)

## Context

The models are large. The face recognition bundle alone is around two hundred
and seventy five megabytes, and the detection, segmentation, landmark and
description models add several gigabytes more.

Baking them into the image makes every rebuild carry them. Leaving them in the
container filesystem means every recreate downloads them again, which turns a
routine redeploy into a long wait and a dependency on the publisher being
reachable.

## Decision

Each cache is a named volume: model weights, the face model bundle, and the
language model cache.

Because a fresh named volume is seeded from the image, the directories must
exist in the image and belong to the runtime user. A volume seeded from a
directory owned by root leaves the container unable to write it, and the failure
surfaces as a model that silently refuses to load.

## Consequences

- A redeploy is fast and works without network access once the caches are warm.
- The image stays smaller than it would with the weights baked in.
- Deleting the volumes forces a re-download, which is the intended way to pick
  up new weights.
- Ownership of the cache directories is now part of the image contract, not an
  incidental detail.
