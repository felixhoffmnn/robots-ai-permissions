"""
Process each split_NNNNN.txt:

  • Copy split file into txt_downloads/YYYY-MM-DD/
  • Create folder txt_downloads/YYYY-MM-DD/split_NNNNN/
  • In that folder, per-domain subfolders with robots.txt, ai.txt, llms.txt

Usage:
    ./process_splits.py [--force]
"""

import logging
import multiprocessing
import shutil
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from email.errors import MessageDefect
from pathlib import Path

import fire
import requests
from src.utils import get_data_dir, setup_logging

DOMAINS_PER_SPLIT = 10_000
THREADS_PER_WORKER = 32
TIMEOUT = 5  # seconds per HTTP GET

logger = logging.getLogger(__name__)


def domain_reachable(domain: str) -> tuple[bool, str | None]:
    """
    Quick HEAD request to test if domain is reachable.
    Returns (reachable: bool, protocol: str | None)
    """
    for proto in ("https", "http"):
        try:
            resp = requests.head(f"{proto}://{domain}", timeout=TIMEOUT, allow_redirects=True)
            if 200 <= resp.status_code < 400:
                return True, proto
        except Exception:
            continue
    return False, None


def get_files(domain: str, split_dir: Path) -> None:
    """
    Fetch robots.txt, ai.txt, llms.txt, llms-full.txt for a domain.
    First checks if domain is reachable, then attempts downloads.
    """
    # Check if domain is reachable first
    reachable, preferred_proto = domain_reachable(domain)

    if not reachable:
        logger.debug(f"Domain {domain} is not reachable, skipping")
        return

    logger.debug(f"Domain {domain} is reachable via {preferred_proto}")

    # Create destination folder for this domain
    dest = split_dir / domain
    dest.mkdir(exist_ok=True, parents=True)

    # Collect successful downloads
    downloads: dict[str, str] = {}

    # Try preferred protocol first, then fallback
    protocols = [preferred_proto, "http" if preferred_proto == "https" else "https"]

    for name in ("robots.txt", "ai.txt", "llms.txt", "llms-full.txt"):
        found = False
        for proto in protocols:
            url = f"{proto}://{domain}/{name}"
            try:
                resp = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
                if resp.status_code == 200 and resp.text:
                    downloads[name] = resp.text
                    logger.debug(f"Successfully downloaded {name} from {proto}://{domain}")
                    found = True
                    break
            except (requests.exceptions.RequestException, MessageDefect) as e:
                logger.debug(f"Failed to get {name} from {proto}://{domain}: {e}")
                continue
            except Exception as e:
                logger.debug(f"Failed to get {name} from {proto}://{domain}: {e}")
                continue

        if not found:
            logger.debug(f"{name} not found for {domain}")

    # Write files if we have successful downloads
    if downloads:
        for name, content in downloads.items():
            (dest / name).write_text(content, encoding="utf-8")

        logger.debug(f"Saved {len(downloads)} files for {domain}")
    else:
        logger.debug(f"No files found for {domain}")


def process_split(split_path: Path, date_folder: Path, force: bool) -> None:
    split_name = split_path.stem  # e.g. "split_00000"
    split_dir = date_folder / "files" / split_name

    logger.info(f"Processing {split_name}…")

    try:
        if split_dir.exists() and not force:
            logger.info(f"SKIP {split_name} (already exists)")
            return

        if force and split_dir.exists():
            shutil.rmtree(split_dir)

        split_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(split_path, split_dir.parent)

        domains = [d.strip() for d in split_path.read_text(encoding="utf-8").splitlines() if d.strip()]

        logger.info(f"{split_name}: fetching {len(domains)} domains with {THREADS_PER_WORKER} threads…")

        # Process domains with progress tracking per split
        with ThreadPoolExecutor(max_workers=THREADS_PER_WORKER) as pool:
            pool.map(lambda d: get_files(d, split_dir), domains)

        logger.info(f"{split_name} done")

    except Exception as e:
        logger.error(f"Error processing {split_name}: {e}")
        logger.error(traceback.format_exc())


def main(
    date: str | None = None,
    force: bool = False,
    skip_until: int | None = None,
    workers: int | None = None,
    only_splits: str | None = None,
) -> None:
    _, base_dir = get_data_dir(date)
    splits_dir = base_dir / "splits"

    splits = sorted(splits_dir.glob("split_*.txt"))
    if not splits:
        logger.error(f"No split_*.txt found in {splits_dir}")
        sys.exit(1)

    # Filter splits based on only_splits parameter
    if only_splits is not None:
        requested_splits = {s.strip() for s in only_splits.split(",") if s.strip()}
        splits = [s for s in splits if s.stem in requested_splits]
        print(", ".join(sorted(requested_splits)))
        logger.info(f"Filtering to only process specified splits: {', '.join(sorted(requested_splits))}")

        if not splits:
            logger.error(f"None of the requested splits found in {splits_dir}")
            sys.exit(1)

    # Filter splits based on skip_until parameter
    if skip_until is not None:
        splits = [s for s in splits if int(s.stem.split("_")[1]) >= skip_until]
        logger.info(f"Skipping splits until split_{skip_until:05d}, processing {len(splits)} splits")

    # Determine worker count
    ctx = multiprocessing.get_context("fork")
    worker_count = workers if workers is not None else min(len(splits), ctx.cpu_count())
    logger.info(f"Processing {len(splits)} splits with {worker_count} workers")

    # Process splits in parallel
    with ctx.Pool(processes=worker_count) as pool:
        pool.starmap(process_split, [(split, base_dir, force) for split in splits])


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
