# FEAT-0008: Teaching the catalog

- **Related**: [FEAT-0002](FEAT-0002-object-catalog.md),
  [FEAT-0003](FEAT-0003-person-recognition.md),
  [FEAT-0009](FEAT-0009-catalog-management.md),
  [API Reference, Objects](../infrastructure/api.md#objects)

## What it does

Two ways to add something to the catalog, mixable on the same entry:

- **Upload a gallery.** Images in any common format, with a box drawn around
  what matters and metadata attached.
- **Capture live.** Point the camera at the thing and save the detection
  straight into the catalog.

## How it is implemented

**From the camera.** `POST /api/v1/detection/capture` takes the frame, the box
and a name. It crops the region, stores the crop in the object store, creates or
extends the catalog entry, and reloads that entry's descriptors so it is
recognisable on the very next frame rather than after a restart. A name that
already exists adds an image to that entry instead of creating a duplicate.

**From uploads.** The Learn page provides annotation tools: draw a box, resize
it from its corners, move it, or select the whole image. Coordinates are scaled
between the displayed image and its natural size, so an annotation drawn on a
scaled preview lands correctly on the stored file. Images are uploaded per entry
and the first becomes the thumbnail.

**Retraining** is the same path with an existing entry selected, so more views
of the same object accumulate rather than creating a second entry.

## Patterns and interfaces

- **One capture endpoint for both new and existing entries.** The decision is
  made from the name, which keeps the client from having to know whether an
  entry exists.
- **Immediate cache refresh** after a write, so learning is visible in the live
  view without a reload.
- **People are marked in the list**, because they train through the embedding
  pipeline rather than the object matcher, and teaching a colleague as if they
  were a product would train the object matcher on a face it cannot recognise
  reliably.
