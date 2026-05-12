#!/bin/bash
# Usage: ./find_files.sh /path/to/file_dir /path/to/output_dir

file_dir="$1"
output_dir="$2"

if [ ! -d "$file_dir" ]; then
  echo "Error: file_dir '$file_dir' does not exist"
  exit 1
fi

mkdir -p "$output_dir/urls"

declare -a targets=("robots.txt" "ai.txt" "llms.txt" "llms-full.txt")

for name in "${targets[@]}"; do
  out_file="${output_dir}/urls/${name%.txt}_urls.txt"
  rg --files \
     --iglob "**/${name}" \
     --glob "!**/_invalid/**" \
     "$file_dir" \
  | awk -F'/' '{print $(NF-1)}' \
  | sort -u > "$out_file"
done
