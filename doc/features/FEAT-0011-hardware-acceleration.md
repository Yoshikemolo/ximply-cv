# FEAT-0011: Hardware acceleration

- **Related**: [ADR-0009](../adr/ADR-0009-discover-acceleration-at-runtime.md),
  [ADR-0011](../adr/ADR-0011-cache-model-weights-in-volumes.md),
  [ADR-0018](../adr/ADR-0018-acceleration-assigned-per-backend.md),
  [FEAT-0010](FEAT-0010-accounts-and-access.md),
  [SEC-0007](../sec/SEC-0007-container-hardening.md),
  [Deployment, GPU deployment](../operations/deployment.md#gpu-deployment),
  [Readme, GPU acceleration](../../README.md#gpu-acceleration)

## What it does

Runs the models on an NVIDIA GPU when the machine has one and on the processor
when it does not, and lets that be decided per part of the pipeline while the
server is running. A badge in the header says whether dedicated hardware is
doing the work, and opens a panel with a switch for each of the three backends.

Green means at least one backend is on the accelerator, amber means everything
is on the processor. Nothing else is spent on the colour, because that is the
only question the badge exists to answer.

## The three backends

They are grouped by the runtime that has to reach the device, not by the
feature the user sees, because a runtime is what succeeds or fails at getting
there.

| Switch | Moves | Through |
| --- | --- | --- |
| Object detection | YOLO detection, Segment Anything, the ResNet50 body descriptor, and the description model when it loads | PyTorch |
| Face recognition | The InsightFace embedding | ONNX Runtime |
| Skeleton and mesh | Pose, hands and the face mesh | MediaPipe Tasks |

They move independently because they fail independently. A machine can have a
working CUDA runtime for PyTorch while the ONNX runtime installed is the
processor only build, and the landmark delegate can be present and still
unusable. Reporting one "GPU: yes" over all three would be wrong in both
directions.

## Three states, not one

Every backend reports three things, and they genuinely differ:

- **Supported**, whether this machine could accelerate it at all.
- **Enabled**, whether it has been asked to.
- **Accelerated**, what is actually happening.

The landmark models are the case that needs all three. They are supported on a
machine with a GPU and switched off by default, because the MediaPipe delegate
needs a real graphics context and a container usually has none. Asked for it
there, all three landmarkers refuse to start and the overlay disappears, which
measures as a large speedup and is nothing of the sort. A single flag could not
express "this machine could, and we are deliberately not".

## The panel

The badge opens rather than only explaining. Inside it:

- The device, its memory, the CUDA version and the compute capability, which
  used to be a tooltip and now sit next to the switches that act on them.
- A count of how many backends are accelerated out of the total.
- One row per backend with its switch, what it is running on, and the device
  name reported for it.
- A row whose backend the machine cannot accelerate is shown with its switch
  disabled and the reason beside it, rather than hidden. Leaving it out would
  make the panel look complete while omitting the row that explains why the
  badge is amber.

Throwing a switch calls the server and waits for it. The row says the models
are rebuilding while that happens, and the panel is drawn from the status the
server sends back rather than from an optimistic guess.

Without `detection:configure` the panel is read only, with a line saying so.
Seeing what the server is doing is not the same as deciding it
([FEAT-0010](FEAT-0010-accounts-and-access.md)).

## How it is implemented

An acceleration service probes each backend once, caches the result for the
life of the process, and holds a preference per backend alongside it. Every
model asks the service for its device rather than deciding for itself, so there
is one place where the answer is known and one place a switch has to change it.

The device is exercised before it is promised to anything, because availability
can be reported while the first allocation fails on a driver mismatch.

`PUT /health/acceleration` sets one preference and then rebuilds whatever that
backend owns. What has to be rebuilt is not the same for each:

- Detection and segmentation need nothing. They are handed a device on every
  call, so the next frame already uses the new one.
- The body descriptor is dropped, because it is moved onto its device once when
  it loads.
- The face embedder is dropped, because its execution providers are fixed when
  the session is built.
- The landmarkers are closed and dropped, because the delegate is fixed when a
  landmarker is created and they hold native resources that dropping the
  reference does not free.

The cost is a rebuild on the next frame that needs the model, a second or two,
once. The alternative was keeping every model loaded on both devices, which
spends the memory that was the reason for accelerating. The reasoning is in
[ADR-0018](../adr/ADR-0018-acceleration-assigned-per-backend.md).

A rebuild that fails is logged and swallowed. The model has already been
dropped and the next frame retries, and raising would report a preference as
rejected when it had in fact been applied.

## Interfaces

- `GET /api/v1/health/acceleration` reports availability, whether anything is
  actually running on it, the device details, and `key`, `supported`, `enabled`
  and `accelerated` for each backend. Unauthenticated, because it describes the
  server rather than any user data and the client draws it before the first
  frame is sent.
- `PUT /api/v1/health/acceleration` takes a backend key and a boolean, requires
  `detection:configure`, and answers with the full status after the change.
  Request and response shapes are in the
  [API reference](../infrastructure/api.md#acceleration).

## Behaviour worth knowing

- **The setting is server wide.** It is not a display toggle. Moving face
  recognition to the processor moves it for everyone whose frames that server
  is handling, which is why it sits behind a permission.
- **Preferences are not persisted.** A restart returns to detection and face on
  and landmarks taking whatever `ACCELERATION_MEDIAPIPE_GPU` says. That
  variable now only seeds the initial preference; it no longer decides whether
  the delegate is probed for at all.
- **A change reaches one worker.** The service is a singleton per process and
  the production override runs four of them, so on a multi worker deployment a
  switch applies to the worker that served the request and the status read
  afterwards may come from another. Switch backends with a single worker
  running.
- **Switching a backend off does not switch the feature off.** It moves it to
  the processor. Face recognition on the CPU is slower and still recognises
  people.
- **Nothing here replaces the compose override.** These switches decide how an
  available accelerator is used. Whether the container has one at all is
  decided by `docker-compose.gpu.yml`, because reserving a GPU device fails
  outright on a machine without one. See the
  [deployment guide](../operations/deployment.md#gpu-deployment).
- **The description model is not rebuilt by the switch.** It reads the same
  device as the detection backend, but it takes it once when it loads and the
  rebuild only covers detection's own models. A vision language model already
  in memory stays where it was until the server restarts
  ([FEAT-0007](FEAT-0007-scene-description.md)).
- **The probe does not repeat.** A driver installed after the server started is
  picked up by restarting it, not by throwing a switch.
