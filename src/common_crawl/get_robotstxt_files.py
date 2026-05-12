"""
Download robots.txt files from Common Crawl data.

This script fetches robots.txt files listed in the robotstxt.paths.gz files
for each crawl available since a specified year. It saves the files locally,
mirroring the directory structure from Common Crawl.
"""

import gzip
import logging
import random
import time
from collections.abc import Generator

import fire
import requests
from get_crawls import get_crawls_since

from src.utils import DATA_DIR, create_session, setup_logging

OUT_DIR = DATA_DIR / "common_crawl"
OUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def fetch_paths_for_crawl(crawl_id: str, session: requests.Session) -> Generator[str, None, None]:
    """
    Download and yield each robots.txt from the gz file for a given crawl.
    """
    base_http = f"https://data.commoncrawl.org/crawl-data/{crawl_id}/robotstxt.paths.gz"

    try:
        r = session.get(base_http, timeout=60)
        r.raise_for_status()
        gzdata = r.content
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning(f"Robots.txt paths file not found for {crawl_id} (404). Skipping this crawl.")
            return
        else:
            raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch paths for {crawl_id}: {e}")
        return

    buf = gzip.decompress(gzdata)  # decompress to bytes
    for line in buf.splitlines():
        yield line.decode("utf-8")


def download_file(path: str, session: requests.Session) -> bool:
    """
    Downloads a robots.txt file given its full HTTP URL.
    Saves to OUTPUT_DIR mirroring subdirectory structure.
    """
    http_url = "https://data.commoncrawl.org/" + path
    local_path = OUT_DIR / path
    local_path.parent.mkdir(parents=True, exist_ok=True)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = session.get(http_url, timeout=60)
            resp.raise_for_status()
            local_path.write_bytes(resp.content)
            print(f"Downloaded: {local_path}")
            return True
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = random.uniform(1, 3) * (2**attempt)  # Exponential backoff with jitter
                print(f"Attempt {attempt + 1} failed for {http_url}: {e}. Retrying in {wait_time:.2f}s...")
                time.sleep(wait_time)
            else:
                print(f"Failed to download {http_url} after {max_retries} attempts: {e}")
                return False

    return False


def main(since: str, total_limit: int | None = None, per_crawl_limit: int | None = None) -> None:
    """
    Iterate over all crawls since the given date/year using get_crawls_since
    and download robots.txt files.
    - since: string like '2023-01-01' or '2023' (depending on your helper's API)
    - total_limit: max number of files overall
    - per_crawl_limit: max number of files per crawl
    """
    logger.info(f"Starting download of robots.txt files since {since}")
    total_count = 0
    session = create_session()

    try:
        for crawl in get_crawls_since(int(since)):
            logger.info(f"Processing crawl: {crawl}")
            per_count = 0

            # Fetch paths
            try:
                paths = fetch_paths_for_crawl(crawl, session)
                if paths is None:  # Handle case where crawl is skipped due to 404
                    continue
            except Exception as e:
                logger.error(f"Failed to fetch paths for crawl {crawl}: {e}")
                continue

            for path in paths:
                # Check if file is already downloaded
                local_path = OUT_DIR / path
                if local_path.exists():
                    logger.debug(f"Skipping already downloaded: {local_path}")
                    continue

                # Add small delay between downloads to be respectful
                time.sleep(random.uniform(0.1, 0.5))

                if download_file(path, session):
                    total_count += 1
                    per_count += 1

                if per_crawl_limit and per_count >= per_crawl_limit:
                    logger.info(f"Reached per-crawl limit ({per_crawl_limit}) for {crawl}")
                    break
                if total_limit and total_count >= total_limit:
                    logger.info(f"Downloaded {total_count} robots.txt files (total limit reached).")
                    return

            logger.info(f"Completed crawl {crawl}: downloaded {per_count} files")
    finally:
        session.close()

    logger.info(f"Download complete. Total files downloaded: {total_count}")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
