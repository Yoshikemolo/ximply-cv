# FEAT-0003: Recognising people

- **Related**: [FEAT-0009](FEAT-0009-catalog-management.md),
  [FEAT-0013](FEAT-0013-events-and-webhooks.md),
  [ADR-0002](../adr/ADR-0002-people-as-catalog-entries.md),
  [ADR-0003](../adr/ADR-0003-dual-embedding-person-reidentification.md),
  [ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md),
  [ADR-0019](../adr/ADR-0019-confirm-a-person-before-enrolling-them.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md)

## What it does

Gives every person a durable identity. A face seen a few times and matching
nobody is enrolled and named in sequence; from then on it is recognised, and
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
[ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md), and what
it takes to create a person in
[ADR-0019](../adr/ADR-0019-confirm-a-person-before-enrolling-them.md).

### Recognising is cheap, creating is not

`evaluate()` reports the best similarity found whether or not it was accepted,
which is the difference between a stranger and a known person seen badly.
Matching uses only the accepted part; enrolment uses both.

Identification runs for every person box in a frame before any enrolment is
considered, because one person can arrive as two boxes and whether a box belongs
to somebody already recognised is knowable only once the matching is done. Four
things then have to hold before a person is created:

- No box already identified in this frame overlaps this one.
- The best candidate is not within `PERSON_ENROL_MARGIN` of a threshold.
- The face cleared `PERSON_MIN_ENROL_FACE_QUALITY`, or, with no face, the body
  crop cleared `PERSON_MIN_ENROL_BODY_QUALITY`.
- The same unknown fingerprint has returned `PERSON_ENROL_CONFIRMATIONS` times
  within `PERSON_ENROL_WINDOW_SECONDS`.

None of these affects recognition. Somebody hard to see is matched as readily as
before; they simply do not become a second entry when the match fails.

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
- **Candidates held outside the catalog.** Unknown fingerprints waiting for
  confirmation live in an in-memory buffer inside the recognition service, not
  as rows. Nothing partial reaches the catalog, and a restart drops them.

## Behaviour worth knowing

- A person identity can only ever attach to a detection the detector called a
  person.
- A new person appears a few seconds after they walk in, not on the first frame.
  Until then they are an unidentified person box.
- Somebody who only crosses the edge of frame is never enrolled. A deployment
  that wants every passer-by recorded lowers `PERSON_ENROL_CONFIRMATIONS`;
  setting it to one restores enrolment on a single sighting.
- The candidate buffer belongs to one process, so a deployment running several
  workers accumulates confirmations per worker. The count is a floor rather than
  an exact number.
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
