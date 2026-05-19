#!/bin/bash
set -euo pipefail

# Container-side script: Copy skills from GDrive central store → SkillClaw skill repository
# Runs inside the SkillClaw container (has GDrive mount and /data/local-share)
# Called from skillclaw-daily.sh

GDRIVE_STORE="/mnt/gdrive/shared/common/agent-skills"
SKILLCLAW_REPO="/data/local-share/openclaw-fleet/skills"
LOG_PREFIX="[skillclaw:sync]"
SKIP_AGENTS="forge"

echo "$LOG_PREFIX Starting bidirectional sync (GDrive → SkillClaw repo)"

if [ ! -d "$GDRIVE_STORE" ]; then
  echo "$LOG_PREFIX ERROR: GDrive store not found at ${GDRIVE_STORE}"
  exit 1
fi

mkdir -p "$SKILLCLAW_REPO"

total_synced=0
total_skipped=0

for agent_dir in "$GDRIVE_STORE"/*/; do
  [ ! -d "$agent_dir" ] && continue
  agent_name=$(basename "$agent_dir")

  # Skip excluded agents
  skip=false
  for skip_agent in $SKIP_AGENTS; do
    if [ "$agent_name" = "$skip_agent" ]; then
      skip=true
      break
    fi
  done
  if [ "$skip" = true ]; then
    echo "$LOG_PREFIX SKIP: ${agent_name} (excluded)"
    continue
  fi

  agent_synced=0
  agent_skipped=0

  for skill_dir in "$agent_dir"/*/; do
    [ ! -d "$skill_dir" ] && continue
    skill_name=$(basename "$skill_dir")
    skill_file="${skill_dir}SKILL.md"

    if [ ! -f "$skill_file" ]; then
      echo "$LOG_PREFIX WARN: ${agent_name}/${skill_name} missing SKILL.md, skipping"
      agent_skipped=$((agent_skipped + 1))
      continue
    fi

    # Copy to SkillClaw repo: skills/{skill-name}/{agent}/SKILL.md
    # This allows SkillClaw to see all agents' versions of each skill
    target_dir="${SKILLCLAW_REPO}/${skill_name}/${agent_name}"
    mkdir -p "$target_dir"

    # Only copy if source is newer or target doesn't exist
    if [ ! -f "${target_dir}/SKILL.md" ] || [ "$skill_file" -nt "${target_dir}/SKILL.md" ]; then
      cp "$skill_file" "${target_dir}/SKILL.md"
      agent_synced=$((agent_synced + 1))
    else
      agent_skipped=$((agent_skipped + 1))
    fi
  done

  if [ "$agent_synced" -gt 0 ]; then
    echo "$LOG_PREFIX ${agent_name}: ${agent_synced} skills synced, ${agent_skipped} unchanged"
  fi
  total_synced=$((total_synced + agent_synced))
  total_skipped=$((total_skipped + agent_skipped))
done

echo "$LOG_PREFIX DONE: ${total_synced} skills synced, ${total_skipped} unchanged"
