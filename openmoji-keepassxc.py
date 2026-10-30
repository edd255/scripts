#!/usr/bin/env python3
"""
Download the latest OpenMoji release, then create KeePassXC-friendly SVGs.

Usage:
  python3 -m pip install -r requirements.txt
  python3 openmoji-keepassxc.py --download-latest
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

DEFAULT_REPO = "hfg-gmuend/openmoji"
DEFAULT_CONTENT_FILL = 0.9
DEFAULT_MIN_VIEWBOX_SIZE = 48.0
FIT_RENDER_SIZE = 288

SVG_VIEWBOX_RE = re.compile(
    r'(<svg\b[^>]*?\sviewBox\s*=\s*)(["\'])([^"\']+)(\2)',
    re.IGNORECASE | re.DOTALL,
)


def slugify(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "unnamed"


def fmt_num(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def parse_viewbox(value: str) -> tuple[float, float, float, float]:
    parts = re.split(r"[\s,]+", value.strip())
    if len(parts) != 4:
        raise ValueError(f"unsupported viewBox format: {value!r}")

    try:
        x, y, width, height = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError(f"non-numeric viewBox: {value!r}") from exc

    return x, y, width, height


def set_viewbox(
    svg_text: str, viewbox: tuple[float, float, float, float]
) -> tuple[str, bool]:
    new_viewbox = " ".join(fmt_num(value) for value in viewbox)

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        quote = match.group(2)
        return f"{prefix}{quote}{new_viewbox}{quote}"

    new_text, count = SVG_VIEWBOX_RE.subn(replace, svg_text, count=1)
    return new_text, count == 1


def require_fit_dependencies() -> tuple[Any, Any]:
    try:
        import cairosvg
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "content fitting requires CairoSVG and Pillow; "
            "run: python3 -m pip install -r requirements.txt"
        ) from exc

    return cairosvg, Image


def validate_fit_options(content_fill: float, min_viewbox_size: float) -> None:
    if not math.isfinite(content_fill) or not 0 < content_fill <= 1:
        raise ValueError("content_fill must be greater than 0 and at most 1")
    if not math.isfinite(min_viewbox_size) or min_viewbox_size <= 0:
        raise ValueError("min_viewbox_size must be greater than 0")


def fit_viewbox(
    svg_text: str,
    content_fill: float = DEFAULT_CONTENT_FILL,
    min_viewbox_size: float = DEFAULT_MIN_VIEWBOX_SIZE,
    render_size: int = FIT_RENDER_SIZE,
) -> tuple[str, bool]:
    """
    Fit a square viewBox around the rendered, non-transparent content.

    The longest painted dimension occupies ``content_fill`` of the resulting
    square. ``min_viewbox_size`` caps enlargement of intentionally small
    symbols. The result never exceeds the source viewBox's longest dimension.
    """

    validate_fit_options(content_fill, min_viewbox_size)
    if render_size <= 0:
        raise ValueError("render_size must be greater than 0")

    match = SVG_VIEWBOX_RE.search(svg_text)
    if match is None:
        raise ValueError("SVG has no viewBox")

    x, y, width, height = parse_viewbox(match.group(3))
    if width <= 0 or height <= 0:
        raise ValueError(f"viewBox dimensions must be positive: {match.group(3)!r}")
    if not math.isclose(width, height):
        raise ValueError("content fitting requires a square source viewBox")

    scale = render_size / max(width, height)
    render_width = max(1, round(width * scale))
    render_height = max(1, round(height * scale))

    cairosvg, Image = require_fit_dependencies()
    png = cairosvg.svg2png(
        bytestring=svg_text.encode("utf-8"),
        output_width=render_width,
        output_height=render_height,
    )

    with Image.open(BytesIO(png)) as image:
        alpha_bbox = image.convert("RGBA").getchannel("A").getbbox()

    if alpha_bbox is None:
        raise ValueError("rendered SVG is fully transparent")

    left, top, right, bottom = alpha_bbox
    content_left = x + (left * width / render_width)
    content_top = y + (top * height / render_height)
    content_right = x + (right * width / render_width)
    content_bottom = y + (bottom * height / render_height)

    content_width = content_right - content_left
    content_height = content_bottom - content_top
    source_side = max(width, height)
    fitted_side = max(content_width, content_height) / content_fill
    side = min(source_side, max(min_viewbox_size, fitted_side))

    center_x = (content_left + content_right) / 2
    center_y = (content_top + content_bottom) / 2
    fitted_x = min(max(center_x - (side / 2), x), x + width - side)
    fitted_y = min(max(center_y - (side / 2), y), y + height - side)
    fitted_viewbox = (
        fitted_x,
        fitted_y,
        side,
        side,
    )

    return set_viewbox(svg_text, fitted_viewbox)


def crop_viewbox(svg_text: str, crop: float) -> tuple[str, bool]:
    """
    Return (new_svg_text, changed).

    Example:
      viewBox="0 0 72 72" with crop=4 becomes viewBox="4 4 64 64"

    This preserves all paths, fills, strokes, colors, masks, and groups.
    It only changes the visible coordinate window.
    """

    if crop == 0:
        return svg_text, False

    match = SVG_VIEWBOX_RE.search(svg_text)
    if match is None:
        return svg_text, False

    old_viewbox = match.group(3)
    x, y, width, height = parse_viewbox(old_viewbox)
    new_width = width - (2 * crop)
    new_height = height - (2 * crop)

    if new_width <= 0 or new_height <= 0:
        raise ValueError(f"crop={crop} is too large for viewBox={old_viewbox!r}")

    return set_viewbox(
        svg_text,
        (x + crop, y + crop, new_width, new_height),
    )


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "openmoji-keepassxc-script",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "openmoji-keepassxc-script",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        with destination.open("wb") as out:
            shutil.copyfileobj(response, out)


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    """
    Extract ZIP while preventing path traversal.
    """

    destination = destination.resolve()

    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if (
                not str(target).startswith(str(destination) + "/")
                and target != destination
            ):
                raise ValueError(f"unsafe path in ZIP archive: {member.filename}")
        archive.extractall(destination)


def find_extracted_repo_root(extract_dir: Path) -> Path:
    candidates = [
        path
        for path in extract_dir.iterdir()
        if path.is_dir() and (path / "data" / "openmoji.json").is_file()
    ]

    if len(candidates) == 1:
        return candidates[0]

    direct = extract_dir
    if (direct / "data" / "openmoji.json").is_file():
        return direct

    raise FileNotFoundError(
        f"could not find extracted OpenMoji repo root under {extract_dir}"
    )


def download_latest_release(repo: str, download_dir: Path, force: bool) -> Path:
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    print(f"fetching latest release metadata: {repo}")
    metadata = request_json(api_url)

    tag_name = metadata.get("tag_name")
    zipball_url = metadata.get("zipball_url")
    html_url = metadata.get("html_url")

    if not isinstance(tag_name, str) or not tag_name:
        raise ValueError("latest release metadata did not include tag_name")

    if not isinstance(zipball_url, str) or not zipball_url:
        raise ValueError("latest release metadata did not include zipball_url")

    final_dir = download_dir / f"{repo.replace('/', '-')}-{tag_name}"

    if final_dir.exists() and not force:
        print(f"using existing downloaded release: {final_dir}")
        return final_dir

    if final_dir.exists() and force:
        shutil.rmtree(final_dir)

    download_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="openmoji-release-") as tmp_name:
        tmp_dir = Path(tmp_name)
        zip_path = tmp_dir / "openmoji-release.zip"
        extract_dir = tmp_dir / "extract"

        print(f"latest release: {tag_name}")
        if html_url:
            print(f"release page: {html_url}")

        print("downloading source archive")
        download_file(zipball_url, zip_path)

        print("extracting")
        extract_dir.mkdir(parents=True, exist_ok=True)
        safe_extract_zip(zip_path, extract_dir)

        repo_root = find_extracted_repo_root(extract_dir)
        shutil.copytree(repo_root, final_dir)

    print(f"downloaded release to: {final_dir}")
    return final_dir


def load_openmoji_items(metadata_path: Path) -> list[dict[str, Any]]:
    data = json.loads(metadata_path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        for key in ("emojis", "data", "openmoji"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    raise ValueError(f"could not find emoji list in {metadata_path}")


def unique_name(base: str, used: set[str]) -> str:
    candidate = base
    index = 2

    while candidate in used:
        candidate = f"{base}--{index}"
        index += 1

    used.add(candidate)
    return candidate


def process_openmoji(
    svg_dir: Path,
    metadata_path: Path,
    out_dir: Path,
    crop: float,
    fit_content: bool,
    content_fill: float,
    min_viewbox_size: float,
    include_hex: bool,
    dry_run: bool,
    limit: int,
) -> int:
    if not svg_dir.is_dir():
        print(f"error: SVG directory not found: {svg_dir}", file=sys.stderr)
        return 2

    if not metadata_path.is_file():
        print(f"error: metadata file not found: {metadata_path}", file=sys.stderr)
        return 2

    try:
        items = load_openmoji_items(metadata_path)
    except Exception as exc:
        print(f"error: failed to read metadata: {exc}", file=sys.stderr)
        return 2

    if fit_content:
        try:
            validate_fit_options(content_fill, min_viewbox_size)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        try:
            require_fit_dependencies()
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    written = 0
    missing_svg = 0
    missing_metadata = 0
    viewbox_warnings = 0
    fit_fallbacks = 0

    for item in items:
        hexcode = item.get("hexcode")
        annotation = item.get("annotation")

        if not isinstance(hexcode, str) or not isinstance(annotation, str):
            missing_metadata += 1
            continue

        src = svg_dir / f"{hexcode}.svg"
        if not src.is_file():
            missing_svg += 1
            continue

        base = slugify(annotation)
        if include_hex:
            base = f"{base}--{hexcode}"

        base = unique_name(base, used_names)
        dst = out_dir / f"{base}.svg"

        try:
            svg_text = src.read_text(encoding="utf-8")
            if fit_content:
                try:
                    svg_text, changed = fit_viewbox(
                        svg_text,
                        content_fill=content_fill,
                        min_viewbox_size=min_viewbox_size,
                    )
                except Exception as exc:
                    fit_fallbacks += 1
                    print(
                        f"warning: content fit failed for {src}; "
                        f"using crop={crop}: {exc}",
                        file=sys.stderr,
                    )
                    svg_text, changed = crop_viewbox(svg_text, crop)
            else:
                svg_text, changed = crop_viewbox(svg_text, crop)

            if not changed and (fit_content or crop != 0):
                viewbox_warnings += 1
                print(f"warning: no viewBox changed: {src}", file=sys.stderr)

        except Exception as exc:
            viewbox_warnings += 1
            print(f"warning: keeping unmodified SVG for {src}: {exc}", file=sys.stderr)
            svg_text = src.read_text(encoding="utf-8")

        if dry_run:
            print(f"{src.name} -> {dst.name}")
        else:
            dst.write_text(svg_text, encoding="utf-8")

        written += 1

        if limit and written >= limit:
            break

    print(f"written: {written}")
    print(f"missing SVGs skipped: {missing_svg}")
    print(f"metadata rows skipped: {missing_metadata}")
    print(f"viewBox warnings: {viewbox_warnings}")
    if fit_content:
        print(f"content-fit fallbacks: {fit_fallbacks}")

    if dry_run:
        print("dry run only: no files written")
    else:
        print(f"output: {out_dir}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download, rename, and content-fit OpenMoji SVGs for KeePassXC."
    )

    parser.add_argument(
        "--download-latest",
        action="store_true",
        help="Download the latest OpenMoji release from GitHub before processing.",
    )

    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repo to download from. Default: {DEFAULT_REPO}",
    )

    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("./openmoji-downloads"),
        help="Directory for downloaded release sources. Default: ./openmoji-downloads",
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Redownload and replace an existing downloaded release directory.",
    )

    parser.add_argument(
        "--openmoji-dir",
        type=Path,
        default=Path("./openmoji"),
        help=(
            "Path to an existing OpenMoji repo/root directory. "
            "Ignored when --download-latest is used. Default: ./openmoji"
        ),
    )

    parser.add_argument(
        "--svg-dir",
        type=Path,
        default=None,
        help="Path to OpenMoji color SVG directory. Overrides openmoji-dir/color/svg.",
    )

    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Path to openmoji.json. Overrides openmoji-dir/data/openmoji.json.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=Path("./openmoji-keepassxc-svg"),
        help="Output directory. Default: ./openmoji-keepassxc-svg",
    )

    parser.add_argument(
        "--crop",
        type=float,
        default=4.0,
        help=(
            "Fixed crop and content-fit fallback, in SVG units per side. "
            "Used directly with --fixed-crop. Default: 4"
        ),
    )

    parser.add_argument(
        "--fixed-crop",
        action="store_true",
        help="Disable content-aware fitting and apply --crop uniformly.",
    )

    parser.add_argument(
        "--content-fill",
        type=float,
        default=DEFAULT_CONTENT_FILL,
        help=(
            "Fraction of the fitted square occupied by the artwork's longest "
            f"painted dimension. Default: {DEFAULT_CONTENT_FILL}"
        ),
    )

    parser.add_argument(
        "--min-viewbox-size",
        type=float,
        default=DEFAULT_MIN_VIEWBOX_SIZE,
        help=(
            "Smallest automatic square viewBox, limiting enlargement of "
            f"intentionally small symbols. Default: {DEFAULT_MIN_VIEWBOX_SIZE:g}"
        ),
    )

    parser.add_argument(
        "--include-hex",
        action="store_true",
        help="Use filenames like envelope--2709.svg instead of envelope.svg.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without creating files.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N matching icons. Useful for testing.",
    )

    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    try:
        if args.download_latest:
            openmoji_dir = download_latest_release(
                repo=args.repo,
                download_dir=args.download_dir,
                force=args.force_download,
            )
        else:
            openmoji_dir = args.openmoji_dir

        svg_dir = args.svg_dir or (openmoji_dir / "color" / "svg")
        metadata_path = args.metadata or (openmoji_dir / "data" / "openmoji.json")

        return process_openmoji(
            svg_dir=svg_dir,
            metadata_path=metadata_path,
            out_dir=args.out,
            crop=args.crop,
            fit_content=not args.fixed_crop,
            content_fill=args.content_fill,
            min_viewbox_size=args.min_viewbox_size,
            include_hex=args.include_hex,
            dry_run=args.dry_run,
            limit=args.limit,
        )

    except urllib.error.HTTPError as exc:
        print(f"error: HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"error: network failure: {exc.reason}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
