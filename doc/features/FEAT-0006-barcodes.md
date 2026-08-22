# FEAT-0006: Barcodes and QR codes

- **Related**: [FEAT-0001](FEAT-0001-live-detection.md),
  [API Reference, Detection](../infrastructure/api.md#detection)

## What it does

Reads barcodes and QR codes from the same frame as everything else, with no
separate mode to switch into. Each result carries its symbology, its decoded
value and its position in the frame.

## How it is implemented

ZBar through pyzbar, with the OpenCV QR detector kept as a fallback. ZBar
replaced the OpenCV barcode detector because it reads reliably at angles and
resolutions where the latter did not.

Detection runs on the same decoded frame the object detector used, so there is
no second capture and no risk of the two disagreeing about what was on screen.

## Behaviour worth knowing

- Results are drawn with a dashed box and the value below, to distinguish them
  from object detections at a glance.
- The decoded value is one of the few pieces of text in the interface that stays
  selectable, since copying it is the point of scanning it.
- The runtime image installs the ZBar shared library. A build without it loses
  barcode reading and nothing else.
