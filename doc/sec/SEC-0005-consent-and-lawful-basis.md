# SEC-0005: Consent and lawful basis

- **Status**: Operator responsibility
- **Related**: [ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md),
  [SEC-0004](SEC-0004-biometric-data.md),
  [Readme](../../README.md)

## The situation this creates

The application enrols a person the first time it sees them. No operator action
is required, no prompt is shown, and the person in front of the camera is not
asked. From their second appearance they are recognised and named.

This is a deliberate design decision, recorded in
[ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md), because
recognition is useless until someone is known. It also means the system creates
biometric records about people who have not been asked.

## What the software provides

- **Automatic enrolment can be switched off.** With it off, no person record is
  created without an explicit action, and unrecognised people are reported as
  ordinary detections.
- **Thresholds are configurable**, so a deployment can require a strong sighting
  before a record is created.
- **Deletion is available** through the catalog, individually or in bulk, and
  takes effect on recognition immediately.

## What the software cannot provide

It cannot establish a lawful basis for processing, obtain consent, display a
notice, honour a subject access request or prove deletion to a regulator. Those
are the operator's obligations and they do not transfer with the source code.

Before pointing this at a space where members of the public appear, confirm at
minimum:

- A lawful basis for processing biometric data in the relevant jurisdiction.
- Notice to the people who will be recorded.
- A retention period, and a mechanism to enforce it, since the software has none
  ([SEC-0004](SEC-0004-biometric-data.md)).
- A route for someone to ask what is held about them and have it removed.

The permissive licence grants the right to use the software. It says nothing
about the right to record anybody.
