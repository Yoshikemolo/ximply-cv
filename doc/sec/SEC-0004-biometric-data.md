# SEC-0004: Biometric data

- **Status**: Enforced, with the retention gaps noted below
- **Related**: [ADR-0002](../adr/ADR-0002-people-as-catalog-entries.md),
  [ADR-0003](../adr/ADR-0003-dual-embedding-person-reidentification.md),
  [ADR-0012](../adr/ADR-0012-automatic-enrolment-of-unknown-people.md),
  [SEC-0005](SEC-0005-consent-and-lawful-basis.md),
  [SEC-0003](SEC-0003-object-storage-exposure.md)

## What is stored

Per person, in the application database and object store:

- **Face embeddings**, floating point vectors derived from the face crop.
- **Body embeddings**, derived from the whole person crop.
- **Portrait images**, the actual photograph the embedding came from, chosen for
  being the clearest sighting.
- **A name**, sequential until someone renames it.

Under most data protection regimes an embedding used to identify a person is
biometric data and attracts the strictest category of protection. Treat this
store accordingly, whatever the jurisdiction.

## How it is protected

- It never leaves the host. See [SEC-0001](SEC-0001-local-only-inference.md).
- Reading it through the API requires an account with the catalog read
  permission. See [SEC-0002](SEC-0002-authentication-and-authorization.md).
- Deleting a person removes their embeddings by cascade and clears them from the
  in memory gallery, so a deleted person stops being recognised immediately
  rather than at the next restart.
- Samples per person are capped, with the oldest dropped first, so a fingerprint
  does not grow without bound.

## Known gaps

- **Not encrypted at rest.** Embeddings are ordinary array columns and portraits
  are ordinary objects. Anyone with database or object store access reads both.
  Use encrypted volumes, and change the default credentials
  ([SEC-0006](SEC-0006-default-credentials-and-secrets.md)).
- **Portraits are reachable without authentication.** See
  [SEC-0003](SEC-0003-object-storage-exposure.md).
- **No retention policy.** Nothing expires. A person enrolled once is kept until
  someone deletes them by hand. A deployment with a retention obligation must
  implement it; the per person cap limits growth, not lifetime.
- **Deletion is not proven.** Removing a person deletes the rows and the cache
  entry, but object store objects for their images are only removed on the paths
  that delete images explicitly. Verify before relying on a deletion request
  being complete.
