# FEAT-0004: Silhouettes

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [ADR-0004](../adr/ADR-0004-segmentation-never-replaces-detection.md),
  [ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md)

## What it does

Replaces the bounding box with the actual outline of the object, as a polygon
drawn over the frame with a light fill.

## How it is implemented

Segment Anything is prompted with the boxes the detector already produced. It
never runs alone, for the reason in
[ADR-0004](../adr/ADR-0004-segmentation-never-replaces-detection.md).

Per frame:

1. The frame is encoded once and the encoder output cached. Without this the
   image encoder runs per box, which is the whole cost of a frame paid per
   detection.
2. Each box is prompted separately, because the negative points differ per box.
3. Several candidate masks are requested per prompt and one is chosen, described
   below.
4. The chosen mask is mapped back to frame coordinates by the library's own
   post processing, which undoes the exact preprocessing that produced it. A
   plain resize does not, and shifts every outline.
5. The largest external contour is traced and simplified with Douglas-Peucker
   until it fits a point budget. Raw contours run past a thousand points, which
   is more than a canvas stroke can show and more than is worth sending.

## Calibration

A box prompt is ambiguous: the rectangle around a person also holds the chair
behind them. Two controls narrow it:

- **Tightness** chooses among the granularity levels the model offers. It ranks
  them by predicted overlap, which favours the widest reading, so the model's
  own preference is often the wrong one here.
- **Exclude other objects** feeds the centres of other detections back as
  negative points. The detector has already found the chair separately, so the
  application knows where it is and can say what the subject is not.

Candidates far below the best score are dropped as noise, and any covering more
of their box than a ceiling allows are treated as having escaped onto the
background.

## Behaviour worth knowing

- A detection the segmenter cannot trace keeps its rectangle.
- The outline must be traced from the mask, not from the library's ready made
  segment list: that list concatenates every disconnected region into one point
  array, which drawn as a single polygon sends lines across the interior.
