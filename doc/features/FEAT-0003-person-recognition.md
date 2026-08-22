# FEAT-0003: Recognising people

- **Related**: [FEAT-0009](FEAT-0009-catalog-management.md),
  [FEAT-0013](FEAT-0013-events-and-webhooks.md),
  [ADR-0002](../adr/ADR-0002-people-as-catalog-entries.md),
  [ADR-0003](../adr/ADR-0003-dual-embedding-person-reidentification.md),
  [ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md)

## What it does

Gives every person a durable identity. A face seen for the first time is
enrolled and named in sequence; from the next appearance it is recognised, and
renaming it makes the new name follow that person everywhere.

## How it is implemented

Two embeddings are produced per sighting, for the reasons in
[ADR-0003](../adr/ADR-0003-dual-embedding-person-reidentification.md):

- **Face**, from InsightFace ArcFace over the largest face in the person crop.
- **Body**, from a torchvision backbone over the whole crop.

Both are unit normalised, so a dot product is the cosine similarity. A gallery
of known people is held in memory, loaded from the database on first use.
Matching takes the best similarity per kind against every stored sample, and
accepts when either clears its threshold, combining them when both do.

A confirmed sighting is stored, which is what lets the fingerprint follow
someone as they put on a cap or take off a mask. Samples are capped per person
per kind, oldest dropped first.

Enrolment and the portrait are described in
[ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md).

## Patterns and interfaces

- **Embedder objects behind a uniform interface.** `FaceEmbedder` and
  `BodyEmbedder` both expose `embed(crop)` returning a vector and a quality
  score, and both fail soft: an unavailable model disables its half rather than
  taking detection down.
- **Separation of recognition from persistence.** The recognition service knows
  vectors and thresholds and nothing about the database. A separate catalog
  module reads and writes rows and keeps the gallery in step.
- **Pluggable body model.** The body embedder accepts an ONNX re-identification
  model through configuration and falls back to the bundled backbone.

## Behaviour worth knowing

- A person identity can only ever attach to a detection the detector called a
  person.
- Deleting a person clears them from the gallery immediately, so they stop being
  recognised without a restart.
- What is stored, and what that obliges the operator to do, is in
  [SEC-0004](../sec/SEC-0004-biometric-data.md) and
  [SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md).
- Enrolment and recognition are what raise `person.enrolled` and
  `person.recognised`, and a person leaving view raises `person.departed` once
  the absence grace period has passed. The event carries the name, the
  confidence and the frame it came from, and can be delivered to a webhook; see
  [FEAT-0013](FEAT-0013-events-and-webhooks.md).
