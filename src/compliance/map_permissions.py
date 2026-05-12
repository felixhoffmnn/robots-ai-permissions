import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from os import PathLike
from pathlib import Path
from urllib.robotparser import RobotFileParser

import fire

from src.utils import (
    PermissionsMap,
    UserAgentRules,
    get_data_dir,
    load_domains_with_both,
    load_permissions,
    setup_logging,
)

logger = logging.getLogger(__name__)


def parse_rules(filepath: Path, url: str) -> PermissionsMap:
    """Parse a local robots-style file into a dict:
    { user_agent: { 'allow': [...], 'disallow': [...] }, ... }
    """
    text = Path(filepath).read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines()]
    parser = RobotFileParser()
    parser.set_url(url)
    parser.parse(lines)

    rules = {}
    entries = parser.entries  # type: ignore
    if parser.default_entry:  # type: ignore
        entries.append(parser.default_entry)  # type: ignore

    for entry in entries:
        for ua in entry.useragents:
            rules.setdefault(ua, {"allow": [], "disallow": []})
            for rule in entry.rulelines:
                target = "allow" if rule.allowance else "disallow"
                rules[ua][target].append(rule.path)
    return rules


def process_domain(args: tuple[str, Path]) -> tuple[str, dict] | None:
    domain, files_root = args
    # locate the folder under any split
    domain_dir = None
    for split in files_root.iterdir():
        p = split / domain
        if p.is_dir():
            domain_dir = p
            break
    if not domain_dir:
        return None

    rob_fp = domain_dir / "robots.txt"
    ai_fp = domain_dir / "ai.txt"
    if not (rob_fp.is_file() and ai_fp.is_file()):
        return None

    try:
        rob_rules = parse_rules(rob_fp, f"https://{domain}/robots.txt")
        ai_rules = parse_rules(ai_fp, f"https://{domain}/ai.txt")
    except Exception:
        return None

    return domain, {"robots": rob_rules, "ai": ai_rules}


def compare_rules(rob: UserAgentRules, ai: UserAgentRules) -> dict[str, list[str]]:
    """Rob and ai are dicts: {'allow': [...], 'disallow': [...]}
    Returns dict of intersections/differences.
    """
    rob_allow = set(rob.get("allow", []))
    ai_allow = set(ai.get("allow", []))
    rob_dis = set(rob.get("disallow", []))
    ai_dis = set(ai.get("disallow", []))

    return {
        "allow_equal": sorted(rob_allow & ai_allow),
        "allow_only_robots": sorted(rob_allow - ai_allow),
        "allow_only_ai": sorted(ai_allow - rob_allow),
        "disallow_equal": sorted(rob_dis & ai_dis),
        "disallow_only_robots": sorted(rob_dis - ai_dis),
        "disallow_only_ai": sorted(ai_dis - rob_dis),
    }


def main(date: str | None = None, data_dir: PathLike | None = None, force: bool = False) -> None:
    _, base_dir = get_data_dir(date, data_dir)
    files_dir = base_dir / "files"
    out_dir = base_dir / "analysis"

    domains_path = out_dir / "domain_files_map.parquet"
    map_path = out_dir / "permissions_map.json"
    diff_path = out_dir / "permissions_diff.json"

    # Generate permissions map
    if map_path.exists() and not force:
        logger.info(f"Permissions map already exists at {map_path}, skipping generation (use --force to regenerate)")
    else:
        # load domains
        try:
            domains = load_domains_with_both(domains_path)
        except FileNotFoundError:
            logger.error(f"CSV not found: {domains_path}")
            sys.exit(1)

        if not domains:
            logger.info("No domains with both robots.txt and ai.txt.")
            sys.exit(0)

        # parse in parallel
        tasks = [(d, files_dir) for d in domains]
        result = {}
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
            for out in pool.map(process_domain, tasks):
                if out:
                    domain, rules = out
                    result[domain] = rules

        # write JSON
        map_path.write_text(json.dumps(result, indent=2))
        logger.info(f"Wrote permissions map for {len(result)} domains to {map_path}")

    # Generate diff between robots.txt and ai.txt
    if diff_path.exists() and not force:
        logger.info(f"Permissions diff already exists at {diff_path}, skipping generation (use --force to regenerate)")
    else:
        permissions = load_permissions(map_path)
        diff = {}

        for domain, blocks in permissions.items():
            rob_block = blocks.get("robots", {})
            ai_block = blocks.get("ai", {})

            # all UAs we'll compare (including wildcard)
            uas = set(rob_block) | set(ai_block)
            uas.add("*")

            domain_diff = {}
            for ua in sorted(uas):
                # fallback to '*' if UA not present
                rob_rules = rob_block.get(ua) or rob_block.get("*", {"allow": [], "disallow": []})
                ai_rules = ai_block.get(ua) or ai_block.get("*", {"allow": [], "disallow": []})

                domain_diff[ua] = compare_rules(rob_rules, ai_rules)

            diff[domain] = domain_diff

        # write out
        diff_path.write_text(json.dumps(diff, indent=2), encoding="utf-8")
        logger.info(f"Wrote diff for {len(diff)} domains to {diff_path}")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
