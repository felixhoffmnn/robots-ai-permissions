"""
Fetch and filter Common Crawl collections from `collinfo.json`.

This module provides functionality to retrieve a list of Common Crawl
collections (crawls) from the `collinfo.json` endpoint and filter them
based on a specified year threshold.

It does not download any files; it only lists the available crawls
that meet the criteria.
"""

import logging

import fire
import requests

from src.utils import create_session, setup_logging

logger = logging.getLogger(__name__)


def get_crawls_since(year_threshold: int = 2016) -> list[str]:
    """
    Fetches Common Crawl collections from collinfo.json and returns a list
    of crawl IDs whose year is >= year_threshold.
    """
    logger.info(f"Fetching Common Crawl collections since {year_threshold}")
    url = "https://index.commoncrawl.org/collinfo.json"
    session = create_session()

    try:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        collections = response.json()
        logger.info(f"Retrieved {len(collections)} total collections from Common Crawl")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch collections from {url}: {e}")
        raise

    filtered = []
    skipped_count = 0
    for coll in collections:
        crawl_id = coll.get("id") or coll.get("name")
        if not crawl_id:
            logger.warning(f"Skipping collection with missing id/name: {coll}")
            skipped_count += 1
            continue
        # Expecting format "CC-MAIN-YYYY-NN"
        parts = crawl_id.split("-")
        # Defensive check: ensure format is as expected
        if len(parts) >= 3 and parts[0] == "CC" and parts[1] == "MAIN":
            try:
                year = int(parts[2])
            except ValueError:
                logger.warning(f"Unable to parse year from crawl ID: {crawl_id}")
                skipped_count += 1
                continue
            if year >= year_threshold:
                filtered.append(crawl_id)
            else:
                logger.debug(f"Skipping crawl {crawl_id} (year {year} < {year_threshold})")
        else:
            logger.warning(f"Unexpected crawl ID format: {crawl_id}")
            skipped_count += 1

    # Sort chronologically
    filtered.sort(key=lambda cid: tuple(map(int, cid.split("-")[2:])))

    logger.info(f"Filtered to {len(filtered)} crawls since {year_threshold} (skipped {skipped_count})")
    if filtered:
        logger.debug(f"First crawl: {filtered[0]}, Last crawl: {filtered[-1]}")

    return filtered


if __name__ == "__main__":
    setup_logging()

    fire.Fire(get_crawls_since)
