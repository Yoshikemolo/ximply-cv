# ADR-0019: Confirm an unknown person before enrolling them

- **Status**: Accepted. Amends
  [ADR-0012](ADR-0012-automatic-enrolment-of-unknown-people.md), which decided
  that enrolment happens automatically. It still does. What changes is what
  counts as enough evidence to create a person.
- **Related**: [ADR-0003](ADR-0003-dual-embedding-person-reidentification.md),
  [ADR-0006](ADR-0006-class-aware-suppression.md),
  [ADR-0007](ADR-0007-view-filters-applied-server-side.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [FEAT-0003](../features/FEAT-0003-person-recognition.md)

## Context

[ADR-0012](ADR-0012-automatic-enrolment-of-unknown-people.md) accepted one
gate before creating a person: a sighting with no face embedding needs a large
enough body crop. A sighting with a face embedding was enrolled outright.

In use, that produced a catalog steadily filling with people who were seen once
and never again. A single camera watching one person for an evening had
accumulated seven such entries, five of them with one or two sightings against
25,402 for the person actually in the room. Two of them were created five
seconds apart while that person was matched in the same frames at 0.95 and 0.98
confidence.

The residue is not cosmetic. Every phantom entry is a face vector the matcher
has to consider, a candidate the real person can be split against, and a
biometric record of somebody who was never there in the sense the catalog
claims.

Four distinct causes were behind it, and only the fourth is about thresholds.

**A person arrives as more than one box.** People are identified before
overlapping boxes are resolved, and that ordering is deliberate: a recognised
person carries a name into deduplication and wins over a bare detector box
([ADR-0007](ADR-0007-view-filters-applied-server-side.md)). The cost is that
one human can reach enrolment as two boxes. The whole figure matches. The
second box, holding a shoulder and half a jaw, matches nothing, and read on its
own it is indistinguishable from a stranger.

**A near miss looks exactly like a stranger.** `match()` answered with a person
or with nothing. A sighting scoring 0.37 against a known face, one hundredth
under the threshold, produced the same silence as a sighting scoring 0.02. The
first is that person in worse light; the second is somebody else. Treating them
alike enrols a duplicate of somebody already in the catalog, and every later
sighting then has two entries to be divided between.

**A face the detector was guessing at still yields a vector.** The embedder
rejects faces below a size floor, but not faces it was unsure of. A reflection
in a monitor, a face on a screen behind the subject, a profile at the edge of
frame: all produce an embedding, and any of them could define a new person.

**Nothing has to happen twice.** A person genuinely in the room is seen several
times a second. A single frame was enough to mint a permanent record, which
means every transient artefact in the pipeline had a direct route into the
catalog.

## Decision

Creating a person is treated as far more expensive than failing to recognise
one. A missed recognition costs one frame. A person invented from a bad crop
stays in the catalog for good.

Recognition is unchanged. Everything below gates enrolment only, so a person
who is hard to see is still matched as readily as before; they simply do not
become a second entry when the match fails.

### Matching is resolved for every box before any enrolment is considered

`_identify_people()` runs in two passes. The first evaluates every person box
against the gallery. The second considers enrolment only for what is left over,
and refuses any box overlapping a box already identified in this frame, at the
thresholds deduplication would use on the same pair.

The ordering that causes the problem is kept, because the reason for it stands.
What changes is that a box is now judged against what the rest of the frame
turned out to be, which is knowable only once the first pass is done.

### The band below the threshold enrols nobody

`evaluate()` reports the best similarity found whether or not it was accepted,
so a caller can tell a stranger from a known person seen badly. A sighting
whose best candidate sits within `PERSON_ENROL_MARGIN` of either threshold is
neither matched nor enrolled. It is left as an unidentified person box for that
frame.

Refusing to answer is the right answer here. The alternative is not "match
them" — the threshold exists because that similarity is not reliable enough to
put a name on a face — it is "invent somebody", which is worse than both.

### A face has to be one the detector was confident about

Enrolment requires the face detector's own score to clear
`PERSON_MIN_ENROL_FACE_QUALITY`. Recognition still runs on weaker faces. The
size floor in the embedder keeps out faces too small to describe; this keeps
out the ones it was guessing at.

### An unknown fingerprint has to come back

Unmatched sightings that pass the gates above go into an in-memory buffer of
candidates rather than into the catalog. A candidate becomes a person once the
same fingerprint has returned `PERSON_ENROL_CONFIRMATIONS` times within
`PERSON_ENROL_WINDOW_SECONDS`, and is dropped if it stops coming back.

The buffer is not persisted. Losing it on a restart costs nothing: somebody
really standing there is seen again on the next frame and starts over.

Setting the count to one restores the previous behaviour exactly.

## Consequences

- A new person is named a few seconds later than before, once they have been
  seen enough times to be believed. During those seconds they are an
  unidentified person box, which is what they were before enrolment anyway.
- Somebody who walks through the edge of frame and leaves is never enrolled.
  Whether that is a loss depends on the deployment: a doorway camera that wants
  every passer-by recorded should lower the confirmation count.
- The gates compound. A person seen only in poor conditions — always in
  profile, always at distance, never with a confident face — may never be
  enrolled at all. That is the intended trade: the catalog holds fewer entries
  and each one means something.
- The candidate buffer lives in one process. A deployment running several
  workers holds a separate buffer per worker, so confirmations accumulate only
  as fast as one worker sees the person. With frames from one browser arriving
  in sequence this is not usually visible, but it means the count is a floor
  rather than an exact number.
- The margin is a second threshold and inherits the first one's difficulty:
  set too wide, a genuine stranger standing near a known person's similarity is
  never enrolled at all.
- Entries created before this decision are still in the catalog. Nothing here
  removes them; they are deleted from catalog management like any other entry.
