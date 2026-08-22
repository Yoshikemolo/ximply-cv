# ADR-0001: Run every model locally

- **Status**: Accepted
- **Related**: [ADR-0009](ADR-0009-discover-acceleration-at-runtime.md),
  [ADR-0010](ADR-0010-local-vision-language-model.md),
  [SEC-0001](../sec/SEC-0001-local-only-inference.md),
  [Architecture, Overview](../infrastructure/architecture.md#overview)

## Context

Every capability in this application could be bought as a hosted API: detection,
face recognition, segmentation and scene description all have mature cloud
offerings that are more accurate than anything that fits on one machine.

Those offerings require sending the camera frame to a third party. The frames
here contain the faces of identifiable people, and the whole point of the
catalog is that it accumulates those identities over time.

## Decision

Every model runs on the host. No inference request leaves the machine, no API
key is required, and no usage is billed per call.

The models are listed in the [readme](../../README.md#the-models-and-what-each-one-is-for).
Weights are downloaded once from their publishers and cached in named volumes,
after which the application runs with no network access at all
(see [ADR-0011](ADR-0011-cache-model-weights-in-volumes.md)).

## Consequences

- Descriptions are shorter and less nuanced than a large hosted model would
  produce. This is accepted; see [ADR-0010](ADR-0010-local-vision-language-model.md).
- The container image is large, several gigabytes before weights.
- First use of each model pays a download and a warm up.
- The privacy position is simple to state and simple to verify: there is no
  outbound call to audit. See [SEC-0001](../sec/SEC-0001-local-only-inference.md).
- An operator with no GPU still gets a working system, only slower
  ([ADR-0009](ADR-0009-discover-acceleration-at-runtime.md)).
