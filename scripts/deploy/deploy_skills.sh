#!/bin/bash
set -euo pipefail

# Deploy evolved skills from local storage to GDrive evolved-skills/
# Compares evolved skills against LIVE baseline in agent-skills/ (not evolved-skills/)
# Generates diff summaries comparing evolved vs live agent baseline

LOCAL_DIR="/data/local-share/openclaw-fleet/skills"
GDRIVE_DIR="/mnt/gdrive/shared/common/evolved-skills"
AGENT_SKILLS_DIR="/mnt/gdrive/shared/common/agent-skills"
DIFF_DIR="/mnt/gdrive/shared/common/evolved-diffs"
LOG_PREFIX="[skillclaw:deploy]"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

if [ ! -d "$LOCAL_DIR" ]; then
  echo "$LOG_PREFIX WARN: Local skills directory not found: $LOCAL_DIR"
  exit 0
fi

mkdir -p "$GDRIVE_DIR" "$DIFF_DIR"

deployed=0
skipped=0
diffs_generated=0

# Look for contributing agent info from session metadata if available
get_contributing_agents() {
  local skill_name="$1"
  local meta_file="${LOCAL_DIR}/${skill_name}/.meta/agents.json"
  if [ -f "$meta_file" ]; then
    python3 -c "import json,sys; d=json.load(open('$meta_file')); print('\'.join(d.get('contributors', ['unknown'])))" 2>/dev/null || echo "unknown"
  else
    echo "not tracked"
  fi
}

# Generate a diff summary between evolved SKILL.md and live agent baseline
# Writes to $DIFF_DIR/{skill_name}.md
generate_diff_summary() {
  local skill_name="$1"
  local evolved_file="$2"
  local baseline_file="$3"
  local diff_file="${DIFF_DIR}/${skill_name}.md"
  local contributing_agents=$(get_contributing_agents "$skill_name")

  # Build the diff body using diff output
  local diff_body
  diff_body=$(diff -u "$baseline_file" "$evolved_file" 2>/dev/null || true)

  # Count changes
  local lines_added=$(echo "$diff_body" | grep -c '^+[^+]\ 2>/dev/null || true)
  local lines_removed=$(echo "$diff_body" | grep -c '^-[^-]\ 2>/dev/null || true)

  # Extract changed section headings from the diff
  local changed_sections
  changed_sections=$(echo "$diff_body" | grep -E '^[+-]#{1,4} ' | sed 's/^[+-]//' | sort -u || true)

  # Determine what was added vs removed vs modified
  local sections_added sections_removed
  sections_added=$(echo "$diff_body" | grep -E '^\+#{1,4} ' | sed 's/^+//' | sort -u || true)
  sections_removed=$(echo "$diff_body" | grep -E '^\-#{1,4} ' | sed 's/^-//' | sort -u || true)

  # Write the diff summary
  cat > "$diff_file" << HEREDOC
# Diff: ${skill_name}

- **Skill:** ${skill_name}
- **Generated:** ${TIMESTAMP}
- **Contributing Agents:** ${contributing_agents}

## Summary

- Lines added: ${lines_added}
- Lines removed: ${lines_removed}

## Sections Added

${sections_added:+$(echo "$sections_added" | sed 's/^/- /')}
${sections_added:-(none)}

## Sections Removed

${sections_removed:+$(echo "$sections_removed" | sed 's/^/- /')}
${sections_removed:-(none)}

## Changed Sections

${changed_sections:+$(echo "$changed_sections" | sed 's/^/- /')}
${changed_sections:-(none)}

## Raw Diff

\`\`\`diff
${diff_body}
\`\`\`
HEREDOC

  echo "$LOG_PREFIX DIFF: ${skill_name} → ${diff_file}"
  diffs_generated=$((diffs_generated + 1))
}

for skill_dir in "$LOCAL_DIR"/*/; do
  [ -d "$skill_dir" ] || continue
  skill_md="${skill_dir}SKILL.md"
  [ -f "$skill_md" ] || continue

  skill_name=$(basename "$skill_dir")
  evolved_target="${GDRIVE_DIR}/${skill_name}/SKILL.md"
  live_baseline="${AGENT_SKILLS_DIR}/${skill_name}/SKILL.md"

  # Skip if evolved copy on GDrive already matches or is newer than local
  if [ -f "$evolved_target" ]; then
    if [ "$evolved_target" -nt "$skill_md" ]; then
      echo "$LOG_PREFIX SKIP: ${skill_name} (evolved copy is newer)"
      skipped=$((skipped + 1))
      continue
    fi
  fi

  # Generate diff: compare evolved local vs LIVE agent baseline
  if [ -f "$live_baseline" ]; then
    generate_diff_summary "$skill_name" "$skill_md" "$live_baseline"
  else
    # New skill — no live baseline, log as new
    cat > "${DIFF_DIR}/${skill_name}.md" << HEREDOC
# Diff: ${skill_name}

- **Skill:** ${skill_name}
- **Generated:** ${TIMESTAMP}
- **Contributing Agents:** $(get_contributing_agents "$skill_name")

## Summary

**NEW SKILL** — no prior baseline in agent-skills/.

## Raw Content

\`\`\`
$(cat "$skill_md")
\`\`\`
HEREDOC

    echo "$LOG_PREFIX DIFF (new): ${skill_name}"
    diffs_generated=$((diffs_generated + 1))
  fi

  mkdir -p "${GDRIVE_DIR}/${skill_name}"
  cp "$skill_md" "$evolved_target"
  echo "$LOG_PREFIX DEPLOY: ${skill_name}"
  deployed=$((deployed + 1))
done

echo "$LOG_PREFIX DONE: ${deployed} deployed, ${skipped} skipped, ${diffs_generated} diffs generated"
