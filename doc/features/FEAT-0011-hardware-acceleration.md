# FEAT-0011: Hardware acceleration

- **Related**: [ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md),
  [ADR-0011](../adr/ADR-0011-cache-model-weights-in-volumes.md),
  [SEC-0007](../sec/SEC-0007-container-hardening.md),
  [Deployment, Production Deployment](../operations/deployment.md#production-deployment),
  [Readme, GPU acceleration](../../README.md#gpu-acceleration)

## What it does

Moves object detection, face recognition, the body descriptor and segmentation
onto an NVIDIA GPU when the machine has one, and falls back to the processor
when it does not. A badge in the header says which is happening, with the device
and the per backend breakdown in its tooltip.

## How it is implemented

An acceleration service probes each backend once and caches the result:

- **PyTorch**, for detection, segmentation and the body descriptor.
- **The ONNX runtime**, for face recognition. Its execution providers depend on
  which build is installed, which is why this is asked separately.
- **The landmark delegate**, which needs a graphics context a headless container
  usually lacks and is therefore off unless asked for.

The device is exercised before it is promised to anything, because availability
can be reported while the first allocation fails on a driver mismatch.

Each model asks the service for its device rather than deciding for itself, so
there is one place where the answer is known.

## Interfaces

- `GET /api/v1/health/acceleration` reports availability, the device, its
  memory, the runtime version and the state of each backend. It is unauthenticated
  because it describes the server rather than any user data, and the client shows
  it before the first frame is sent.

## Deployment

Reserving a GPU device fails outright on a machine without one, so it lives in a
separate compose override rather than the base configuration. See the
[deployment guide](../operations/deployment.md#gpu-deployment).
