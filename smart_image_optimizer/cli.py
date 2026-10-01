"""Command-line interface for safe, metadata-free WebP conversion."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class Result:
    source: Path
    destination: Path | None
    original_bytes: int
    output_bytes: int
    error: str | None = None


def image_files(source: Path, recursive: bool, excluded: Path | None) -> list[Path]:
    candidates = [source] if source.is_file() else list(source.rglob("*") if recursive else source.iterdir())
    files = []
    for item in candidates:
        if not item.is_file() or item.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if excluded and item.resolve().is_relative_to(excluded.resolve()):
            continue
        files.append(item)
    return sorted(files)


def convert(
    source: Path,
    destination: Path,
    max_width: int,
    max_height: int,
    quality: int,
    overwrite: bool,
) -> Result:
    original_bytes = source.stat().st_size
    try:
        with Image.open(source) as opened:
            if getattr(opened, "n_frames", 1) > 1:
                return Result(source, None, original_bytes, 0, "animated images are skipped")
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            # Pillow may keep EXIF, XMP, or ICC metadata in Image.info.
            # Clear it before encoding so source metadata is not copied.
            image.info.clear()

            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not overwrite:
                return Result(source, None, original_bytes, 0, "output exists; use --overwrite")

            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=quality, method=6)
            temporary = destination.with_name(destination.name + ".tmp")
            temporary.write_bytes(buffer.getvalue())
            temporary.replace(destination)
            return Result(source, destination, original_bytes, destination.stat().st_size)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return Result(source, None, original_bytes, 0, str(exc))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="smart-image-optimizer",
        description="Resize images, convert to WebP, and omit source metadata.",
    )
    result.add_argument("source", type=Path, help="An image file or a directory")
    result.add_argument("-o", "--output", type=Path, required=True, help="Output directory")
    result.add_argument("--max-width", type=int, default=1920)
    result.add_argument("--max-height", type=int, default=1920)
    result.add_argument("--quality", type=int, default=82, help="WebP quality from 1 to 100")
    result.add_argument("--recursive", action="store_true", help="Include nested directories")
    result.add_argument("--overwrite", action="store_true", help="Replace existing WebP outputs")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.max_width < 1 or args.max_height < 1:
        raise SystemExit("Maximum dimensions must be positive integers.")
    if not 1 <= args.quality <= 100:
        raise SystemExit("Quality must be between 1 and 100.")
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Input does not exist: {source}")
    if not source.is_file() and not source.is_dir():
        raise SystemExit("Input must be a file or directory.")

    candidates = image_files(source, args.recursive, output if source.is_dir() else None)
    if not candidates:
        print("No supported images found.")
        return 0

    results = []
    for item in candidates:
        if source.is_file():
            destination = output / f"{source.stem}.webp"
        else:
            relative = item.relative_to(source)
            destination = output / relative.parent / f"{item.stem}.webp"
        results.append(
            convert(item, destination, args.max_width, args.max_height, args.quality, args.overwrite)
        )

    before = sum(item.original_bytes for item in results)
    after = sum(item.output_bytes for item in results if item.destination)
    for item in results:
        if item.destination:
            delta = (1 - item.output_bytes / item.original_bytes) * 100 if item.original_bytes else 0
            print(f"OK  {item.source.name} -> {item.destination.name}  ({delta:+.1f}%)")
        else:
            print(f"SKIP {item.source.name}: {item.error}")
    converted = sum(item.destination is not None for item in results)
    reduction = (1 - after / before) * 100 if before else 0
    print(
        f"\nConverted {converted}/{len(results)} image(s) | "
        f"{before / 1024:.1f} KB -> {after / 1024:.1f} KB | total change {reduction:+.1f}%"
    )
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(main())
