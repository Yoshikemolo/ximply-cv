# ADR-0020: An event carries the time it was observed, and a floor delays it rather than dropping it

- **Status**: Accepted. Amends
  [ADR-0014](ADR-0014-events-on-transition-not-per-frame.md), whose rule that an
  event marks a transition stands. What changes is the handling of a transition
  the floor arrived too early for, and where the timestamp readers sort by comes
  from.
- **Related**: [ADR-0013](ADR-0013-events-as-opentelemetry-records.md),
  [ADR-0015](ADR-0015-signed-webhook-delivery.md),
  [ADR-0016](ADR-0016-read-only-protocol-server.md),
  [FEAT-0013](../features/FEAT-0013-events-and-webhooks.md)

## Context

Two defects made the event stream misdescribe what the camera saw. Both were
found by reading the stream back and comparing it against a room that plainly
did not look like that.

**The stream said the room was empty while somebody sat in front of the
camera.** `scene.changed` is subject to `events_scene_min_interval`, a floor
between two scene events. When the floor blocked one, the event was skipped —
and the remembered signature was updated anyway, at the bottom of `observe()`,
outside the branch that emits. The scene was therefore marked as announced when
nothing had been announced. Since the scene then stayed as it was, no later
frame differed from the stored signature, and the transition was never emitted.
It was not delayed. It was lost, permanently, and the last thing a reader had
been told remained true forever.

The observed sequence: at 00:34:07.245 a frame with nobody in view emitted
`scene.changed` with an empty `present`. Two hundred and seventy milliseconds
later the person was back. The signature changed, the floor blocked it, the
signature advanced silently, and `get_current_scene` went on reporting an empty
room indefinitely.

**Events raised by one frame could not be ordered, and were stamped before they
happened.** `occurred_at` was left to `server_default=func.now()`. In PostgreSQL
`now()` is the start of the transaction, not the moment of the statement. Every
event written in one transaction therefore shared a timestamp to the
microsecond, and that timestamp preceded the work that produced them.

That column is not incidental. `list_events` and `get_current_scene` order by
it, `since_minutes` filters on it, and `get_current_scene` computes the age it
reports from it. Records sharing a value cannot be ordered against each other at
all, and the age of the scene was measured from when a transaction opened.

The nanosecond fields the specification requires
([ADR-0013](ADR-0013-events-as-opentelemetry-records.md)) were correct
throughout. Every reader sorts by the column, so being right in a field nobody
sorts by was no help.

## Decision

### The floor delays an announcement; it never cancels one

The remembered signature advances only when the event is actually raised. While
the floor holds, the stored signature stays at the last value that was
announced, so the difference is still there to be found, and the next frame past
the floor raises it with the scene as it is by then.

A subscriber gets one event slightly late rather than an incorrect picture that
never corrects itself. That is the whole purpose of a floor: to bound how often
a subscriber hears, not to decide which changes it is told about.

Where the two collide, correctness wins. A rate limit that silently drops a
state transition is not a rate limit.

### One instant, stamped on the record

`_record()` takes `time.time_ns()` once and derives everything from it: both
nanosecond fields, the `occurredAt` in the body, and `occurred_at` itself,
converted through `timedelta` rather than a float so the microsecond column and
the nanosecond fields cannot round apart.

Callers no longer stamp `occurredAt` into the body themselves. One source of
truth per record, set where the record is built.

The column keeps its `server_default` for anything writing outside this path,
but the path always supplies a value.

## Consequences

- Events raised by one frame now hold distinct, increasing timestamps in the
  order they were created, so `list_events` returns arrival before scene change
  rather than an arbitrary order within a shared value.
- The age reported by `get_current_scene` is the age of the observation, not the
  age of a transaction.
- Rows written before this decision keep their transaction-start timestamps. A
  query spanning the change sees the old records clustered on shared values.
  Nothing is rewritten; the history is what it was recorded as.
- The clock is the wall clock and can move backwards when the host adjusts it.
  Ordering assumes it does not, which is the same assumption the nanosecond
  fields already made.
- A scene change held back by the floor is reported with the contents of the
  frame that finally raised it, not the frame that first differed. If the scene
  changed twice inside the floor, the intermediate state is not announced. That
  is the floor doing its job, and it now leaves the reader on the current state
  rather than on a stale one.
- No migration accompanies this. The change is in what the application writes,
  not in the shape of the table.
