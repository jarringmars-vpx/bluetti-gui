from pathlib import Path

def resolve_model_image(model_name: str) -> Path | None:
    """
    Resolve Images/Bluetti_Models/<exact model name>.png.

    Example:
        EL30V2 -> Images/Bluetti_Models/EL30V2.png

    If the exact image is missing, Unknown.png is used when present.
    """
    project_root = Path(__file__).resolve().parents[1]
    image_dir = project_root / "Images" / "Bluetti_Models"

    exact = image_dir / f"{model_name}.png"
    if exact.exists():
        return exact

    fallback = image_dir / "Unknown.png"
    if fallback.exists():
        return fallback

    return None
