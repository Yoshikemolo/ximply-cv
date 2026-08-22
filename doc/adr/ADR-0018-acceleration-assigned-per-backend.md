# ADR-0018: Assign acceleration per backend at runtime

- **Status**: Accepted
- **Related**: [ADR-0009](ADR-0009-discover-acceleration-at-runtime.md),
  [ADR-0011](ADR-0011-cache-model-weights-in-volumes.md),
  [FEAT-0011](../features/FEAT-0011-hardware-acceleration.md),
  [Deployment, GPU deployment](../operations/deployment.md#gpu-deployment),
  [API Reference, Acceleration](../infrastructure/api.md#acceleration)

## Context

[ADR-0009](ADR-0009-discover-acceleration-at-runtime.md) settled how the
machine's capability is discovered. It did not settle what to do with the
answer, and until now the answer was also the decision: a backend that could be
accelerated was accelerated. The one place that needed a different answer, the
landmark delegate, got an environment variable read once at startup.

Two things were wrong with that.

The first is that whether a backend is worth accelerating is a property of the
deployment rather than of the code. The landmark models are the case that
proves it. Asked for the GPU delegate in a container, all three landmarkers
refuse to start with "GPU emulation detected, but not supported": the delegate
needs a physical graphics context and a virtualised graphics stack does not
provide one. The measured frame time fell from 42 ms to 8 ms, which looked like
a large win and was in fact the overlay being absent, because the models it
draws had failed to load. The same delegate on a machine with a real context is
a genuine improvement. No value compiled into the application is right for both
of those.

The second is that changing the answer cost a restart. Working out whether an
accelerator is helping means moving one thing at a time and comparing, and a
loop that runs through an environment variable, a rebuild and a lost session is
a loop nobody completes. The question people actually have in front of a slow
frame rate is which part is slow, and the software made that expensive to ask.

Underneath both sat a smaller problem: one flag per backend was being asked to
carry three different facts. Whether the machine can accelerate this, whether
anyone wants it to, and what is happening right now are separate, and the
landmark case is exactly where they come apart.

## Decision

Acceleration is assigned per backend, at runtime, and the models affected are
rebuilt rather than kept on both devices.

### Three backends, named and stable

| Key | Covers | Runtime |
| --- | --- | --- |
| `detection` | Detection, segmentation and the body descriptor | PyTorch |
| `face` | Face recognition | ONNX Runtime |
| `landmarks` | Pose, hands and face mesh | MediaPipe Tasks |

The grouping follows the runtimes rather than the features, because a runtime
is what actually succeeds or fails at reaching a device. The keys are part of
the interface: the client sends one back to say which switch was thrown.

### Capability and choice are separate fields

Each backend reports three:

- `supported`, whether this machine could accelerate it at all.
- `enabled`, whether it has been asked to.
- `accelerated`, what is happening, which is the two above taken together.

Collapsing these into one flag is what produced a badge claiming acceleration
while the overlay it was measuring had never loaded. Kept apart, a backend that
is supported, switched on and still running on the processor is a state the
interface can draw and explain rather than a contradiction.

### Changing it is a permission, reading it is not

`GET /api/v1/health/acceleration` stays public: it describes the server and no
user data, and the client draws it before a frame is ever sent.
`PUT /api/v1/health/acceleration` requires `detection:configure`.

The asymmetry is not caution for its own sake. The preference is server wide.
One person moving face recognition to the processor moves it for everyone whose
frames that server is handling, so it belongs with the rest of the detection
configuration rather than with a per viewer display toggle.

The response to the change is the whole status rather than an acknowledgement.
A client that flipped its own switch optimistically would eventually draw a
state the server does not hold, and the interesting fields here are precisely
the ones it cannot compute.

### The models are rebuilt, not duplicated

Switching a backend drops what it owns, and the next frame that needs a model
builds it on the new device. Nothing is held on both.

What actually has to be rebuilt varies, and only the ones that do are touched:

- **Detection and segmentation need nothing.** They are handed a device on
  every call, so the next frame already uses the new one.
- **The body descriptor does.** It is moved onto its device once when it loads,
  so it has to be dropped to move.
- **Face recognition does.** The execution providers are chosen when the
  session is built.
- **The landmarkers must be closed and recreated.** The delegate is fixed when
  a landmarker is created, and they hold native resources that dropping the
  reference does not free.

Keeping a second copy on the other device would make the switch instant and
would cost that memory permanently, on a machine where the memory in question
is the reason for accelerating in the first place. A switch thrown a handful of
times in the life of a deployment does not earn that.

### The badge reports work, not hardware

`is_active` is true when at least one backend is both capable and switched on.
Switching everything off turns the badge amber rather than leaving it
describing a GPU that nothing is using.

`ACCELERATION_MEDIAPIPE_GPU` survives as the initial preference for
`landmarks` and nothing more. It no longer gates the probe, so a container that
starts with the delegate off still knows it could be asked for, and the panel
can offer the switch instead of hiding the row.

## Consequences

- A switch costs a rebuild on the next frame that needs the model, a second or
  two, once. The interface says so while it happens rather than appearing to
  hang.
- Preferences live in memory and are not persisted. A restart returns to the
  defaults: detection and face on, landmarks from
  `ACCELERATION_MEDIAPIPE_GPU`. A deployment that wants a different resting
  state sets the variable; there is no stored setting to migrate, and no way to
  make a change stick across a restart.
- The service is a singleton per process, and the production override runs four
  workers. A change reaches the worker that served the request and no other, so
  on a multi worker deployment the switch is unreliable and the status read
  afterwards may come from a worker that never saw it. Move a backend with one
  worker running, or accept that it applies to a fraction of the frames.
- Probing is still done once per process
  ([ADR-0009](ADR-0009-discover-acceleration-at-runtime.md)). Switching a
  backend does not re-probe, so a driver installed after the server started is
  found by restarting it, not by throwing a switch.
- A rebuild that fails is logged and swallowed. The model was already dropped
  and the next frame retries, so the preference is reported as applied, because
  it was. The consequence is that a backend can be switched on and stay on the
  processor, which is the state `accelerated` exists to show.
- Switching a backend off does not switch the feature off. Face recognition
  moved to the processor is slower and still recognises people.
- None of this replaces the GPU compose override. These switches decide how an
  available accelerator is used; whether the container has one at all is still
  decided by `docker-compose.gpu.yml`.
