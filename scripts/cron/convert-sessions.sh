#!/bin/bash
# Run SkillClaw session converter
# Scheduled: 02:00 UTC daily

set -e

LOG_PREFIX="[skillclaw-convert]"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S')

echo "$LOG_PREFIX Starting converter at $TIMESTAMP"

# Run converter inside the container
docker exec skillclaw python3 /data/converter/convert.py 2>&1

echo "$LOG_PREFIX Converter completed at $(date -u '+%Y-%m-%d %H:%M:%S')"
