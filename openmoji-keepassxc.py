#!/usr/bin/env python3
"""
Download latest OpenMoji release, then create KeePassXC-friendly SVGs.

Usage:
  python3 openmoji_keepassxc.py --download-latest --crop 4
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_REPO = "hfg-gmuend/openmoji"

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

    changed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal changed

        prefix = match.group(1)
        quote = match.group(2)
        old_viewbox = match.group(3)

        x, y, width, height = parse_viewbox(old_viewbox)

        new_x = x + crop
        new_y = y + crop
        new_width = width - (2 * crop)
        new_height = height - (2 * crop)

        if new_width <= 0 or new_height <= 0:
            raise ValueError(f"crop={crop} is too large for viewBox={old_viewbox!r}")

        new_viewbox = " ".join(
            fmt_num(v) for v in (new_x, new_y, new_width, new_height)
        )

        changed = True
        return f"{prefix}{quote}{new_viewbox}{quote}"

    new_text, count = SVG_VIEWBOX_RE.subn(replace, svg_text, count=1)
    return new_text, changed and count == 1


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

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    used_names: set[str] = set()
    written = 0
    missing_svg = 0
    missing_metadata = 0
    viewbox_warnings = 0

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
            svg_text, changed = crop_viewbox(svg_text, crop)

            if crop != 0 and not changed:
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

    if dry_run:
        print("dry run only: no files written")
    else:
        print(f"output: {out_dir}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download, rename, and viewBox-crop OpenMoji SVGs for KeePassXC."
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
            "Amount to crop from each side of the SVG viewBox. "
            "Use 4 first; try 5 or 6 for stronger zoom. Default: 4"
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
