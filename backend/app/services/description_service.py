"""
Scene descriptions from a vision language model.

Writes a short paragraph about what the camera is looking at. The detector has
already worked out what is in the frame and who the people are, so that list is
handed to the model as context rather than left for it to rediscover: it fixes
the names, keeps the model from inventing objects that were never there, and
lets the prose refer to "Person 3" by the name the rest of the application uses.

The model still looks at the image. Detections say what is present, not what is
happening, and the whole point of a description is the part a bounding box
cannot express: what someone is doing, how the room is lit, whether the desk is
tidy. So the prompt asks for the scene, with the detection list as a hint, not
for a rendering of the list into sentences.

Everything runs locally on whatever accelerator the machine has. No frame ever
leaves the host.
"""

import threading
import time
from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.acceleration_service import get_acceleration_service

logger = get_logger(__name__)


class DescriptionService:
    """
    Produces a short prose description of a frame.

    The model loads lazily on first use, which keeps a stack that never asks for
    a description from paying several gigabytes of download and VRAM for it, and
    fails soft: when it cannot be loaded the endpoint reports that plainly
    instead of taking detection down with it.
    """

    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._unavailable = False
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._loading = False

    @property
    def available(self) -> bool:
        """Whether a description can be produced."""
        return not self._unavailable

    def describe_status(self) -> dict:
        """Report the state of the model for the status endpoint."""
        return {
            "enabled": settings.description_enabled,
            "available": self.available,
            "loaded": self._model is not None,
            "loading": self._loading,
            "model": settings.description_model,
            "error": self._error,
        }

    def _ensure_loaded(self) -> bool:
        """Load the vision language model on first use."""
        if self._model is not None:
            return True
        if self._unavailable or not settings.description_enabled:
            return False

        with self._lock:
            if self._model is not None:
                return True
            if self._unavailable:
                return False

            self._loading = True
            try:
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor

                name = settings.description_model
                device = get_acceleration_service().torch_device
                logger.info(f"Loading the description model: {name} on {device}")
                started = time.perf_counter()

                self._processor = AutoProcessor.from_pretrained(name)
                self._model = AutoModelForImageTextToText.from_pretrained(
                    name,
                    dtype=torch.float16 if device == "cuda" else torch.float32,
                    device_map=device,
                )
                self._model.eval()

                logger.info(
                    f"Description model ready in {time.perf_counter() - started:.1f}s"
                )
                return True
            except Exception as e:
                self._unavailable = True
                self._error = str(e)
                logger.warning(f"Scene descriptions unavailable: {e}")
                return False
            finally:
                self._loading = False

    def _build_context(self, detections: Sequence[dict]) -> str:
        """
        Turn the detection list into a line the model can lean on.

        Names carry the identity the rest of the application uses, so a person
        already recognised is referred to by their catalog name rather than
        described from scratch as "a man". Uncertain detections are marked as
        such, because a description that states a guess as a fact is worse than
        one that admits it.

        Args:
            detections: Detections for the frame, as returned by the API.

        Returns:
            A single line of context, or an empty string when there is nothing.
        """
        if not detections:
            return ""

        people: List[str] = []
        objects: List[str] = []

        for detection in detections:
            name = detection.get("objectName") or detection.get("label") or ""
            if not name:
                continue

            certainty = detection.get("matchConfidence")
            if certainty is None or not detection.get("objectId"):
                certainty = detection.get("confidence", 0.0)

            entry = name if certainty >= settings.detection_certainty_threshold else f"possibly {name}"

            label = str(detection.get("label", "")).lower()
            if label == "person" or str(name).lower().startswith("person "):
                people.append(entry)
            else:
                objects.append(entry)

        parts = []
        if people:
            parts.append("people present: " + ", ".join(sorted(set(people))))
        if objects:
            parts.append("objects detected: " + ", ".join(sorted(set(objects))))
        return "; ".join(parts)

    def describe(
        self,
        frame: np.ndarray,
        detections: Sequence[dict],
    ) -> Tuple[Optional[str], float]:
        """
        Write a short description of a frame.

        Args:
            frame: Full BGR frame.
            detections: Detections for that frame, used as context.

        Returns:
            Tuple of (description or None, processing milliseconds).
        """
        if not self._ensure_loaded():
            return None, 0.0

        started = time.perf_counter()

        try:
            import cv2
            import torch
            from PIL import Image

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)

            # A description does not need the full sensor resolution, and a
            # smaller image is markedly faster through the vision encoder.
            longest = max(image.size)
            if longest > settings.description_max_side:
                ratio = settings.description_max_side / longest
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                )

            context = self._build_context(detections)
            instruction = settings.description_prompt
            if context:
                instruction = (
                    f"{instruction}\n\n"
                    f"A detector has already identified the following in this frame: "
                    f"{context}. Use those names, do not contradict them, and do not "
                    f"list anything you cannot actually see."
                )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": instruction},
                    ],
                }
            ]

            inputs = self._processor.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=True,
                return_dict=True,
                return_tensors="pt",
            ).to(self._model.device)

            with torch.no_grad():
                # Generation is left uncompiled on purpose. The compiled path
                # goes through Triton, which shells out to a C compiler the
                # runtime image does not carry, and a slim image is worth more
                # here than the speedup on a paragraph of text.
                generate_kwargs = {
                    "max_new_tokens": settings.description_max_tokens,
                    "do_sample": False,
                }
                try:
                    generated = self._model.generate(
                        **inputs, **generate_kwargs, disable_compile=True
                    )
                except TypeError:
                    generated = self._model.generate(**inputs, **generate_kwargs)

            # Only the newly generated tail is the answer; the rest is the prompt
            # echoed back.
            trimmed = generated[:, inputs["input_ids"].shape[1] :]
            text = self._processor.batch_decode(trimmed, skip_special_tokens=True)[0]

            elapsed = (time.perf_counter() - started) * 1000
            return text.strip(), elapsed

        except Exception as e:
            logger.warning(f"Description failed: {e}")
            self._error = str(e)
            return None, (time.perf_counter() - started) * 1000


_description_service: Optional[DescriptionService] = None


def get_description_service() -> DescriptionService:
    """Get the description service singleton."""
    global _description_service
    if _description_service is None:
        _description_service = DescriptionService()
    return _description_service
