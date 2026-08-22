# FEAT-0012: Interface and localisation

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [FEAT-0009](FEAT-0009-catalog-management.md)

## What it does

English and Spanish, dark and light themes, and a layout that fits the viewport
without the page scrolling.

## Localisation

Every user facing string comes from a translation file. Adding a string means
adding it to both languages; a key left in one is visible immediately as the key
itself rendered on screen.

One detail worth knowing: a translation key that becomes a group of keys must
not still be used as a string anywhere. Doing so renders the object rather than
text, which is the kind of failure that reaches production because it is not a
build error.

## Theming

Colours are CSS custom properties defined per theme, in three places: the light
default, the explicit dark theme, and the system preference. A token added to
the explicit dark theme but not the system preference block is correct for
whoever picked a theme and wrong for everyone who never did.

Derived values are derived rather than written out. Accent tints and the focus
ring are computed from the accent colour, so a change to the brand cannot leave
them behind on the previous one.

## Layout

The application shell fills the viewport and scrolling happens inside the
content area. The view page is laid out so the video takes the space available
and the side column scrolls within itself, so the interface fits vertically with
no page scroll.

Below the desktop breakpoint the sections stack and the page scrolls normally,
which is the right behaviour on a phone.

Chrome text is not selectable. Labels, headings and buttons exist to be read and
pressed, and a drag across a control leaving them painted makes an application
feel like a page. Inputs stay selectable, and so do barcode values and the scene
description, which are values someone would reasonably copy.
