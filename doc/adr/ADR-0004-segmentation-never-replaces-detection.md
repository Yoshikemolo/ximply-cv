# ADR-0004: Segmentation never replaces detection

- **Status**: Accepted
- **Related**: [ADR-0005](ADR-0005-two-confidences.md),
  [ADR-0006](ADR-0006-class-aware-suppression.md),
  [View feature](../features/FEAT-0001-live-detection.md)

## Context

Segment Anything produces a far better shape than a bounding box. It is
tempting to offer it as an alternative to the detector, and the interface does
present a choice between the two.

Segment Anything cannot classify. It reports where an edge runs and has no idea
what it is looking at. A model selector that genuinely swapped one for the other
would silently disable the catalog, person identity and every label in the
interface.

## Decision

The detector always runs. When silhouettes are selected, Segment Anything is
prompted with the boxes the detector already produced, and its outline replaces
the rectangle in the drawing. Labels, catalog matches and person identities keep
coming from the detector in both modes.

The same principle applies in reverse: a person entry may only ever be attached
to a detection the detector called a person.

## Consequences

- Choosing silhouettes costs accuracy nowhere and adds roughly seventy
  milliseconds a frame.
- A box prompt is ambiguous, since the rectangle around a person also contains
  whatever is behind them. Two controls narrow it: a tightness slider that
  chooses among the granularity levels the model offers, and an option that
  feeds the centres of other detections back as negative points.
- The frame is encoded once and each box costs only a decoder pass. Prompting
  per box is necessary because the negative points differ per box.
- A detection the segmenter cannot trace keeps its rectangle, so nothing
  disappears from the overlay.
