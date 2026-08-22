# ADR-0014: An event marks a transition, never a frame

- **Status**: Accepted
- **Related**: [ADR-0013](ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0015](ADR-0015-signed-webhook-delivery.md),
  [FEAT-0001](../features/FEAT-0001-live-detection.md),
  [FEAT-0013](../features/FEAT-0013-events-and-webhooks.md),
  [API Reference, Events](../infrastructure/api.md#events)

## Context

Detection runs several times a second for as long as a view is open. Every one
of those frames produces a full set of results, and the obvious implementation
records each set as it arrives.

That implementation is useless. A single camera watching an empty corridor with
one chair in it would write tens of thousands of identical records an hour. A
person who walks in and stays for ten minutes would produce around three
thousand recognition events instead of one. Any subscriber would spend its whole
budget discarding duplicates, the retention window would be measured in days,
and the word "event" would stop meaning anything: a stream that fires constantly
carries no information about when something happened.

## Decision

An event is raised when the scene changes, not when a frame arrives. Each frame
is compared against the last one for the same owner and camera, and only the
difference is recorded.

The comparison works on identities rather than boxes. A detection is identified
by its catalog entry when it was recognised, and by its class otherwise, so an
unrecognised bottle is `class:bottle` and a second bottle in the same frame does
not become a second subject. Three things can then come out of one frame:

- **An arrival.** An identity present now and absent before raises
  `person.enrolled`, `person.recognised` or `object.recognised`. An unrecognised
  class raises nothing on its own; it is news only as part of the scene.
- **A departure.** An identity absent now and present before raises
  `person.departed`, but only for a subject that was worth announcing when it
  arrived.
- **A scene change.** The sorted set of names present, compared as a signature
  against the previous one, raises `scene.changed` when it differs.

### The absence grace period

A departure is not raised the moment an identity stops being detected. It is
raised once the identity has been missing for longer than
`events_absence_seconds`, which defaults to four seconds.

Detectors drop things. A person turning their head, a hand passing in front of a
face, a frame that arrived slightly dark: any of these can lose a subject for a
frame or two. Without the grace period each of those would read as a departure
immediately followed by an arrival, and a subscriber that unlocks a door or
sends a notification would act on both.

### The floor between scene changes

The scene signature changes whenever the detector changes its mind about
anything, and a detector flickering between two readings of the same object
changes its mind often. `events_scene_min_interval`, five seconds by default,
is a hard floor between two `scene.changed` events regardless of what the scene
does in between. A change that arrives inside the floor is not queued; the next
frame after the floor expires reports whatever is true then.

### The state is not persisted

Everything above lives in memory, keyed by owner and camera, and is lost when
the process stops. This is deliberate rather than an omission.

After a restart the first frame finds no previous state, so everything in view
counts as an arrival and is announced again. That is what a subscriber wants: it
has no way of knowing what happened while the service was down, so a fresh
statement of what is in view is more useful than silence. Persisting the state
would produce the opposite behaviour, where a subscriber that missed an outage
is never told the room is still occupied.

The same reasoning gives the service a `reset` for one owner and camera, so a
stream that stops and starts again re-announces the room rather than treating it
as unchanged.

## Consequences

- Events are rare enough to be read by a human. A quiet camera produces none.
- The measured behaviour is the point of the decision: sending the same frame
  three times in a row produced three events from the first frame and none at
  all from the other two.
- A subscriber cannot use events to count frames or measure how long something
  was present. It gets an arrival and, later, a departure, and works out the
  duration itself.
- A restart produces a burst of arrivals for a busy scene. A subscriber has to
  tolerate being told about something it already knew, which it has to do anyway
  because delivery is retried ([ADR-0015](ADR-0015-signed-webhook-delivery.md)).
- The state is per process. More than one backend replica means more than one
  copy of the state, and the same arrival can be announced by each of them.
- The distinction between `person.enrolled` and `person.recognised` rests on the
  recogniser reporting a brand new person with certainty, since that person is
  whoever this sighting is. A change to how enrolment scores itself changes
  which of the two is raised.
