# SEC-0007: Container hardening

- **Status**: Enforced
- **Related**: [ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md),
  [ADR-0011](../adr/ADR-0011-cache-model-weights-in-volumes.md),
  [SEC-0006](SEC-0006-default-credentials-and-secrets.md),
  [Deployment, Production Deployment](../operations/deployment.md#production-deployment)

## What is in place

- **Both application images run as a non root user.** The backend and the web
  server each create an unprivileged user and switch to it before the process
  starts.
- **Multi stage builds.** Compilers and build dependencies stay in the build
  stage. The runtime image carries only the virtual environment and the runtime
  libraries.
- **Health checks** on every service, so a container that is running but not
  serving is visible as unhealthy rather than assumed good.
- **The frontend sends security headers**: frame options, content type options,
  referrer policy.
- **Only hashed assets are cached immutably.** Unhashed bundles revalidate, and
  the document is never cached, so a deployment reaches the browser.

## Accepted exceptions

- **The GPU image carries a C compiler.** The compiled kernel path builds a
  helper module from source on first use and fails outright without one. Eager
  attention and disabling the compiled backends were both tried first and
  neither avoided that path. The exception is confined to the GPU build: the
  processor only image does not reach it and does not carry the toolchain.
- **Model weights are downloaded at runtime** rather than baked in, so the first
  start of a fresh deployment reaches the model publishers. See
  [ADR-0011](../adr/ADR-0011-cache-model-weights-in-volumes.md) and the
  outbound connections section of [SEC-0001](SEC-0001-local-only-inference.md).

## Not addressed

- No read only root filesystem, no dropped capabilities, no seccomp profile
  beyond the runtime default.
- No image scanning in the build.
- The compose files publish ports on all interfaces. Bind them to the loopback
  address, or put a reverse proxy in front, before running on a shared network.
