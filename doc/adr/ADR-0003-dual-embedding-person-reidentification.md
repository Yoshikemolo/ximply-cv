# ADR-0003: Identify people with two embeddings, not one

- **Status**: Accepted
- **Related**: [ADR-0002](ADR-0002-people-as-catalog-entries.md),
  [ADR-0012](ADR-0012-automatic-enrolment-of-unknown-people.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md)

## Context

Recognising a person across sessions is not one problem. A face model is the
only thing that survives a change of clothes, a different camera and a different
day, but it degrades behind a mask and has nothing to work with when the subject
faces away. A whole body appearance model is unaffected by a cap, sunglasses or
a mask and works from behind, but a change of clothes destroys it.

Choosing either one alone means accepting its blind spot as a permanent
limitation of the product.

## Decision

Two embeddings are stored per sighting:

- **Face**, from InsightFace ArcFace. Carries identity across sessions.
- **Body**, from a torchvision ResNet50 backbone over the whole person crop.
  Carries identity within a session, through occlusion of the face.

A sighting matches a known person when either clears its own threshold. When
both do, the similarities are combined with the face weighted more heavily,
since it is the one that generalises.

Several samples are kept per person per kind, capped, with the oldest dropped
first so the fingerprint follows how someone looks now.

## Consequences

- Recognition holds up through a cap, glasses or a mask, and across a change of
  clothes, which neither model manages alone.
- Two thresholds and a weight need tuning per deployment. The defaults are the
  usual ArcFace figures and are unlikely to be right for every camera.
- The body embedder is a general purpose backbone rather than a dedicated
  re-identification model. A model such as OSNet would be stronger, but its
  common packaging pulls a second OpenCV distribution that conflicts with the
  one this project uses. The loader accepts an ONNX re-identification model
  through configuration, so the substitution needs no code change.
- Storage per person grows with sightings. See
  [SEC-0004](../sec/SEC-0004-biometric-data.md) for retention.
