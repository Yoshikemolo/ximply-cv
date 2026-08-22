# ADR-0012: Enrol an unknown person automatically

- **Status**: Accepted
- **Related**: [ADR-0002](ADR-0002-people-as-catalog-entries.md),
  [ADR-0003](ADR-0003-dual-embedding-person-reidentification.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md)

## Context

Recognition is only useful once someone is known. Requiring an explicit
enrolment step means a face has to be captured, named and saved before it can
ever be recognised, and until then every appearance is an anonymous box.

## Decision

A sighting that matches nobody and is good enough to be worth keeping creates a
catalog entry immediately. It is named in sequence, "Person 1", "Person 2", and
so on, continuing after the highest number already used so that renaming never
causes a later collision. The crop from that frame is stored as the portrait.

Every later sighting is scored, and the portrait is replaced whenever a clearer
one appears, so an entry settles on a picture with a visible face rather than
the blurred back view it started from.

Enrolment is refused for a sighting with no face embedding unless the body crop
was large enough to be reliable, because enrolling on a poor sighting creates
duplicate people who never match again.

## Consequences

- A face is recognisable from its second appearance, with no setup.
- The catalog fills with entries nobody created deliberately, which is a
  significant privacy consequence and the subject of
  [SEC-0004](../sec/SEC-0004-biometric-data.md) and
  [SEC-0005](../sec/SEC-0005-consent-and-lawful-basis.md).
- Automatic enrolment is a configuration switch, so a deployment that must not
  create records without an operator action can turn it off.
- Sequential names are placeholders. Renaming is available inline wherever a
  person appears.
