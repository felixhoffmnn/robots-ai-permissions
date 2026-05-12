"""
Tranco-only domain list builder with PLD extraction & merge-sort + splitting.

Usage:
    ./01-fetch.py [--force]

Produces under txt_downloads/YYYY-MM-DD/:
  domains_sorted.txt    merged sorted+unique PLDs
  splits/               split_00000.txt, split_00001.txt, … (10k lines each)
"""

import csv
import logging
import shutil
from datetime import UTC
from datetime import datetime as dt
from pathlib import Path

import fire
import requests
from publicsuffix2 import get_sld
from src.utils import get_data_dir, setup_logging

UA = "zrdz/0.4"
SPLIT_SIZE = 10_000

logger = logging.getLogger(__name__)


def fetch_to(url: str, dest: Path, headers: dict[str, str] | None = None) -> Path:
    """Download url to dest if not already present."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers={"User-Agent": UA, **(headers or {})}, stream=True, timeout=90) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest


def download_tranco(download_dir: Path) -> set[str]:
    """Fetch Tranco Top 1M zip, unpack CSV, and extract PLDs."""
    download_dir.mkdir(parents=True, exist_ok=True)
    download_path = download_dir / "tranco.csv"

    logger.info("Downloading Tranco list")
    fetch_to("https://tranco-list.eu/download/PLW5J/full", download_path)

    plds: set[str] = set()
    logger.info("Parsing domains")

    # Assume it's a plain CSV file
    logger.info("CSV format detected")
    with download_path.open(encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for _, dom in reader:
            pld = get_sld(dom.lower())
            if pld:
                plds.add(pld)

    return plds


def write_sorted(plds: set[str], base_dir: Path) -> Path:
    """Write sorted unique PLDs to domains_sorted.txt."""
    out = base_dir / "domains_sorted.txt"
    base_dir.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for d in sorted(plds):
            fh.write(d + "\n")
    return out


def split_file(sorted_file: Path, splits_dir: Path) -> None:
    """Split the sorted file into chunks of SPLIT_SIZE lines."""
    splits_dir.mkdir(parents=True, exist_ok=True)
    with sorted_file.open(encoding="utf-8") as fh:
        idx = 0
        while True:
            lines = [fh.readline() for _ in range(SPLIT_SIZE)]
            lines = [line for line in lines if line]
            if not lines:
                break
            part = splits_dir / f"split_{idx:05d}.txt"
            with part.open("w", encoding="utf-8") as out:
                out.writelines(lines)
            idx += 1


def main(force: bool = False) -> None:
    _, base_dir = get_data_dir()
    splits_dir = base_dir / "splits"
    download_dir = base_dir / "download"

    # Skip if already done
    if splits_dir.exists() and any(splits_dir.iterdir()) and not force:
        logger.info("Splits exist, skipping")
        return
    if force and base_dir.exists():
        shutil.rmtree(base_dir)

    # Prepare directories
    download_dir.mkdir(parents=True, exist_ok=True)
    start = dt.now(UTC)
    logger.info(f"Starting download to {base_dir}")

    # download & collect PLDs from Tranco zip
    plds = download_tranco(download_dir)

    # write sorted unique PLDs
    logger.info("Writing sorted PLDs")
    sorted_file = write_sorted(plds, base_dir)

    # split into chunks
    logger.info("Splitting into files of up to 10k lines")
    split_file(sorted_file, splits_dir)
    sorted_file.unlink()  # remove the merged file

    dur = (dt.now(UTC) - start).total_seconds()
    logger.info(f"Done in {dur:.1f}s")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
