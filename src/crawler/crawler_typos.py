import json
import logging
import re
from os import PathLike
from pathlib import Path

import fire
from rapidfuzz import fuzz, process

from src.utils import get_data_dir, load_domains_with_both, load_known_bots, load_permissions, setup_logging

logger = logging.getLogger(__name__)

FUZZY_MATCH_THRESHOLD = 90


def normalize(s: str) -> str:
    """Remove non-alphanumeric characters and convert to lowercase."""
    return re.sub(r"\W+", "", s.lower())


def clean_bot_name(bot_name: str) -> str:
    """Remove version numbers and slashes from bot name."""
    # Remove version numbers (e.g., /1.0, -2.5, _3.0.1)
    cleaned = re.sub(r"[/_-]?\d+(\.\d+)*", "", bot_name)
    # Remove any remaining slashes
    cleaned = cleaned.replace("/", "")
    return cleaned.strip()


def find_typo_match(user_agent: str, normalized_bots: list[str], original_bots: list[str]) -> str | None:
    """
    Find the best fuzzy match for a user agent against known bots.

    Returns:
        Original bot name if match found above threshold, None otherwise.
    """
    normalized_ua = normalize(user_agent)

    match = process.extractOne(normalized_ua, normalized_bots, scorer=fuzz.token_sort_ratio)
    if match and match[1] >= FUZZY_MATCH_THRESHOLD:
        # Return the cleaned original bot name
        matched_index = normalized_bots.index(match[0])
        return clean_bot_name(original_bots[matched_index])
    return None


def extract_user_agents(robots_uas: dict, ai_uas: dict) -> set[str]:
    """Extract all unique user agents from robots.txt and ai.txt, excluding wildcards."""
    user_agents = set(robots_uas) | set(ai_uas)
    user_agents.discard("*")
    return user_agents


def create_result_entry(domain: str, file_type: str, user_agent: str, suggestion: str) -> dict:
    """Create a standardized result entry."""
    return {
        "domain": domain,
        "file": file_type,
        "user_agent": user_agent,
        "suggestion": suggestion,
    }


def process_domain(
    domain: str,
    perm_map: dict,
    normalized_bots: list[str],
    original_bots: list[str],
) -> list[dict]:
    """Process a single domain and return potential typo matches."""
    if domain not in perm_map:
        return []

    robots_user_agents = perm_map[domain].get("robots", {})
    ai_user_agents = perm_map[domain].get("ai", {})

    user_agents = extract_user_agents(robots_user_agents, ai_user_agents)

    domain_results = []
    for user_agent in sorted(user_agents):
        suggestion = find_typo_match(user_agent, normalized_bots, original_bots)
        if not suggestion:
            continue

        if user_agent in robots_user_agents:
            domain_results.append(create_result_entry(domain, "robots.txt", user_agent, suggestion))
        if user_agent in ai_user_agents:
            domain_results.append(create_result_entry(domain, "ai.txt", user_agent, suggestion))

    return domain_results


def save_results(results: list[dict], output_path: Path) -> None:
    """Save results to a JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Found {len(results)} potential typos. Results saved to {output_path}")


def save_mapping(results: list[dict], output_path: Path) -> None:
    """Save unique user agent to suggestion mappings to a JSON file."""
    mapping = []
    seen_user_agents = set()

    for result in results:
        user_agent = result["user_agent"]
        suggestion = result["suggestion"]
        # Only add if different and not already present (keeps first occurrence)
        if user_agent != suggestion and user_agent not in seen_user_agents:
            mapping.append({"original": user_agent, "corrected": suggestion})
            seen_user_agents.add(user_agent)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(mapping, f, indent=2)
    logger.info(f"Saved {len(mapping)} unique mappings to {output_path}")


def main(date: str | None = None, data_dir: PathLike | None = None) -> None:
    """Analyze user agents for potential typos by fuzzy matching against known bots."""
    _, base_dir = get_data_dir(date, data_dir)
    out_dir = base_dir / "analysis"

    domains_path = out_dir / "domain_files_map.parquet"
    map_path = out_dir / "permissions_map.json"

    domains = load_domains_with_both(domains_path)
    perm_map = load_permissions(map_path)
    known_bots = load_known_bots(out_dir / "cloudflare_known_bots.json")

    # Normalize known bots once for efficient matching
    normalized_bots = [normalize(bot) for bot in known_bots]

    results = []
    for domain in domains:
        domain_results = process_domain(domain, perm_map, normalized_bots, known_bots)
        results.extend(domain_results)

    output_path = out_dir / "typo_analysis.json"
    save_results(results, output_path)

    mapping_path = out_dir / "typo_mapping.json"
    save_mapping(results, mapping_path)


if __name__ == "__main__":
    setup_logging()
    fire.Fire(main)
