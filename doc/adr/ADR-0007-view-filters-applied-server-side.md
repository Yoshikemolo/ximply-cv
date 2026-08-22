# ADR-0007: Apply the view filters before deduplication, on the server

- **Status**: Accepted
- **Related**: [ADR-0006](ADR-0006-class-aware-suppression.md),
  [API Reference, Detection](../infrastructure/api.md#objects)

## Context

The interface offers toggles that hide people, restrict the list to catalog
entries, and switch the skeleton and face overlays off. Originally these
filtered the response after it arrived.

Filtering afterwards is not equivalent to filtering before. Suppression resolves
overlaps against every box, including ones the user asked not to see, so a
hidden box could suppress a visible one and leave a gap where a detection
should have been.

The overlays are worse: computing a landmark model and discarding its result is
the entire cost for none of the benefit.

## Decision

The toggle states travel with the detection request. The server applies them
before suppression, and skips any landmark model whose overlay is switched off.

## Consequences

- A hidden box can no longer suppress a visible one.
- Switching the overlays off is a real saving rather than a cosmetic one.
  Measured on one frame: forty eight milliseconds with both on, eight with both
  off.
- The request carries a little more state, and the server and the interface must
  agree on the defaults. Where a default exists in both, they are set to the
  same value deliberately.
