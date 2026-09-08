from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from PySide6.QtGui import QImageReader
except ImportError:
    QImageReader = None


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).with_name("model_image_manifest.json")
OUTPUT_DIR = ROOT / "Images" / "Bluetti_Models"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_dimensions(path: Path) -> str:
    if QImageReader is None:
        return "unknown"

    reader = QImageReader(str(path))
    size = reader.size()

    if not size.isValid():
        return "unknown"

    return f"{size.width()}x{size.height()}"


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/150 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.8",
        },
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read()

    if len(data) < 1024:
        raise RuntimeError(f"Downloaded file is unexpectedly small ({len(data)} bytes)")

    destination.write_bytes(data)


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assets = manifest.get("assets", [])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"BLUETTI model-image downloader — manifest v{manifest.get('version', '?')}")
    print(f"Destination: {OUTPUT_DIR}")
    print()

    failures = 0
    records = []

    for asset in assets:
        model = asset["model"]
        filename = asset["filename"]
        url = asset["url"]
        destination = OUTPUT_DIR / filename

        print(f"[{model}] {filename}")

        try:
            download(url, destination)
            digest = sha256_file(destination)
            dimensions = image_dimensions(destination)
            size_bytes = destination.stat().st_size

            print(f"  OK  {dimensions}  {size_bytes:,} bytes")
            print(f"  SHA256 {digest}")

            records.append(
                {
                    "model": model,
                    "filename": filename,
                    "dimensions": dimensions,
                    "bytes": size_bytes,
                    "sha256": digest,
                    "source_url": url,
                }
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            failures += 1
            print(f"  FAILED: {exc}")

        print()

    report_path = OUTPUT_DIR / "download_report.json"
    report_path.write_text(
        json.dumps(records, indent=2),
        encoding="utf-8",
    )

    unresolved = manifest.get("unresolved_models", [])
    print(f"Downloaded: {len(records)}")
    print(f"Failed:     {failures}")
    print(f"Unresolved models intentionally omitted: {len(unresolved)}")

    if unresolved:
        print("  " + ", ".join(unresolved))

    print()
    print(f"Report: {report_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
