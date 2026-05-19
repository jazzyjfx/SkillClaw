#!/bin/bash
set -euo pipefail

# Host-side script: Copy agent skills from all agent containers → GDrive central store
# Runs on the VPS host (has docker access)
# Schedule via cron: 0 6 * * * /home/jazzy/docker/skillclaw/cron/sync-agent-skills.sh

GDRIVE_STORE="/mnt/gdrive/shared/common/agent-skills"
LOG_PREFIX="[host:sync-skills]"
SKIP_AGENTS="forge"
timestamp=$(date '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX Starting at $timestamp"

mkdir -p "$GDRIVE_STORE"

# Dynamically discover all agent containers
agent_dirs=$(find /home/jazzy/docker/ -maxdepth 1 -type d -name 'openclaw-*' 2>/dev/null || true)

if [ -z "$agent_dirs" ]; then
  echo "$LOG_PREFIX WARN: No openclaw-* directories found"
  exit 0
fi

total_skills=0
agents_synced=0

for agent_dir in $agent_dirs; do
  agent_name=$(basename "$agent_dir" | sed 's/^openclaw-//')

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

  container="openclaw-${agent_name}"

  # Check if container is running
  if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "$LOG_PREFIX WARN: ${container} not running, skipping"
    continue
  fi

  skill_count=0
  agent_out="${GDRIVE_STORE}/${agent_name}"

  # Workspace skills: /home/node/.openclaw/workspace/skills/
  while IFS= read -r skill_path; do
    [ -z "$skill_path" ] && continue
    skill_name=$(basename "$(dirname "$skill_path")")
    mkdir -p "${agent_out}/${skill_name}"
    docker cp "${container}:${skill_path}" "${agent_out}/${skill_name}/SKILL.md"
    skill_count=$((skill_count + 1))
  done < <(docker exec "$container" find /home/node/.openclaw/workspace/skills/ -name "SKILL.md" 2>/dev/null || true)

  # App skills: /home/node/.openclaw/skills/
  while IFS= read -r skill_path; do
    [ -z "$skill_path" ] && continue
    skill_name=$(basename "$(dirname "$skill_path")")
    mkdir -p "${agent_out}/${skill_name}"
    docker cp "${container}:${skill_path}" "${agent_out}/${skill_name}/SKILL.md"
    skill_count=$((skill_count + 1))
  done < <(docker exec "$container" find /home/node/.openclaw/skills/ -name "SKILL.md" 2>/dev/null || true)

  echo "$LOG_PREFIX ${agent_name}: ${skill_count} skills synced"
  total_skills=$((total_skills + skill_count))
  agents_synced=$((agents_synced + 1))
done

echo "$LOG_PREFIX DONE: ${total_skills} skills from ${agents_synced} agents synced to ${GDRIVE_STORE}"
