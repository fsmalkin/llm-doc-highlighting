"""
Download and extract the FUNSD dataset (utilities only; data is git-ignored).

Usage:
  python scripts\\funsd_download.py --dest data\\funsd
"""

from __future__ import annotations

import argparse
import os
import pathlib
import zipfile
from typing import Optional

import requests


DEFAULT_URL = "https://guillaumejaume.github.io/FUNSD/dataset.zip"


def _download(url: str, dest: pathlib.Path, *, force: bool) -> pathlib.Path:
    if dest.exists() and not force:
        print(f"Dataset zip already exists: {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    print(f"Downloaded: {dest}")
    return dest


def _extract(zip_path: pathlib.Path, out_dir: pathlib.Path, *, force: bool) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / ".funsd_extracted"
    if marker.exists() and not force:
        print(f"Dataset already extracted: {out_dir}")
        return out_dir
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)
    marker.write_text("ok", encoding="utf-8")
    print(f"Extracted to: {out_dir}")
    return out_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="Download and extract FUNSD dataset")
    ap.add_argument("--dest", default="data/funsd", help="Destination root (default: data/funsd)")
    ap.add_argument("--url", default=DEFAULT_URL, help="Dataset zip URL")
    ap.add_argument("--no-extract", action="store_true", help="Skip extraction")
    ap.add_argument("--force", action="store_true", help="Re-download/re-extract even if present")
    args = ap.parse_args()

    dest_root = pathlib.Path(args.dest)
    raw_dir = dest_root / "raw"
    zip_path = raw_dir / "dataset.zip"

    _download(args.url, zip_path, force=args.force)
    if not args.no_extract:
        _extract(zip_path, raw_dir, force=args.force)

    print("Done.")


if __name__ == "__main__":
    main()
