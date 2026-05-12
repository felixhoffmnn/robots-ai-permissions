import logging
import re
import subprocess
from os import PathLike
from pathlib import Path

import fire
import polars as pl

from src.utils import get_data_dir, setup_logging

logger = logging.getLogger(__name__)


def find_exp_directives(splits_dir: Path) -> pl.DataFrame:
    result = subprocess.run(
        [
            "rg",
            "-n",
            "--no-heading",
            "--with-filename",
            "-g",
            "**/robots.txt",
            "--no-ignore",
            r"(?i)^\s*(AllowAITraining|DisallowAITraining|Content-Usage|Content-Signal)\s*:\s*.+$",
            str(splits_dir),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode > 1:
        raise RuntimeError(f"ripgrep error: {result.stderr}")

    pattern = re.compile(
        r"^(?P<filepath>.+?):(?P<line_number>\d+):\s*(?P<directive>AllowAITraining|DisallowAITraining|Content-Usage|Content-Signal)\s*:\s*(?P<value>.+)$",
        re.IGNORECASE,
    )

    records = []
    for line in result.stdout.strip().splitlines():
        m = pattern.match(line)
        if m:
            records.append(
                {
                    "domain": Path(m.group("filepath")).parent.name,
                    "filepath": m.group("filepath"),
                    "line_number": int(m.group("line_number")),
                    "directive": m.group("directive").strip(),
                    "value": m.group("value").strip(),
                }
            )

    return pl.DataFrame(records)


def main(date: str | None = None, data_dir: PathLike | None = None, force: bool = False) -> None:
    _, base_dir = get_data_dir(date, data_dir)
    files_dir = base_dir / "files"
    analysis_dir = base_dir / "analysis"
    out_path = analysis_dir / "exp_directives.parquet"

    analysis_dir.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        logger.info(
            f"Experimental directives file already exists at {out_path}, skipping generation (use --force to regenerate)"
        )
    else:
        df_directives = find_exp_directives(files_dir)
        df_directives.write_parquet(out_path)
        logger.info(f"Wrote experimental directives to {out_path}")


if __name__ == "__main__":
    setup_logging()

    fire.Fire(main)
