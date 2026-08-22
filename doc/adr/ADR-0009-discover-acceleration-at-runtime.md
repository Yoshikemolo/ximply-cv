# ADR-0009: Discover hardware acceleration at runtime

- **Status**: Accepted
- **Related**: [ADR-0001](ADR-0001-run-every-model-locally.md),
  [ADR-0011](ADR-0011-cache-model-weights-in-volumes.md),
  [ADR-0018](ADR-0018-acceleration-assigned-per-backend.md),
  [Deployment, Production Deployment](../operations/deployment.md#production-deployment),
  [Readme, GPU acceleration](../../README.md#gpu-acceleration)

## Context

The same image has to run on a workstation with a discrete GPU and on a laptop
without one. Configuring which is which by hand means an operator can get it
wrong in both directions: asking for a device that is not there, or leaving one
idle.

The backends also fail independently. A machine can have a working CUDA runtime
for PyTorch while the ONNX runtime installed is the processor only build. A
single flag covering all of them would be wrong in both directions.

## Decision

Each backend is probed separately on first use and the result is cached for the
life of the process. The device is exercised before it is promised to anything,
because availability can be reported while the first allocation fails on a
driver mismatch.

Reserving a GPU device fails outright on a machine without one, so that belongs
in a separate compose override rather than the base configuration. The backend
itself needs no flag either way.

The state is reported per backend at `/api/v1/health/acceleration` and shown as
a badge in the application header.

## Consequences

- One image, two very different machines, no flag to remember.
- The GPU image additionally carries a C compiler, because the compiled kernel
  path builds a helper module from source on first use. The processor only image
  does not reach that path and does not carry the weight. See
  [SEC-0007](../sec/SEC-0007-container-hardening.md).
- The badge can report a partial state, where detection is accelerated and the
  landmark models are not, because that is genuinely what happens.
