import json
import os
from os import PathLike
from pathlib import Path

import fire
import polars as pl
import requests
from dotenv import load_dotenv

from src.utils import get_data_dir, setup_logging

load_dotenv()

DATE = "2025-10-11"
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")


def get_domains_to_fetch(analysis_dir: Path) -> tuple[pl.Series, pl.Series]:
    """Get domains that need to be fetched from Cloudflare API."""
    domain_files_map_path = analysis_dir / "domain_files_map.parquet"
    cloudflare_domain_details_file = analysis_dir / "cloudflare_domain_details.jsonl"

    if not domain_files_map_path.exists():
        raise FileNotFoundError(f"{domain_files_map_path} does not exist. Please run the analysis first.")

    df = pl.read_parquet(domain_files_map_path)

    # Already fetched domains
    existing_domains = (
        pl.read_ndjson(cloudflare_domain_details_file).explode("result").unnest("result").get_column("domain").unique()
        if cloudflare_domain_details_file.exists()
        else pl.Series("domain", [], dtype=pl.Utf8)
    )

    # Filter out already queried domains
    all_domains = (
        df.filter(pl.col("ai_txt") | pl.col("llms_txt") | pl.col("llms_full_txt") | pl.col("robots_txt"))
        .get_column("domain")
        .unique()
    )

    domains_to_fetch = all_domains.filter(~all_domains.is_in(existing_domains.to_list()))

    return all_domains, domains_to_fetch


def fetch_cloudflare_domain_details(analysis_dir: Path, session: requests.Session) -> None:
    """Fetch domain details from Cloudflare API in bulk.

    The Cloudflare API allows fetching details for multiple domains in a single request.
    The API endpoint provides information such as domain categorization.
    """
    # Bulk fetch in batches (API may have limits, adjust batch_size if needed)
    batch_size = 100
    timeout = (30, 300)  # (connect timeout, read timeout) in seconds

    # Cloudflare API endpoint for bulk domain details
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/intel/domain/bulk"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
    }

    cloudflare_domain_details_file = analysis_dir / "cloudflare_domain_details.jsonl"

    try:
        all_domains, domains_to_fetch = get_domains_to_fetch(analysis_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    print(
        f"Total domains: {len(all_domains)}, Already fetched: {len(all_domains) - len(domains_to_fetch)}, To fetch: {len(domains_to_fetch)}"
    )

    # Update session headers
    session.headers.update(headers)

    for i in range(0, len(domains_to_fetch), batch_size):
        batch = domains_to_fetch[i : i + batch_size]

        # Build query string with multiple domain parameters
        params = [("domain", domain) for domain in batch]

        try:
            response = session.get(url, params=params, timeout=timeout)

            if response.status_code != 200:
                print(f"Error fetching batch {i // batch_size + 1}: {response.status_code}")
                print(f"Response content: {response.text}")
                continue

            data = response.json()

            with cloudflare_domain_details_file.open("a") as f:
                f.write(json.dumps(data) + "\n")

            print(f"Fetched batch {i // batch_size + 1}/{(len(domains_to_fetch) + batch_size - 1) // batch_size}")
        except requests.exceptions.Timeout:
            print(f"Timeout fetching batch {i // batch_size + 1}")
        except requests.exceptions.RequestException as e:
            print(f"Error fetching batch {i // batch_size + 1}: {e}")


def fetch_cloudflare_known_bots(analysis_dir: Path, session: requests.Session) -> None:
    """Fetch known bots list from Cloudflare API.

    The Cloudflare API provides a list of known bots that are commonly blocked or allowed
    in robots.txt and ai.txt files.
    """
    url = "https://api.cloudflare.com/client/v4/radar/bots"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
    }
    params = {
        "limit": "1000",
    }

    cloudflare_known_bots_file = analysis_dir / "cloudflare_known_bots.json"

    if cloudflare_known_bots_file.exists():
        print("Known bots file already exists, skipping download.")
        return

    try:
        response = session.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            print(f"Error fetching known bots: {response.status_code}")
            print(f"Response content: {response.text}")
            return

        bots = response.json()["result"]["bots"]

        with cloudflare_known_bots_file.open("w") as f:
            json.dump(bots, f)

        print(f"Fetched {len(bots)} known bots")
    except requests.exceptions.Timeout:
        print("Timeout fetching known bots")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching known bots: {e}")


def main(date: str | None = None, data_dir: PathLike | None = None, force: bool = False) -> None:
    _, base_dir = get_data_dir(date, data_dir)
    analysis_dir = base_dir / "analysis"

    with requests.Session() as session:
        fetch_cloudflare_known_bots(analysis_dir, session)
        fetch_cloudflare_domain_details(analysis_dir, session)


if __name__ == "__main__":
    setup_logging()
    fire.Fire(main)
