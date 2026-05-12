# Print available commands.
@help:
    just --list

# Setup the development environment.
[group("dev")]
setup:
    uv sync

# Run commands against ruff, for example: just ruff check .
[group("dev")]
ruff *COMMANDS:
    uv run ruff {{ COMMANDS }}

# Create list of files containing robots.txt, ai.txt, llms.txt, llms-full.txt.
[group("data")]
find-files file_dir="data/2025-10-11/files/" output_dir="data/2025-10-11/analysis/":
    bash scripts/find_files.sh "{{ file_dir }}" "{{ output_dir }}"

# Run plot notebooks.
[group("plots")]
notebook-run FILE:
    uv run jupyter nbconvert --execute --to notebook --inplace {{ FILE }}

# Export plot notebooks to PDF.
[group("plots")]
notebook-export FILE:
    uv run jupyter nbconvert --to pdf {{ FILE }}
