import logging
import re
from os import PathLike
from pathlib import Path
from urllib.parse import urlparse

import fire
import polars as pl
from tqdm import tqdm

from src.utils import get_data_dir, setup_logging

# Regexes
LINK_RE = re.compile(r"\[.*?\]\((https?://[^)]+|/[^)]+)\)")
DISALLOW_RE = re.compile(r"^\s*Disallow\s*:\s*(\S.*)$", re.IGNORECASE)
DIRECTIVE_RE = re.compile(r"^\s*(DisallowAITraining|Content-Usage)\s*:\s*(\S.*)$", re.IGNORECASE)

logger = logging.getLogger(__name__)


def load_disallows(fp: Path) -> list[tuple[str, str]]:
    """Read Disallow and experimental directives as (pattern, directive_name)."""
    res = []
    for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = DISALLOW_RE.match(line)
        if m:
            res.append((m.group(1).strip(), "Disallow"))
            continue
        m2 = DIRECTIVE_RE.match(line)
        if m2 and m2.group(1).lower() == "disallowaitraining":
            val = m2.group(2).strip()
            if val == "/":
                res.append(("/", "DisallowAITraining"))
        elif m2 and m2.group(1).lower() == "content-usage":
            res.append((m2.group(2).strip(), "Content-Usage"))
    return res


def normalize_link(domain: str, url: str) -> str:
    """Convert absolute or relative URL to a path on the domain."""
    if url.startswith("/"):
        return url

    try:
        parsed = urlparse(url)
    except ValueError:
        # Invalid URL format, return root to skip matching
        return "/"

    # If it's an absolute URL, check if it matches the domain
    if parsed.netloc:
        if parsed.netloc == domain or parsed.netloc == f"www.{domain}" or parsed.netloc == domain.replace("www.", ""):
            return parsed.path or "/"
        # Different domain, return root to avoid false matches
        return "/"

    # Relative URL without scheme/netloc
    return parsed.path or "/"


def scan_domain(domain_dir: Path, domain: str, files: dict[str, bool]) -> list[tuple[str, int, str, str, str]]:
    """
    For domain, scan llms.txt links, check against disallow patterns
    from robots.txt/ai.txt. Return list of conflicts:
      (domain, line_no, link_url, blocking_file, directive_name)
    """
    llms_txt_path = domain_dir / "llms.txt"
    robots_txt_path = domain_dir / "robots.txt" if files["robots_txt"] else None
    ai_txt_path = domain_dir / "ai.txt" if files["ai_txt"] else None

    disallows = []
    if robots_txt_path and robots_txt_path.is_file():
        for pattern, directive_name in load_disallows(robots_txt_path):
            disallows.append((pattern, "robots_txt", directive_name))
    if ai_txt_path and ai_txt_path.is_file():
        for pattern, directive_name in load_disallows(ai_txt_path):
            disallows.append((pattern, "ai_txt", directive_name))

    if len(disallows) == 0:
        return []

    conflicts = []
    for lineno, line in enumerate(llms_txt_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        for m in LINK_RE.finditer(line):
            url = m.group(1)
            path = normalize_link(domain, url)
            for pattern, fname, directive in disallows:
                if pattern == "/" or path.startswith(pattern):
                    conflicts.append((domain, lineno, url, fname, directive))

    return conflicts


def main(date: str | None = None, data_dir: PathLike | None = None, force: bool = False) -> None:
    """Main entry point to scan all domains for llms.txt links pointing to blocked paths.

    This scans all domains that have both llms.txt and at least one of robots.txt or ai.txt.
    For each domain, it loads the disallow directives from robots.txt and ai.txt, then scans
    llms.txt for links. If any link points to a path blocked by a disallow directive, it is reported.
    """
    _, base_dir = get_data_dir(date, data_dir)
    files_dir = base_dir / "files"
    analysis_dir = base_dir / "analysis"
    out_path = analysis_dir / "llms_blocked_paths.parquet"

    if out_path.exists() and not force:
        logger.info(
            f"LLMs conflicts file already exists at {out_path}, skipping generation (use --force to regenerate)"
        )
    else:
        domains = pl.read_parquet(analysis_dir / "domain_files_map.parquet").filter(
            pl.col("llms_txt") & (pl.col("robots_txt") | pl.col("ai_txt"))
        )

        conflicts = []
        for domain, split, files in tqdm(
            domains.select(
                pl.col("domain"), pl.col("split"), pl.struct(["robots_txt", "ai_txt", "llms_txt"])
            ).iter_rows(),
            desc="Scanning domains",
            total=domains.height,
        ):
            domain_dir = files_dir / split / domain
            results = scan_domain(domain_dir, domain, files)
            conflicts.extend(results)

        df_results = pl.DataFrame(
            list(set(conflicts)),
            schema=["domain", "line_no", "link_url", "blocking_file", "directive_name"],
            orient="row",
        )
        df_results.write_parquet(out_path)

        logger.info(f"Found {df_results.height} llms.txt links pointing to blocked paths. Results saved to {out_path}")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
