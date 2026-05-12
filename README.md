# Robots AI Permissions

Source-code artifact for the paper "From robots.txt to ai.txt: Mapping the Evolution of Web Permissions in the Age of AI".

This repository contains the crawler, processing, and analysis code. The corresponding analysis data and raw crawl archive are published separately on Zenodo.

## Data

The data is not stored in git. Download `robots-ai-permissions-data-2025-10-11.tar.gz` from Zenodo and unpack it so that the repository contains a local `data/` directory:

```bash
tar -xzf robots-ai-permissions-data-2025-10-11.tar.gz
```

Expected result:

```text
data/
`-- 2025-10-11/analysis/
```

The same Zenodo record also includes the raw crawl archive and checksums:

```text
robots-ai-permissions-data-2025-10-11.tar.gz
robots-ai-permissions-data-2025-10-11.tar.gz.sha256
robots-ai-permissions-raw-crawl-2025-10-11.tar.zst
robots-ai-permissions-raw-crawl-2025-10-11.tar.zst.sha256
```

Zenodo DOI: [10.5281/zenodo.20138990](https://doi.org/10.5281/zenodo.20138990)

The submitted analysis package contains the tracked analysis outputs from the source commit plus supplemental bot metadata exported from the local DuckDB store and parent-category mappings derived from the bundled Cloudflare domain details. The raw crawl archive contains the `2025-10-11` crawl files. Some exploratory notebooks and rerun workflows still require external inputs or services that are not bundled, including Cloudflare API access and Common Crawl WARC files.

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

Useful commands are available through `just`:

```bash
just --list
```

Run linting with:

```bash
just ruff check .
```

## Repository Layout

- `src/common_crawl/`: Common Crawl collection helpers
- `src/crawler/`: Tranco-based crawler and cleaning scripts
- `src/compliance/`: permission mapping and conflict analysis
- `src/notebooks/`: exploratory notebooks used during analysis
- `scripts/`: shell helpers
- `container/`: crawler container configuration

## Licenses

This repository is derived from [TobiPeterG/robots-ai-permissions](https://github.com/TobiPeterG/robots-ai-permissions). Code in this repository is released under the GNU General Public License v3.0. The dataset prepared for Zenodo is released under Creative Commons Attribution 4.0 International, unless a third-party source imposes stricter terms.
