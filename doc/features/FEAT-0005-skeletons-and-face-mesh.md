# FEAT-0005: Skeletons and face mesh

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [ADR-0007](../adr/ADR-0007-view-filters-applied-server-side.md),
  [ADR-0008](../adr/ADR-0008-published-landmark-layouts.md)

## What it does

Draws a wireframe over people and hands, and a mesh over faces: 33 body
landmarks, 21 per hand with handedness, and 478 face landmarks.

## How it is implemented

Three landmarkers from the MediaPipe Tasks vision API, each loading lazily and
failing soft. Task bundles are downloaded once into the model volume, written to
a temporary name first so an interrupted download cannot leave a truncated file
that every later start would accept.

Each skeleton is published with its keypoints and the edges connecting them.
Edges come from the library's own connection constants rather than being written
out by hand, so a change in the models cannot leave the drawing out of step with
the points ([ADR-0008](../adr/ADR-0008-published-landmark-layouts.md)).

Because edges never change within a kind, they are sent on the first skeleton of
each kind per frame and the client caches them by kind. The face mesh alone runs
to a few thousand edges, so sending them per skeleton would dominate the payload.

## Patterns and interfaces

- **One shape for three models.** Body, hand and face all produce the same
  `Skeleton` structure, so the drawing code branches on line weight and colour
  rather than on which model produced the points.
- **Edges carry a part label**, so the client colours a limb or a finger without
  knowing the layout.
- **Toggles stop the work.** Switching an overlay off skips the model rather
  than discarding its result
  ([ADR-0007](../adr/ADR-0007-view-filters-applied-server-side.md)).

## Drawing notes

- Bones are drawn before joints, so the dots sit on top of the lines.
- An edge whose endpoints are not both visible is skipped rather than drawn to
  the origin, which is where an unscored keypoint sits.
- The face mesh is drawn as a hairline and its individual vertices are not
  drawn: at 478 points they are noise rather than information.
