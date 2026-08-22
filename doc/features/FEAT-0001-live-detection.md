# FEAT-0001: Live detection

- **Related**: [FEAT-0002](FEAT-0002-object-catalog.md),
  [FEAT-0009](FEAT-0009-catalog-management.md),
  [ADR-0005](../adr/ADR-0005-two-confidences.md),
  [ADR-0006](../adr/ADR-0006-class-aware-suppression.md),
  [ADR-0007](../adr/ADR-0007-view-filters-applied-server-side.md),
  [API Reference, Detection](../infrastructure/api.md#detection)

## What it does

Streams a video source into the browser, sends frames to the backend, and draws
what comes back over the picture: boxes or silhouettes, labels, confidence and
the identities resolved from the catalog.

## How it is implemented

The camera is opened with `getUserMedia` against the device the user picked from
the enumerated video inputs. Two loops run independently:

- A **render loop** on `requestAnimationFrame`, which draws the current video
  frame and the last set of results onto a canvas. Drawing is decoupled from
  inference so the picture stays smooth while detection runs at its own pace.
- A **detection loop** on an interval, which grabs the current frame, encodes it
  and posts it to `POST /api/v1/detection/detect`. A guard prevents a second
  request while one is in flight, so a slow frame delays the next request rather
  than queueing behind it.

The response carries detections, barcodes and skeletons. Detections are merged
into aggregated cards rather than replacing the list outright, described in
[FEAT-0009](FEAT-0009-catalog-management.md#the-detections-list).

## Patterns and interfaces

- **Signals for all view state.** Every piece of state is an Angular signal and
  the derived values are `computed`, so the filtered list, the tab counts and
  the labels recompute themselves rather than being recalculated by hand.
- **Service facade.** `DetectionService` is the only thing that knows the API
  shape. The component holds no URLs.
- **Server side filtering.** The view toggles travel with the request rather
  than filtering the response, for the reasons in
  [ADR-0007](../adr/ADR-0007-view-filters-applied-server-side.md).

## Behaviour worth knowing

- Overlapping detections of different things are all drawn. Suppression applies
  only between boxes describing the same thing
  ([ADR-0006](../adr/ADR-0006-class-aware-suppression.md)).
- A detection below the certainty threshold, or with no catalog identity, is
  labelled as a guess rather than stated as fact
  ([ADR-0005](../adr/ADR-0005-two-confidences.md)).
