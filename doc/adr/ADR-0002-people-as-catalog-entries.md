# ADR-0002: People are catalog entries in a system category

- **Status**: Accepted
- **Related**: [ADR-0003](ADR-0003-dual-embedding-person-reidentification.md),
  [SEC-0004](../sec/SEC-0004-biometric-data.md),
  [Architecture, PostgreSQL Database](../infrastructure/architecture.md#postgresql-database)

## Context

The application recognises people as well as objects. A person needs a name,
a portrait, a history of sightings and the ability to be renamed, merged and
deleted. Objects already have all of that.

Two shapes were available: a dedicated `people` table with its own API, service
layer and catalog tab, or reusing the existing object entity.

## Decision

A person is an `ObjectEntity` row in a system category named **People**. Their
identity vectors live in a separate `person_embeddings` table keyed by that row.

The category is created on demand per owner. The catalog lists People as a
separate tab, so a recognised face is never mixed in with trained products.

## Consequences

- Listing, renaming, thumbnails, image upload, merging and deletion apply to
  people with no new code.
- The object entity carries fields that make no sense for a person, such as
  price and weight. They are nullable and left empty.
- Care is needed to keep the two apart where the distinction matters. Portraits
  must be excluded from the object feature matcher, or any textured object
  scores against a photograph of a face; see
  [ADR-0004](ADR-0004-segmentation-never-replaces-detection.md) for the related
  principle and the incident that motivated it.
- Biometric material is now stored in the same database as ordinary catalog
  data, which raises the sensitivity of the whole store. See
  [SEC-0004](../sec/SEC-0004-biometric-data.md).
