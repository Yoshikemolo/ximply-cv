# FEAT-0002: Recognising your own objects

- **Related**: [FEAT-0008](FEAT-0008-teaching-the-catalog.md),
  [FEAT-0009](FEAT-0009-catalog-management.md),
  [ADR-0005](../adr/ADR-0005-two-confidences.md),
  [API Reference, Objects](../infrastructure/api.md#objects)

## What it does

Matches a detected region against the objects you have taught it, so a generic
class becomes a specific entry with your name, reference and metadata attached.

## How it is implemented

Recognition uses ORB feature descriptors rather than a trained network, which is
why adding an object takes effect immediately instead of requiring a fine tuning
run.

- On startup, or on demand, every active catalog entry with images has its
  descriptors extracted and held in an in memory cache keyed by entry.
- For each detection, the cropped region is described and matched against the
  cache with a brute force Hamming matcher and Lowe's ratio test.
- The score combines the number of surviving matches with their average
  distance, and a minimum confidence rejects the weakest.

The cache is updated atomically: descriptors are extracted before the cache
entry is replaced, so a failed extraction leaves the previous ones in place
rather than emptying the entry.

## Patterns and interfaces

- **Singleton service with an internal cache.** `FeatureMatchingService` owns
  the cache and exposes load, match, remove and clear. Routes never touch the
  cache directly.
- **Cache invalidation at the write sites.** Renaming, deactivating, deleting
  and merging all update the cache, because a cache keyed by name that is not
  updated on rename keeps announcing the old one.

## Known limitations

- ORB is texture based. A plain or reflective object gives few descriptors and
  matches poorly.
- The minimum confidence is low by default, which produces occasional confident
  looking matches on unrelated objects. This is why identity confidence is
  reported separately and a weak match is labelled as a guess
  ([ADR-0005](../adr/ADR-0005-two-confidences.md)).
- **People are excluded from this matcher.** A portrait produces descriptors
  generic enough that any textured object scores against it, which is how a bus
  was once announced as a person. Person identity comes from
  [FEAT-0003](FEAT-0003-person-recognition.md) instead.
