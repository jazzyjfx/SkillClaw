#!/bin/bash
# run-pipeline.sh — Full SkillClaw evolution pipeline
# Cron: 15 8 * * * on VPS host
# Flow: convert → evolve → deploy to GDrive + diffs → exit
# Jazzy reads diffs from GDrive for Discord approval

set -euo pipefail

LOG="/var/log/skillclaw/pipeline-$(date +%Y%m%d-%H%M%S).log"
mkdir -p /var/log/skillclaw

log() {
  echo "[$(date -u "+%Y-%m-%d %H:%M:%S UTC")] $1" | tee -a "$LOG"
}

log "=== SkillClaw Pipeline Start ==="

# 1. Convert OpenClaw sessions → SkillClaw format
log "Step 1: Converting sessions..."
docker exec skillclaw python3 /data/converter/convert.py 2>&1 | tee -a "$LOG"
log "Conversion complete."

# 2. Run evolver on converted sessions
log "Step 2: Running evolver..."
docker exec skillclaw python3 -m evolve_server --once 2>&1 | tee -a "$LOG"
log "Evolution complete."

# 3. Deploy evolved skills to GDrive + generate diffs
log "Step 3: Deploying to GDrive + generating diffs..."
docker exec skillclaw bash /data/deploy/deploy_skills.sh 2>&1 | tee -a "$LOG"
log "Deploy complete."

# 4. Summary
DIFF_COUNT=$(ls /mnt/gdrive/shared/common/evolved-diffs/*.md 2>/dev/null | wc -l)
log "Pipeline done. $DIFF_COUNT skill(s) pending approval."
log "=== SkillClaw Pipeline End ==="
