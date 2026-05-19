# SkillClaw — Quick Reference

Skill evolution system that reads agent session transcripts, identifies reusable patterns, and evolves them into installable skills.

**Container:** `skillclaw` | **Model:** `xiaomi/mimo-v2.5` | **Storage:** Local + GDrive

---

## Pipeline at a Glance

```
Sessions → Convert → Evolve (LLM) → Deploy (GDrive + diffs) → Review → Approve/Reject
```

| Step | When | Script |
|------|------|--------|
| Sync agent skills → GDrive | 01:30 UTC | `cron/sync-agent-skills.sh` |
| Convert sessions | 02:00 UTC | `cron/convert-sessions.sh` |
| Evolve | Auto (post-convert/restart) | Built-in |
| Deploy + diffs | Auto (post-evolve) | `deploy/deploy_skills.sh` |
| Approve | Manual | `deploy/approve-skill.sh <skill> "<agents>"` |
| Reject | Manual | `deploy/reject-skill.sh <skill> [reason]` |

---

## Key Paths

| What | Where |
|------|-------|
| VPS host dir | `/home/jazzy/docker/skillclaw/` |
| Container code | `/opt/skillclaw/` |
| Container data | `/data/local-share/openclaw-fleet/` |
| Evolved skills (GDrive) | `/mnt/gdrive/shared/common/evolved-skills/` |
| Diff summaries (GDrive) | `/mnt/gdrive/shared/common/evolved-diffs/` |
| Central skill store (GDrive) | `/mnt/gdrive/shared/common/agent-skills/` |
| Agent map | `/home/jazzy/docker/skillclaw/deploy/agent-map.json` |

---

## Quick Commands

```bash
# Approve a skill for specific agents
approve-skill.sh discord "jazzy,forge,atlas"

# Reject a skill
reject-skill.sh discord "Too generic"

# Run full pipeline manually
run-pipeline.sh

# Check daily report
cat /mnt/gdrive/shared/common/evolved-skills/DAILY-REPORT.md

# Review diffs
ls /mnt/gdrive/shared/common/evolved-diffs/
```

---

## Max Tokens by Stage

| Stage | max_tokens |
|-------|------------|
| Session Judge | 4096 |
| Execution | 8192 |
| Skill Verifier | 2000 |
| Summarizer | 100000 |

---

## Key Gotchas

1. **Reasoning models eat tokens** — MiMo v2.5 thinking tokens consume budget. Session judge was fixed from 1200 → 4096.
2. **Only SKILL.md is evolved** — Companion files preserved but never updated by evolver.
3. **Config mismatch** — `config.yaml` says `/data/skills` but evolver writes to `/data/local-share/openclaw-fleet/skills/`.
4. **Multiple max_tokens sites** — Don't assume one value; each pipeline stage has its own.
5. **Forge excluded** — Converter skips forge sessions.

---

## Full Documentation

→ [PROJECT.md](./PROJECT.md) — Complete architecture, scripts reference, configuration, known issues, lessons learned, and roadmap.
