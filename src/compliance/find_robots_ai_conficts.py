import logging
import re
from os import PathLike
from pathlib import Path

import fire
import polars as pl

from src.utils import get_data_dir, load_domains_with_both, load_known_bots, load_permissions, setup_logging

logger = logging.getLogger(__name__)


# regex to pull out User-Agent / Allow / Disallow lines
DIRECTIVE_RE = re.compile(r"^\s*(User-Agent|Allow|Disallow)\s*:\s*(\S.*)$", re.IGNORECASE)


def find_directive_lines(fp: Path, directive: str, path_value: str) -> list[tuple[int, str]]:
    matches = []
    for lineno, line in enumerate(fp.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        m = DIRECTIVE_RE.match(line)
        if not m:
            continue
        field, val = m.group(1).lower(), m.group(2).strip()
        if field == directive.lower() and val == path_value:
            matches.append((lineno, line))
    return matches


def main(date: str | None = None, data_dir: PathLike | None = None, force: bool = False) -> None:
    _, base_dir = get_data_dir(date, data_dir)
    out_dir = base_dir / "analysis"

    domains_path = out_dir / "domain_files_map.parquet"
    map_path = base_dir / "analysis" / "permissions_map.json"
    out_path = out_dir / "ai_conflicts.parquet"

    domains = load_domains_with_both(domains_path)
    perm_map = load_permissions(map_path)
    known_bots = load_known_bots(out_dir / "cloudflare_known_bots.json")

    if out_path.exists() and not force:
        logger.info(f"AI conflicts file already exists at {out_path}, skipping generation (use --force to regenerate)")
    else:
        conflicts = []
        for domain in domains:
            if domain not in perm_map:
                continue
            rob_block = perm_map[domain].get("robots", {})
            ai_block = perm_map[domain].get("ai", {})

            # gather every UA key we might compare: explicit ones + wildcard if present
            candidate_uas = set(rob_block) | set(ai_block)
            if "*" in rob_block or "*" in ai_block:
                candidate_uas.add("*")

            for ua_key in sorted(candidate_uas):
                # only keep explicit AIs or the wildcard
                if ua_key != "*" and not any(sub.lower() in ua_key.lower() for sub in known_bots):
                    continue

                rob_rules = rob_block.get(ua_key) or rob_block.get("*", {"allow": [], "disallow": []})
                ai_rules = ai_block.get(ua_key) or ai_block.get("*", {"allow": [], "disallow": []})

                rob_allow = set(rob_rules.get("allow", []))
                rob_disallow = set(rob_rules.get("disallow", []))
                ai_allow = set(ai_rules.get("allow", []))
                ai_disallow = set(ai_rules.get("disallow", []))

                # all paths mentioned in either file
                all_paths = rob_allow | rob_disallow | ai_allow | ai_disallow

                for path in sorted(all_paths):
                    ai_has_allow = path in ai_allow
                    ai_has_disallow = path in ai_disallow
                    rob_has_allow = path in rob_allow
                    rob_has_disallow = path in rob_disallow

                    # determine relationship type
                    if ai_has_allow and rob_has_disallow:
                        relationship = "conflict_ai_allow_rob_disallow"
                    elif ai_has_disallow and rob_has_allow:
                        relationship = "conflict_ai_disallow_rob_allow"
                    elif ai_has_allow and rob_has_allow:
                        relationship = "both_allow"
                    elif ai_has_disallow and rob_has_disallow:
                        relationship = "both_disallow"
                    elif ai_has_allow and not rob_has_allow and not rob_has_disallow:
                        relationship = "ai_only_allow"
                    elif ai_has_disallow and not rob_has_allow and not rob_has_disallow:
                        relationship = "ai_only_disallow"
                    elif rob_has_allow and not ai_has_allow and not ai_has_disallow:
                        relationship = "robots_only_allow"
                    elif rob_has_disallow and not ai_has_allow and not ai_has_disallow:
                        relationship = "robots_only_disallow"
                    else:
                        relationship = "unknown"
                        continue  # shouldn't happen given our set union

                    conflicts.append(
                        {
                            "domain": domain,
                            "user_agent": ua_key,
                            "path": path,
                            "relationship": relationship,
                            "ai_allow": ai_has_allow,
                            "ai_disallow": ai_has_disallow,
                            "rob_allow": rob_has_allow,
                            "rob_disallow": rob_has_disallow,
                        }
                    )

        df = pl.DataFrame(conflicts)
        df.write_parquet(out_path)
        logger.info(f"Wrote AI conflicts for {len(df)} entries to {out_path}")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
