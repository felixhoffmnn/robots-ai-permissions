import logging
import subprocess
import sys
from os import PathLike
from pathlib import Path

import fire
from tqdm import tqdm

import polars as pl
from src.utils import get_data_dir, setup_logging

logger = logging.getLogger(__name__)


def move_invalid_files(files: pl.Series) -> None:
    """Move files in the invalid list to the '_invalid' subdirectory."""
    counts = {
        "already_moved": 0,
        "not_exist": 0,
        "moved": 0,
    }

    for file_path in tqdm(files, desc="Moving invalid files"):
        file_path = Path(file_path)
        invalid_dir = file_path.parent / "_invalid"
        new_path = invalid_dir / file_path.name

        # Check if file has already been moved
        if new_path.exists():
            counts["already_moved"] += 1
            logger.debug(f"File already moved: {new_path}")
            continue

        # Check if file exists in original location
        if not file_path.exists():
            counts["not_exist"] += 1
            logger.debug(f"File does not exist: {file_path}")
            continue

        invalid_dir.mkdir(exist_ok=True)
        counts["moved"] += 1
        logger.debug(f"Moving {file_path} to {new_path}")
        file_path.rename(new_path)

    logger.info(
        f"Moved {counts['moved']}, skipped {counts['already_moved']} already moved, and {counts['not_exist']} non-existing files."
    )


def move_valid_files(files_dir: Path) -> None:
    """Move files from '_invalid' subdirectories back to their parent directories.
    Remove empty '_invalid' directories afterwards.
    """
    counts = {
        "moved": 0,
        "failed": 0,
    }

    # Use ripgrep to find all files in _invalid directories
    try:
        result = subprocess.run(
            ["rg", "--files", "--no-heading", "--glob", "**/_invalid/**", str(files_dir)],
            capture_output=True,
            text=True,
            check=True,
        )
        file_paths = [Path(line) for line in result.stdout.strip().split("\n") if line]
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to run ripgrep: {e}")
        return
    except FileNotFoundError:
        logger.error("ripgrep (rg) not found. Please install it.")
        return

    # Move files back to parent directories
    for file_path in tqdm(file_paths, desc="Moving files from _invalid directories"):
        if not file_path.is_file():
            continue

        target_path = file_path.parent.parent / file_path.name

        try:
            logger.debug(f"Moving {file_path} to {target_path}")
            file_path.rename(target_path)
            counts["moved"] += 1
        except Exception as e:
            logger.error(f"Failed to move {file_path}: {e}")
            counts["failed"] += 1

    logger.info(f"Moved {counts['moved']} files back, {counts['failed']} failed.")


def find_invalid_files(files_dir: Path) -> pl.DataFrame:
    """Use ripgrep to find invalid files and return a DataFrame with file paths and reasons."""
    invalid_files = []

    # Find HTML files
    logger.info("Searching for HTML files...")
    try:
        result = subprocess.run(
            [
                "rg",
                "--files-with-matches",
                "--no-heading",
                "-i",
                "-g",
                "**/*.txt",
                "-g",
                "!**/_invalid/**",
                "--no-ignore",
                r"^\s*(?:<!doctype html|<html|<head)",
                str(files_dir),
            ],
            capture_output=True,
            text=True,
        )
        html_files = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        invalid_files.extend([(f, "html") for f in html_files])
        logger.info(f"Found {len(html_files)} HTML files")
    except Exception as e:
        logger.error(f"Failed to find HTML files: {e}")

    # Find files without User-Agent
    logger.info("Searching for files without User-Agent...")
    try:
        result = subprocess.run(
            [
                "rg",
                "--files-without-match",
                "--no-heading",
                "-i",
                "-g",
                "robots.txt",
                "-g",
                "ai.txt",
                "-g",
                "!**/_invalid/**",
                "--no-ignore",
                r"^\s*User-Agent\s*:",
                str(files_dir),
            ],
            capture_output=True,
            text=True,
        )
        no_useragent_files = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        invalid_files.extend([(f, "useragent") for f in no_useragent_files])
        logger.info(f"Found {len(no_useragent_files)} files without User-Agent")
    except Exception as e:
        logger.error(f"Failed to find files without User-Agent: {e}")

    # Find files without markdown
    logger.info("Searching for files without markdown...")
    try:
        result = subprocess.run(
            [
                "rg",
                "--files-without-match",
                "--no-heading",
                "-g",
                "llms*.txt",
                "-g",
                "!**/_invalid/**",
                "--no-ignore",
                r"(?:^#{1,6}\s|^\s*[-*+]\s|^\s*\d+\.\s|\[.+\]\(.+\)|```|^\s*>)",
                str(files_dir),
            ],
            capture_output=True,
            text=True,
        )
        no_markdown_files = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        invalid_files.extend([(f, "markdown") for f in no_markdown_files])
        logger.info(f"Found {len(no_markdown_files)} files without markdown")
    except Exception as e:
        logger.error(f"Failed to find files without markdown: {e}")

    # Create DataFrame
    if invalid_files:
        df = pl.DataFrame(invalid_files, schema=["file", "reason"], orient="row")
        return df.group_by("file").agg(pl.col("reason"))
    else:
        return pl.DataFrame(schema={"file": pl.Utf8, "reason": pl.List(pl.Utf8)})


def main(date: str | None = None, data_dir: PathLike | None = None, reverse: bool = False) -> None:
    date, base_dir = get_data_dir(date, data_dir)

    files_dir = base_dir / "files"
    analysis_dir = base_dir / "analysis"
    invalid_df_path = analysis_dir / "invalid_files.parquet"

    if not files_dir.is_dir():
        logger.error(f"Expected {files_dir}")
        sys.exit(1)

    if reverse:
        move_valid_files(files_dir)
        return

    if not invalid_df_path.is_file():
        analysis_dir.mkdir(parents=True, exist_ok=True)
        df_invalid = find_invalid_files(files_dir)
        df_invalid.write_parquet(invalid_df_path)
        logger.info(f"Saved invalid files to {invalid_df_path}")
    else:
        df_invalid = pl.read_parquet(invalid_df_path)

    move_invalid_files(df_invalid.get_column("file"))


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
