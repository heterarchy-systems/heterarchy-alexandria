#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$plugin_dir/../.." && pwd)"
mkdir -p "$repo_dir/dist"
stage_dir="$(mktemp -d "$repo_dir/dist/alexandria-package.XXXXXX")"
trap 'rm -rf "$stage_dir"' EXIT
package_dir="$stage_dir/heterarchy-alexandria"
mkdir -p "$package_dir/skills"
cp "$plugin_dir/plugin.json" "$plugin_dir/.app.json" "$package_dir/"

for skill in alexandria-library alexandria-current-refresh alexandria-graph-care \
  alexandria-maintenance-dlq connection-hub operational-sync safe-markdown-storage; do
  if [ -n "$(find "$repo_dir/skills_alexandria/$skill" -type l -print -quit)" ]; then
    echo "Refusing symlinks in skill: $skill" >&2
    exit 1
  fi
  while IFS= read -r -d '' source_file; do
    relative_file="${source_file#"$repo_dir/skills_alexandria/"}"
    mkdir -p "$package_dir/skills/$(dirname "$relative_file")"
    cp "$source_file" "$package_dir/skills/$relative_file"
  done < <(find "$repo_dir/skills_alexandria/$skill" -type f \
    \( -name '*.md' -o -name '*.yaml' \) -print0)
done
mv "$package_dir/skills/safe-markdown-storage" \
  "$package_dir/skills/alexandria-safe-markdown-storage"
while IFS= read -r -d '' skill_file; do
  sed 's|../safe-markdown-storage/SKILL.md|../alexandria-safe-markdown-storage/SKILL.md|g' \
    "$skill_file" > "$skill_file.tmp"
  mv "$skill_file.tmp" "$skill_file"
done < <(find "$package_dir/skills" -name '*.md' -print0)

# A fresh output directory prevents stale files surviving an archive update.
output_dir="$(mktemp -d "$repo_dir/dist/alexandria-release.XXXXXX")"
(cd "$stage_dir" && zip -qr "$output_dir/heterarchy-alexandria.zip" heterarchy-alexandria)
printf '%s\n' "$output_dir/heterarchy-alexandria.zip"
