"""
Hardware acceleration discovery.

Works out what the machine can actually accelerate on and hands every model the
right device, so the same image runs on a workstation with a discrete GPU and on
a laptop with none, without a different build or a flag to remember.

Availability is probed once and cached. Each backend is asked separately,
because they fail independently: a machine can have a working CUDA runtime for
PyTorch while the ONNX runtime installed is the CPU only build, and reporting a
single "GPU: yes" over that would be a lie in both directions.
"""

import threading
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BackendStatus:
    """
    What one inference backend can use, and what it has been asked to use.

    Three states rather than one, because they answer different questions.
    "supported" is whether this machine could accelerate it at all, "enabled" is
    whether someone asked it to, and "accelerated" is what is actually
    happening. A backend can be supported and switched on and still not
    accelerated, which is what the landmark models do in a container without a
    graphics context.
    """

    key: str
    name: str
    accelerated: bool
    device: str
    detail: str = ""
    supported: bool = False
    enabled: bool = True


@dataclass
class AccelerationReport:
    """The full picture, as reported to the client."""

    available: bool
    active: bool
    device_name: Optional[str] = None
    device_memory_mb: Optional[int] = None
    driver: Optional[str] = None
    compute_capability: Optional[str] = None
    backends: List[BackendStatus] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialise for the API."""
        return {
            "available": self.available,
            "active": self.active,
            "deviceName": self.device_name,
            "deviceMemoryMb": self.device_memory_mb,
            "driver": self.driver,
            "computeCapability": self.compute_capability,
            "backends": [
                {
                    "key": b.key,
                    "name": b.name,
                    "accelerated": b.accelerated,
                    "device": b.device,
                    "detail": b.detail,
                    "supported": b.supported,
                    "enabled": b.enabled,
                }
                for b in self.backends
            ],
        }


class AccelerationService:
    """
    Single source of truth for which device each model should run on.

    Probing is done once on first use. The results do not change while the
    process lives: hardware is not hot plugged into a running container, and
    re-probing on every frame would cost more than it saves.
    """

    #: The three backends the interface offers a switch for, in the order they
    #: are shown. Keys are stable: the client sends them back.
    BACKEND_KEYS = ("detection", "face", "landmarks")

    def __init__(self) -> None:
        self._probed = False
        self._lock = threading.Lock()
        # What each backend has been asked to use. Separate from what the
        # hardware can do: a machine with no accelerator leaves these on and
        # simply has nothing to honour them with.
        self._preferences = {
            "detection": True,
            "face": True,
            "landmarks": settings.acceleration_mediapipe_gpu,
        }
        self._torch_device = "cpu"
        self._torch_detail = ""
        self._onnx_providers: List[str] = ["CPUExecutionProvider"]
        self._onnx_detail = ""
        self._mediapipe_gpu = False
        self._mediapipe_detail = ""
        self._device_name: Optional[str] = None
        self._device_memory_mb: Optional[int] = None
        self._driver: Optional[str] = None
        self._capability: Optional[str] = None

    def _probe_torch(self) -> None:
        """Ask PyTorch whether it has a usable accelerator."""
        try:
            import torch

            if torch.cuda.is_available():
                # is_available() can be true while the first allocation fails on
                # a driver mismatch, so the device is exercised before it is
                # promised to anything.
                torch.zeros(1, device="cuda")
                index = torch.cuda.current_device()
                properties = torch.cuda.get_device_properties(index)
                self._torch_device = "cuda"
                self._device_name = properties.name
                self._device_memory_mb = int(properties.total_memory / (1024 * 1024))
                self._capability = f"{properties.major}.{properties.minor}"
                self._torch_detail = torch.__version__
                try:
                    self._driver = torch.version.cuda
                except Exception:
                    self._driver = None
                return

            if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                self._torch_device = "mps"
                self._device_name = "Apple Metal"
                self._torch_detail = torch.__version__
                return

            self._torch_detail = f"{torch.__version__} without a usable accelerator"
        except Exception as e:
            self._torch_detail = f"unavailable: {e}"

    def _probe_onnx(self) -> None:
        """Ask the ONNX runtime which execution providers it was built with."""
        try:
            import onnxruntime

            available = list(onnxruntime.get_available_providers())
            preferred = [p for p in ("CUDAExecutionProvider",) if p in available]

            if preferred:
                self._onnx_providers = preferred + ["CPUExecutionProvider"]
                self._onnx_detail = onnxruntime.__version__
            else:
                self._onnx_providers = ["CPUExecutionProvider"]
                self._onnx_detail = (
                    f"{onnxruntime.__version__}, CPU build. "
                    "Install onnxruntime-gpu to accelerate face recognition."
                )
        except Exception as e:
            self._onnx_detail = f"unavailable: {e}"

    def _probe_mediapipe(self) -> None:
        """
        Decide whether the landmark models should ask for the GPU delegate.

        The delegate needs a working GL context, which a headless container
        usually does not have. This records only whether it could be asked for;
        whether it is asked for is a preference the operator sets.
        """
        if self._torch_device != "cuda":
            self._mediapipe_detail = "no accelerator to delegate to"
            return
        try:
            from mediapipe.tasks import python as mp_python

            hasattr(mp_python.BaseOptions.Delegate, "GPU")
            self._mediapipe_gpu = True
            self._mediapipe_detail = (
                "GPU delegate available. It needs a real graphics context, which "
                "a container usually lacks, and falls back to the processor when "
                "it cannot start."
            )
        except Exception as e:
            self._mediapipe_detail = f"unavailable: {e}"

    def _ensure_probed(self) -> None:
        """Run the probes once."""
        if self._probed:
            return
        with self._lock:
            if self._probed:
                return

            if settings.acceleration_enabled:
                self._probe_torch()
                self._probe_onnx()
                self._probe_mediapipe()
            else:
                self._torch_detail = "disabled by configuration"
                self._onnx_detail = "disabled by configuration"
                self._mediapipe_detail = "disabled by configuration"

            self._probed = True

            if self.is_active:
                logger.info(
                    f"Hardware acceleration active on {self._device_name}: "
                    f"torch={self._torch_device}, onnx={self._onnx_providers[0]}"
                )
            else:
                logger.info("Running on CPU, no hardware acceleration in use")

    @property
    def torch_device(self) -> str:
        """Device string to move PyTorch models onto."""
        self._ensure_probed()
        if not self._preferences["detection"]:
            return "cpu"
        return self._torch_device

    @property
    def ultralytics_device(self) -> str:
        """
        Device in the form Ultralytics expects.

        It takes a CUDA index rather than the word "cuda", and the string "cpu"
        otherwise.
        """
        self._ensure_probed()
        device = self.torch_device
        return "0" if device == "cuda" else device

    @property
    def onnx_providers(self) -> List[str]:
        """Execution providers to build ONNX sessions with, best first."""
        self._ensure_probed()
        if not self._preferences["face"]:
            return ["CPUExecutionProvider"]
        return list(self._onnx_providers)

    @property
    def insightface_ctx_id(self) -> int:
        """
        Context id for InsightFace, which predates the provider API.

        Zero selects the first GPU, minus one forces CPU.
        """
        self._ensure_probed()
        return 0 if self.onnx_providers[0] == "CUDAExecutionProvider" else -1

    @property
    def mediapipe_gpu(self) -> bool:
        """Whether landmark models should ask for the GPU delegate."""
        self._ensure_probed()
        return self._mediapipe_gpu and self._preferences["landmarks"]

    @property
    def is_available(self) -> bool:
        """Whether the machine has an accelerator at all."""
        self._ensure_probed()
        return self._torch_device != "cpu" or "CUDAExecutionProvider" in self._onnx_providers

    @property
    def is_active(self) -> bool:
        """Whether anything is actually running on it."""
        self._ensure_probed()
        if not (self.is_available and settings.acceleration_enabled):
            return False
        # At least one backend has to be both capable and switched on. Reporting
        # acceleration while every backend has been turned off would be a badge
        # that describes the hardware rather than the work.
        return any(b.accelerated for b in self._backend_states())

    @property
    def preferences(self) -> dict:
        """What each backend has been asked to use."""
        return dict(self._preferences)

    def set_preference(self, key: str, enabled: bool) -> bool:
        """
        Ask one backend to use the accelerator, or to stop.

        Args:
            key: One of BACKEND_KEYS.
            enabled: Whether that backend should use dedicated hardware.

        Returns:
            bool: True when the preference actually changed, so the caller knows
                whether anything needs reloading.

        Raises:
            ValueError: If the key names no backend.
        """
        if key not in self.BACKEND_KEYS:
            raise ValueError(f"Unknown backend: {key}")

        self._ensure_probed()
        if self._preferences[key] == enabled:
            return False

        self._preferences[key] = enabled
        logger.info(
            f"Acceleration for {key} switched {'on' if enabled else 'off'}"
        )
        return True

    def _backend_states(self) -> List[BackendStatus]:
        """
        The state of each backend, capability and choice kept apart.

        Built in one place because the report and is_active have to agree: if
        they were derived separately the badge could contradict the panel it
        opens.
        """
        torch_supported = self._torch_device != "cpu"
        onnx_supported = "CUDAExecutionProvider" in self._onnx_providers

        detection_on = torch_supported and self._preferences["detection"]
        face_on = onnx_supported and self._preferences["face"]
        landmarks_on = self._mediapipe_gpu and self._preferences["landmarks"]

        return [
            BackendStatus(
                key="detection",
                name="Object detection",
                accelerated=detection_on,
                device=self._torch_device if detection_on else "cpu",
                detail=self._torch_detail,
                supported=torch_supported,
                enabled=self._preferences["detection"],
            ),
            BackendStatus(
                key="face",
                name="Face recognition",
                accelerated=face_on,
                device="cuda" if face_on else "cpu",
                detail=self._onnx_detail,
                supported=onnx_supported,
                enabled=self._preferences["face"],
            ),
            BackendStatus(
                key="landmarks",
                name="Skeleton and mesh",
                accelerated=landmarks_on,
                device="gpu" if landmarks_on else "cpu",
                detail=self._mediapipe_detail,
                supported=self._mediapipe_gpu,
                enabled=self._preferences["landmarks"],
            ),
        ]

    def report(self) -> AccelerationReport:
        """
        Build the status the client shows in its badge.

        Returns:
            AccelerationReport: Device details and the state of each backend.
        """
        self._ensure_probed()

        backends = self._backend_states()

        return AccelerationReport(
            available=self.is_available,
            active=self.is_active,
            device_name=self._device_name,
            device_memory_mb=self._device_memory_mb,
            driver=self._driver,
            compute_capability=self._capability,
            backends=backends,
        )


_acceleration_service: Optional[AccelerationService] = None


def get_acceleration_service() -> AccelerationService:
    """Get the acceleration service singleton."""
    global _acceleration_service
    if _acceleration_service is None:
        _acceleration_service = AccelerationService()
    return _acceleration_service
