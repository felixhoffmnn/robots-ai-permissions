import json
import logging
import re
import subprocess
import sys
from datetime import UTC
from datetime import datetime as dt
from os import PathLike
from pathlib import Path
from typing import TypedDict

import polars as pl
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

DEFAULT_KNOWN_BOTS = [
    "Amazonbot",
    "anthropic-ai",
    "Applebot",
    "Bytespider",
    "CCBot",
    "ChatGPT-User",
    "Claude-Web",
    "ClaudeBot",
    "Google-Extended",
    "GPTBot",
    "OAI-SearchBot",
    "PerplexityBot",
]


def load_known_bots(*paths: PathLike | None) -> list[str]:
    """Load known bot user-agent patterns from Cloudflare metadata if available."""
    candidates = [Path(path) for path in paths if path is not None]
    candidates.extend(
        [
            DATA_DIR / "cloudflare_known_bots.json",
            DATA_DIR / "2025-10-11" / "analysis" / "cloudflare_known_bots.json",
        ]
    )

    for path in candidates:
        if not path.exists():
            continue
        try:
            patterns = (
                pl.read_json(path)
                .get_column("userAgentPatterns")
                .explode()
                .drop_nulls()
                .unique()
                .to_list()
            )
            patterns = [pattern for pattern in patterns if pattern]
            return sorted(set(patterns) | set(DEFAULT_KNOWN_BOTS))
        except Exception as exc:
            logger.warning(f"Could not load known bots from {path}: {exc}")

    return DEFAULT_KNOWN_BOTS


KNOWN_BOTS = load_known_bots()


class UserAgentRules(TypedDict):
    allow: list[str]
    disallow: list[str]


class DomainPermissions(TypedDict):
    robots: dict[str, UserAgentRules]
    ai: dict[str, UserAgentRules]


PermissionsMap = dict[str, DomainPermissions]


def setup_logging(base_dir: Path = BASE_DIR, prefix: str = "script") -> None:
    """Configure logging to both file and console."""
    log_dir = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{prefix}_{dt.now(UTC).strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def get_data_dir(date: str | None = None, override_dir: PathLike | None = None) -> tuple[str, Path]:
    """Get data paths for a given date (default: today)."""
    if date is None:
        date = dt.now(UTC).strftime("%Y-%m-%d")

    if override_dir is not None:
        base_dir = Path(override_dir) / date
        return date, base_dir

    base_dir = DATA_DIR / date

    return date, base_dir


def find_latest_date_folder(txt_root: PathLike) -> Path:
    """Return the most recent subdirectory named YYYY-MM-DD under txt_root."""
    date_dirs = [d for d in Path(txt_root).iterdir() if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", d.name)]
    if not date_dirs:
        logger.error(f"No date folders found in {txt_root}")
        sys.exit(1)
    return sorted(date_dirs)[-1]


# Create a session with retry strategy
def create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_files(files_root: Path) -> pl.DataFrame:
    files = subprocess.run(
        [
            "rg",
            "--files",
            "-g",
            "*.txt",
            "-g",
            "!**/_invalid/**",
            str(files_root),
        ],
        capture_output=True,
        text=True,
    )
    # Convert output to Polars DataFrame including file path and domain
    file_paths = [line.strip() for line in files.stdout.strip().split("\n") if line.strip()]
    records = []
    for path in file_paths:
        domain = Path(path).parent.name
        file_type = Path(path).name
        records.append({"file_path": path, "domain": domain, "type": file_type})
    return pl.DataFrame(records)


def load_permissions(path: Path) -> PermissionsMap:
    return json.loads(path.read_text(encoding="utf-8"))


def load_domains_with_both(path: Path) -> list[str]:
    df = pl.read_parquet(path).filter(pl.col("robots_txt") & pl.col("ai_txt"))
    return df.get_column("domain").to_list()
