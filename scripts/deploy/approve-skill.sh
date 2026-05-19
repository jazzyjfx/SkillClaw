#!/bin/bash
# approve-skill.sh — Deploy an approved evolved skill to target agents + central store
# Usage: approve-skill.sh <skill_name> <target_agents_comma_separated>
# Copies ENTIRE skill directory (not just SKILL.md)

set -euo pipefail

SKILL="$1"
TARGETS="$2"
EVOLVED_DIR="/mnt/gdrive/shared/common/evolved-skills"
CENTRAL_DIR="/mnt/gdrive/shared/common/agent-skills"
DIFF_DIR="/mnt/gdrive/shared/common/evolved-diffs"
AGENTS_DIR="/home/jazzy/docker"
BACKUP_DIR="/mnt/gdrive/shared/common/agent-skills-backup"
DATE=$(date +%Y%m%d-%H%M%S)

if [ -z "$SKILL" ] || [ -z "$TARGETS" ]; then
  echo "Usage: approve-skill.sh <skill_name> <target_agents>"
  exit 1
fi

if [ ! -d "$EVOLVED_DIR/$SKILL" ]; then
  echo "ERROR: Evolved skill not found: $EVOLVED_DIR/$SKILL"
  exit 1
fi

echo "=== Approving skill: $SKILL ==="
echo "Target agents: $TARGETS"

# 1. Backup existing skill in central store (if exists)
if [ -d "$CENTRAL_DIR/$SKILL" ]; then
  mkdir -p "$BACKUP_DIR/$SKILL"
  cp -r "$CENTRAL_DIR/$SKILL" "$BACKUP_DIR/$SKILL.$DATE"
  echo "Backed up existing skill to $BACKUP_DIR/$SKILL.$DATE"
else
  echo "No existing skill in central store — first deployment"
fi

# 2. Deploy to central store (entire directory)
mkdir -p "$CENTRAL_DIR/$SKILL"
cp -r "$EVOLVED_DIR/$SKILL/"* "$CENTRAL_DIR/$SKILL/"
echo "Deployed to central store: $CENTRAL_DIR/$SKILL/"

# 3. Copy approved skill back to SkillClaw evolver skill base
EVOLVER_SKILL_DIR="/data/local-share/openclaw-fleet/skills/$SKILL"
docker exec skillclaw mkdir -p "$EVOLVER_SKILL_DIR"
# Copy entire directory into container
for f in "$EVOLVED_DIR/$SKILL/"*; do
  fname=$(basename "$f")
  if [ -d "$f" ]; then
    docker cp "$f" "skillclaw:$EVOLVER_SKILL_DIR/"
  else
    docker cp "$f" "skillclaw:$EVOLVER_SKILL_DIR/$fname"
  fi
done
echo "Updated SkillClaw evolver baseline: $EVOLVER_SKILL_DIR/"

# 4. Deploy to target agents (entire directory)
IFS="," read -ra AGENTS <<< "$TARGETS"
DEPLOYED=0
for agent in "${AGENTS[@]}"; do
  agent=$(echo "$agent" | xargs)
  dir="$AGENTS_DIR/openclaw-$agent/workspace/skills/$SKILL"
  if [ -d "$AGENTS_DIR/openclaw-$agent/workspace/skills" ]; then
    mkdir -p "$dir"
    cp -r "$EVOLVED_DIR/$SKILL/"* "$dir/"
    echo "Deployed -> $agent"
    DEPLOYED=$((DEPLOYED + 1))
  else
    echo "Skipped -> $agent (no skills directory)"
  fi
done

# 5. Clean up diff
rm -f "$DIFF_DIR/$SKILL.md"
echo "Cleaned up diff: $DIFF_DIR/$SKILL.md"

echo ""
echo "=== Done: $SKILL deployed to $DEPLOYED agent(s) ==="
