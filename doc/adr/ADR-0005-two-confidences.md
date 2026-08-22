# ADR-0005: Report detection confidence and match confidence separately

- **Status**: Accepted
- **Related**: [ADR-0004](ADR-0004-segmentation-never-replaces-detection.md),
  [API Reference, Objects](../infrastructure/api.md#objects),
  [View feature](../features/FEAT-0009-catalog-management.md#the-detections-list)

## Context

Two different questions are answered by two different models, and both were
being reported as one number.

The detector says how sure it is that something is present. The catalog matcher
says how sure it is that the something is a particular entry. A bus detected at
ninety two percent can be a terrible match for a phone in the catalog, and
showing ninety two percent beside the word "phone" states a wrong identity with
the detector's certainty behind it.

## Decision

A detection carries `confidence` and, when an identity was attached,
`matchConfidence`. The interface shows the identity confidence whenever there is
one, and falls back to the detector's otherwise.

Below a certainty threshold, or with no catalog identity at all, the label is
written as a guess rather than a statement: `Possible: name percent`.

## Consequences

- A weak match now reads as weak. The bus that matched a phone at four percent
  is labelled as a four percent guess instead of a ninety two percent fact.
- Two numbers travel per detection, which is a small addition to the payload.
- The distinction has to be preserved everywhere a percentage is shown,
  including the aggregated cards in the detections list.
