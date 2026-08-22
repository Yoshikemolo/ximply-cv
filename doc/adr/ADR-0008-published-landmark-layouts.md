# ADR-0008: Use published landmark layouts and send the edges with the points

- **Status**: Accepted
- **Related**: [ADR-0007](ADR-0007-view-filters-applied-server-side.md),
  [View feature](../features/FEAT-0001-live-detection.md)

## Context

Drawing a skeleton needs two things: the joint positions and the list of which
joints connect. It is easy to hardcode the connection list in the drawing code,
and easy for it to drift out of step with the model that produces the points.

The layouts themselves are also a choice. An earlier implementation used the
seventeen point COCO layout, which stops at the wrists and the ankles.

## Decision

Bodies use the thirty three point layout, hands twenty one per hand, and faces
four hundred and seventy eight, all from the MediaPipe Tasks vision API. The
edge lists come from that library's own connection constants rather than being
written out by hand.

Each skeleton travels to the client with its edges attached, so the drawing code
never needs to know which layout it is looking at. Because the edges never
change within a kind, they are sent on the first skeleton of each kind per frame
and the client reuses them.

## Consequences

- The extra body points are the ones that matter for a readable figure: each
  foot gains a heel and a toe, and each wrist gains thumb, index and pinky
  anchors, so an arm continues into the hand instead of stopping dead.
- A change in the models cannot leave the drawing out of step with the points.
- The face mesh runs to a few thousand edges. Sending them once per kind per
  frame keeps the payload reasonable; sending them per skeleton would not.
- Body detection at distance is weaker than the previous layout. This is
  accepted for a webcam application, where the subject is close.
