from pathlib import Path
from typing import Optional

MODEL_IMAGE_DIR = Path("Images") / "Bluetti_Models"

# Preserve BLUETTI's original CDN format whenever possible.
# WEBP is checked first because many current BLUETTI masters use it.
SUPPORTED_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")


def resolve_model_image(model: str) -> Optional[Path]:
    """
    Resolve the best local image for a BLUETTI model.

    The filename stem must match the backend model identifier exactly,
    for example:
        EL30V2.webp
        AC180.png
        AP300.png

    Falls back to Unknown.<ext> when available.
    """
    if not model:
        return _resolve_fallback()

    safe_model = model.strip()

    for extension in SUPPORTED_EXTENSIONS:
        candidate = MODEL_IMAGE_DIR / f"{safe_model}{extension}"
        if candidate.is_file():
            return candidate

    return _resolve_fallback()


def _resolve_fallback() -> Optional[Path]:
    for extension in SUPPORTED_EXTENSIONS:
        candidate = MODEL_IMAGE_DIR / f"Unknown{extension}"
        if candidate.is_file():
            return candidate
    return None
