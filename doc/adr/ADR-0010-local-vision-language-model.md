# ADR-0010: Describe scenes with a local vision language model

- **Status**: Accepted
- **Related**: [ADR-0001](ADR-0001-run-every-model-locally.md),
  [ADR-0012](ADR-0012-automatic-enrolment-of-unknown-people.md),
  [SEC-0001](../sec/SEC-0001-local-only-inference.md)

## Context

Detections say what is present. They cannot say what is happening, how a room is
lit, or whether a desk is tidy, and that is what a description is for.

A hosted model would describe far better. It would also mean sending a frame
containing identifiable faces to a third party on a timer, which
[ADR-0001](ADR-0001-run-every-model-locally.md) rules out.

## Decision

A small vision language model runs locally alongside the other models. The
detections already found in the frame are passed as context, so the description
uses the names in the catalog rather than describing a known person from scratch,
and does not invent objects that were not there. The prompt asks for the scene,
with the detections as a hint, rather than for the list rendered into sentences.

The description is regenerated when the scene changes, keyed on the set of names
present rather than on pixels, with a cooldown on top.

## Consequences

- No frame leaves the machine, and there is nothing to bill or rate limit.
- Descriptions are correct but terse, and the model does not always use the
  catalog names it is given. This is the cost of a model small enough to sit
  beside the others, and the model is a single configuration value if a larger
  one is wanted.
- Keying on names rather than pixels means moving about does not trigger a
  rewrite, while someone walking in does. A detector that flickers between two
  readings of the same object would trigger one on every change of mind, which
  is what the cooldown is for.
- The model loads lazily, so a deployment that never asks for a description does
  not pay its download or its memory.
