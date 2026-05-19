#!/bin/bash
# reject-skill.sh — Reject an evolved skill: remove from evolved dirs + SkillClaw local storage
# Usage: reject-skill.sh <skill_name> [reason]
#
# At rejection time, the evolved skill is ONLY in evolved-skills/ (GDrive),
# never in agent-skills/ (central store). This script:
#   1. Removes the evolved skill from evolved-skills/
#   2. Removes the evolved skill from SkillClaw local storage (container)
#   3. Cleans up the diff file from evolved-diffs/
#   4. Logs what it did

set -euo pipefail

EVOLVED_DIR="/mnt/gdrive/shared/common/evolved-skills"
DIFF_DIR="/mnt/gdrive/shared/common/evolved-diffs"
SKILLCLAW_LOCAL="/data/local-share/openclaw-fleet/skills"
LOG_PREFIX="[skillclaw:reject]"

# --- Args ---
SKILL="${1:-}"
REASON="${2:-Rejected by operator}"

if [ -z "$SKILL" ]; then
  echo "Usage: reject-skill.sh <skill_name> [reason]"
  exit 1
fi

echo "$LOG_PREFIX Rejecting skill: $SKILL"
echo "$LOG_PREFIX Reason: $REASON"

# 1. Remove evolved skill directory (GDrive)
if [ -d "$EVOLVED_DIR/$SKILL" ]; then
  rm -rf "$EVOLVED_DIR/$SKILL"
  echo "$LOG_PREFIX Removed: $EVOLVED_DIR/$SKILL/"
else
  echo "$LOG_PREFIX Already gone: $EVOLVED_DIR/$SKILL/"
fi

# 2. Remove evolved skill from SkillClaw local storage (inside container)
if docker exec skillclaw test -d "$SKILLCLAW_LOCAL/$SKILL" 2>/dev/null; then
  docker exec skillclaw rm -rf "$SKILLCLAW_LOCAL/$SKILL"
  echo "$LOG_PREFIX Removed: $SKILLCLAW_LOCAL/$SKILL/ (SkillClaw container)"
else
  echo "$LOG_PREFIX Already gone: $SKILLCLAW_LOCAL/$SKILL/ (SkillClaw container)"
fi

# 3. Remove diff file
if [ -f "$DIFF_DIR/$SKILL.md" ]; then
  rm -f "$DIFF_DIR/$SKILL.md"
  echo "$LOG_PREFIX Removed: $DIFF_DIR/$SKILL.md"
else
  echo "$LOG_PREFIX Already gone: $DIFF_DIR/$SKILL.md"
fi

# 4. Summary
echo ""
echo "$LOG_PREFIX === Done: $SKILL rejected ==="
