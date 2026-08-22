# ADR-0006: Suppress only boxes that describe the same thing

- **Status**: Accepted
- **Related**: [ADR-0004](ADR-0004-segmentation-never-replaces-detection.md),
  [ADR-0007](ADR-0007-view-filters-applied-server-side.md),
  [View feature](../features/FEAT-0001-live-detection.md)

## Context

Non maximum suppression removed overlapping boxes by geometry alone, including a
containment check that dropped any box mostly inside another.

A person holding a bottle contains the bottle box inside the person box. The
suppression removed the bottle, which is the object the user was holding up to
the camera. The overlap was the scene, not a duplicate.

## Decision

Suppression applies only between detections that describe the same thing:

- Both resolved to the same catalog entry or the same person.
- Both carry the same detector class.

Anything else survives however much it overlaps. A person box never suppresses
an object box, and the reverse is also true.

## Consequences

- Overlapping detections of different things are all drawn, which is the
  behaviour the interface needed.
- Genuine duplicates of the same class are still collapsed, with a recognised
  entry preferred over a bare detector box.
- The rule depends on the class label surviving to that point, which is why the
  detector class is kept alongside any catalog name that replaced it.
