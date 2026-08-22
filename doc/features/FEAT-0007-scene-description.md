# FEAT-0007: Scene description

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [FEAT-0003](FEAT-0003-person-recognition.md),
  [ADR-0010](../adr/ADR-0010-local-vision-language-model.md),
  [SEC-0001](../sec/SEC-0001-local-only-inference.md),
  [API Reference, Detection](../infrastructure/api.md#detection)

## What it does

Writes a sentence or two about what the camera is looking at, below the video,
and rewrites it when the scene changes.

## How it is implemented

A small vision language model runs locally. The detections already on screen
travel with the request and are turned into a context line naming the people and
objects present, marking anything below the certainty threshold as uncertain.
The prompt asks for the scene, with that list as a hint, rather than for the
list rendered into sentences.

The frame is downscaled before it reaches the vision encoder, which is a large
part of the cost and loses nothing at this task.

Regeneration is keyed on a **scene signature**: the sorted set of names
currently present. Comparing names rather than pixels means moving about does
not trigger a rewrite while someone walking in does. A cooldown sits on top,
because a detector flickering between two readings of the same object would
otherwise trigger one on every change of mind.

## Patterns and interfaces

- **Lazy loading with a soft failure.** The model loads on first use, so a
  deployment that never asks for a description pays neither the download nor the
  memory. An unavailable model is reported in the panel with the reason, not by
  hiding the panel.
- **Status endpoint.** `GET /api/v1/detection/describe/status` reports whether
  the model is loaded, loading, or unavailable and why.

## Behaviour worth knowing

- The first description of a session pays the model load, several seconds. Later
  ones are around a second.
- The model is a single configuration value. A larger one produces richer
  descriptions at a proportional cost in memory and latency.
