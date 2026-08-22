# FEAT-0009: Catalog management

- **Related**: [FEAT-0002](FEAT-0002-object-catalog.md),
  [FEAT-0003](FEAT-0003-person-recognition.md),
  [FEAT-0008](FEAT-0008-teaching-the-catalog.md),
  [ADR-0002](../adr/ADR-0002-people-as-catalog-entries.md),
  [API Reference, Objects](../infrastructure/api.md#objects)

## What it does

Lists, searches, renames, merges and deletes catalog entries, with People kept
in their own tab.

## Renaming

Available inline wherever an entry appears, in the catalog and in the live
detections list. A pencil beside the name swaps the text for an input with a
clear button; Enter commits, Escape reverts.

Validation runs while typing rather than on submit, so the field turns red the
moment the name becomes unusable instead of only when the user tries to save,
and Enter is inert while it is invalid. The reason appears in small red text
below: empty, or already in use. Names are compared trimmed and case folded,
because two entries differing only in those are indistinguishable in a list.

The server validates again and answers 409 on a duplicate, so a clash created
between two clients is still caught.

## Merging and deletion

- **Merge** folds several entries into one, moving images and descriptors and
  removing the sources.
- **Bulk delete** removes every selected entry, after a confirmation that lists
  them by name. Deletions are tracked individually so a partial failure leaves
  the failed entries selected rather than claiming they are gone.
- **Forget all** clears the catalog and both caches.

## The detections list

Detection runs several times a second, so the raw list flickers: the same object
reappears every frame with a slightly different confidence. Detections are
aggregated into one card per thing, keyed by identity when recognised and by
label otherwise.

A card holds the **best** sighting of the last few seconds rather than the
newest one, along with the thumbnail cropped from the frame where it looked
clearest. Cards expire when nothing has been seen for a while.

Four tabs slice the list: all, above the certainty threshold, humans and
objects. A search box matches the name, the type and the percentage, so typing
a number finds everything detected at that confidence.

## Patterns and interfaces

- **A shared rename component** used by both pages, so the validation rules
  cannot diverge between them.
- **Category name in the list response**, so the client can tell a person from
  an object without a request per row.
- **The detector class is kept alongside the display name.** Once an entry is
  recognised the label becomes its catalog name, so a person renamed to a
  personal name would otherwise stop looking like a person to every filter.
