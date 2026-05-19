# SkillClaw — Skill Evolution System

> **Owner:** Jazzy (CTO / Infrastructure)
> **Status:** Active — v1 (single-file evolution)
> **Location:** NetCup VPS — Docker container `skillclaw`
> **Last Updated:** 2026-05-19

---

## Overview

SkillClaw is an automated skill evolution system that reads OpenClaw agent session transcripts, identifies reusable patterns, and evolves them into installable skills. It runs as a standalone Docker container on the NetCup VPS and integrates with the shared Google Drive workspace for skill distribution.

**Core value:** Agents learn from their own work. Patterns that emerge across sessions get codified into skills that improve future performance fleet-wide.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    NetCup VPS (Docker)                       │
│                                                              │
│  ┌──────────────┐    ┌──────────────────────────────────┐   │
│  │  openclaw-*   │───▶│  cron: sync-agent-skills.sh     │   │
│  │  containers   │    │  (01:30 UTC — containers→GDrive) │   │
│  └──────────────┘    └──────────┬───────────────────────┘   │
│                                  │                           │
│                                  ▼                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              skillclaw container                      │   │
│  │                                                       │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │  Converter   │─▶│   Evolver    │─▶│  Deployer  │  │   │
│  │  │ (sessions→   │  │ (LLM-driven  │  │ (GDrive +  │  │   │
│  │  │  JSON)       │  │  evolution)  │  │  diffs)    │  │   │
│  │  └─────────────┘  └──────────────┘  └────────────┘  │   │
│  │                                                       │   │
│  │  LLM: xiaomi/mimo-v2.5 via OpenRouter                │   │
│  │  Storage: /data/local-share/openclaw-fleet/           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                  │                           │
│                                  ▼                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Google Drive (FUSE mount)                 │   │
│  │                                                       │   │
│  │  shared/common/agent-skills/    ← Central store       │   │
│  │  shared/common/evolved-skills/  ← Evolved output      │   │
│  │  shared/common/evolved-diffs/   ← Diff summaries      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                  │                           │
│                                  ▼                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Jazzy reviews diffs → approve-skill.sh / reject      │   │
│  │  Approved → central store + target agent containers   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Container Details

| Property | Value |
|----------|-------|
| Container name | `skillclaw` |
| Image | `skillclaw-skillclaw` |
| Ports | `127.0.0.1:8080->8080`, `127.0.0.1:8787->8787` |
| Model | `xiaomi/mimo-v2.5` via OpenRouter |
| Storage backend | Local (`/data/local-share`) |
| Group ID | `openclaw-fleet` |

---

## Pipeline Flow

The full pipeline runs daily and follows this sequence:

```
1. SYNC     ──▶  Agent containers → GDrive central store (01:30 UTC)
2. CONVERT  ──▶  Session .jsonl → SkillClaw format (02:00 UTC)
3. EVOLVE   ──▶  LLM-driven skill extraction & evolution (auto after convert)
4. DEPLOY   ──▶  Evolved skills → GDrive + diff generation
5. REVIEW   ──▶  Jazzy reads diffs from /mnt/gdrive/shared/common/evolved-diffs/
6. APPROVE  ──▶  Deploy to central store + target agent containers
    or REJECT ──▶  Remove from evolved-skills + SkillClaw storage
```

### Step Details

| Step | Script | Trigger | Description |
|------|--------|---------|-------------|
| Sync | `sync-agent-skills.sh` | Cron 01:30 UTC | Copies skills from all `openclaw-*` containers to GDrive central store |
| Convert | `convert-sessions.sh` | Cron 02:00 UTC | Converts OpenClaw `.jsonl` session transcripts to SkillClaw format |
| Evolve | *(automatic)* | After restart or convert | LLM analyzes sessions, extracts patterns, evolves skills |
| Deploy | `deploy_skills.sh` | After evolve | Copies evolved skills to GDrive, generates diff summaries |
| Approve | `approve-skill.sh` | Manual (Jazzy) | Deploys approved skill to central store + target agents |
| Reject | `reject-skill.sh` | Manual (Jazzy) | Removes rejected skill from evolved output |

---

## File Layout

### VPS Host: `/home/jazzy/docker/skillclaw/`

```
skillclaw/
├── config/
│   └── config.yaml                 # SkillClaw configuration
├── deploy/
│   ├── deploy_skills.sh            # Evolved skills → GDrive + diffs
│   ├── approve-skill.sh            # Approve: central store + agents
│   ├── reject-skill.sh             # Reject: remove evolved + SkillClaw storage
│   ├── sync_agent_skills.sh        # GDrive → SkillClaw repo (reverse sync)
│   ├── report_skills.sh            # Daily report generator
│   ├── run-pipeline.sh             # Full pipeline: convert → evolve → deploy
│   └── agent-map.json              # Domain → agent targeting map
├── cron/
│   ├── sync-agent-skills.sh        # Host-side: containers → GDrive (01:30)
│   ├── convert-sessions.sh         # Runs converter (02:00)
│   └── skillclaw-daily.sh          # Legacy full pipeline
└── session_judge.py                # (bind-mounted into container)
```

### Container: `/opt/skillclaw/` and `/data/`

```
/opt/skillclaw/
├── evolve_server/
│   ├── core/llm_client.py          # LLM API client
│   ├── pipeline/
│   │   ├── session_judge.py        # Scores sessions for skill potential (max_tokens=4096)
│   │   ├── execution.py            # Skill merge/evolve/create (max_tokens=8192)
│   │   ├── skill_verifier.py       # Validates evolved skills (max_tokens=2000)
│   │   └── summarizer.py           # Session summaries (max_tokens=100000)
│   ├── engines/
│   │   ├── workflow.py             # Session pipeline (single-file only)
│   │   ├── agent.py                # Agent-driven engine (multi-file)
│   │   └── agent_workspace.py      # Multi-file bundle support
│   └── storage/oss_helpers.py      # Storage layer
├── skillclaw/
│   ├── skill_bundle.py             # Multi-file bundle library
│   └── skill_hub.py                # Push/pull to cloud
└── .env                            # Environment variables

/data/
├── converter/
│   ├── convert.py                  # Session converter
│   ├── config.py                   # Converter config
│   └── processed.json              # Dedup tracking
├── local-share/openclaw-fleet/
│   ├── sessions/{agent}/{id}.json  # Converted sessions
│   └── skills/{skill}/SKILL.md     # Evolved skills output
└── skills/                         # (config points here but empty — see Known Issues)
```

### Google Drive (Shared Workspace)

```
/mnt/gdrive/shared/common/
├── agent-skills/{skill}/SKILL.md       # Live agent skills (central store)
├── evolved-skills/{skill}/SKILL.md     # Deployed evolved skills awaiting review
├── evolved-diffs/{skill}.md            # Diff summaries for Jazzy's review
└── agent-skills-backup/                # Backups before deploy
```

---

## Scripts Reference

### `deploy_skills.sh`
- **Purpose:** Copy evolved skills to GDrive + generate diff summaries
- **Reads from:** `/data/local-share/openclaw-fleet/skills/`
- **Compares against:** `/mnt/gdrive/shared/common/agent-skills/` (live baseline)
- **Writes to:** `/mnt/gdrive/shared/common/evolved-skills/` and `evolved-diffs/`
- **Skip logic:** Skips if GDrive copy is newer
- **Diff output:** Line counts, section changes, raw unified diff

### `approve-skill.sh`
- **Args:** `<skill_name> <target_agents_comma_separated>`
- **Example:** `approve-skill.sh discord "jazzy,forge,atlas"`
- **Actions:**
  1. Backs up existing skill to `agent-skills-backup/`
  2. Deploys to central store (`agent-skills/`)
  3. Updates SkillClaw baseline
  4. Deploys to target agent containers at `/home/jazzy/docker/openclaw-{agent}/workspace/skills/{skill}/`
  5. Cleans up diff file
- **Note:** Copies FULL directory (companion files preserved)

### `reject-skill.sh`
- **Args:** `<skill_name> [reason]`
- **Actions:**
  1. Removes from GDrive `evolved-skills/`
  2. Removes from SkillClaw local storage inside container
  3. Cleans up diff file
- **Does NOT touch:** Central store (`agent-skills/`)

### `sync-agent-skills.sh` (host-side cron)
- **Schedule:** 01:30 UTC daily
- **Action:** Copies skills from all `openclaw-*` containers → GDrive `agent-skills/`
- **Note:** Dynamic container discovery, skips `forge`

### `convert-sessions.sh` (cron)
- **Schedule:** 02:00 UTC daily
- **Action:** Runs `convert.py` inside skillclaw container

### `run-pipeline.sh`
- **Action:** Full pipeline — convert → evolve → deploy + diffs
- **Logs:** `/var/log/skillclaw/`

### `report_skills.sh`
- **Action:** Generates daily report at `evolved-skills/DAILY-REPORT.md`

### `sync_agent_skills.sh` (deploy/ — reverse sync)
- **Action:** Copies from GDrive → SkillClaw repo (reverse direction)
- **Note:** NOT part of the standard flow — may be legacy

---

## Agent Map

The `agent-map.json` file maps skill domains to target agents for automated deployment:

```json
{
  "sysadmin":          ["jazzy"],
  "devops":            ["jazzy"],
  "crypto":            ["dex"],
  "forex":             ["vector"],
  "mt5":               ["vector"],
  "mql5":              ["vector"],
  "ml":                ["nova"],
  "data-science":      ["nova"],
  "research":          ["lumi"],
  "intelligence":      ["lumi"],
  "compliance":        ["axiom"],
  "project-management":["atlas"],
  "fleet":             ["dispatch"],
  "personal":          ["jim"],
  "general":           ["atlas","axiom","dex","dispatch","forge","jazzy","jim","lumi","nova","prime","vector"]
}
```

---

## Configuration

### `.env` Key Variables

| Variable | Value | Notes |
|----------|-------|-------|
| `EVOLVE_MODEL` | `xiaomi/mimo-v2.5` | LLM model for evolution |
| `EVOLVE_LLM_MAX_TOKENS` | `5000` | Global default — overridden per-pipeline stage |
| `EVOLVE_LLM_TEMPERATURE` | `0.4` | |
| `LLM_CALL_DELAY` | `3` | Seconds between LLM calls |
| `EVOLVE_INTERVAL` | `43200` | 12 hours between evolution cycles |
| `EVOLVE_PUBLISH_MODE` | `direct` | |
| `EVOLVE_USE_SKILL_VERIFIER` | `1` | Enable skill verification step |
| `EVOLVE_REJECT_REWRITE` | `1` | Allow rewrite on rejection |
| `EVOLVE_STORAGE_BACKEND` | `local` | |
| `EVOLVE_STORAGE_LOCAL_ROOT` | `/data/local-share` | |
| `SKILLCLAW_SHARING_BACKEND` | `local` | |
| `SKILLCLAW_SHARING_LOCAL_ROOT` | `/data/local-share` | |

### `config.yaml` Key Settings

| Setting | Value | Notes |
|---------|-------|-------|
| `sharing.local_root` | `/data/local-share` | |
| `sharing.group_id` | `openclaw-fleet` | |
| `skills.dir` | `/data/skills` | **Empty** — evolver actually writes to `/data/local-share/openclaw-fleet/skills/` |
| `publish_mode` | `direct` | |

### Max Tokens by Pipeline Stage

| Stage | File | max_tokens |
|-------|------|------------|
| Session Judge | `session_judge.py` | 4096 |
| Execution | `execution.py` | 8192 |
| Skill Verifier | `skill_verifier.py` | 2000 |
| Summarizer | `summarizer.py` | 100000 |

---

## Converter

The converter transforms raw OpenClaw session transcripts into SkillClaw-compatible format.

| Property | Detail |
|----------|--------|
| **Input** | OpenClaw `.jsonl` session transcripts from `/openclaw-sessions/{agent}/` |
| **Output** | `/data/local-share/openclaw-fleet/sessions/{agent}/{id}.json` |
| **Dedup** | `processed.json` tracks by original session ID |
| **Hierarchy** | Subagent sessions merged into parent session ID (`resolve_root_session`) |
| **Skills extraction** | Scans system messages for `<available_skills>` blocks |
| **Filtering** | Status `done`/`timeout` + `endedAt` present + no lock file + not excluded (forge) |
| **Backfill** | `--backfill` flag ignores processed state |

---

## Evolver

The evolver is the LLM-driven core that analyzes converted sessions and produces evolved skills.

### Pipeline Stages

1. **Session Judge** — Scores each session for skill potential (rejects low-value sessions)
2. **Grouping** — Groups related sessions by domain/topic
3. **Execution** — Merges, evolves, or creates skills from grouped sessions
4. **Skill Verifier** — Validates evolved skills for correctness and completeness
5. **Output** — Writes to `/data/local-share/openclaw-fleet/skills/{skill}/SKILL.md`

### Cycle Behavior

- Processes all converted sessions each cycle
- Groups by domain → evolves → uploads
- Runs automatically after container restart or on internal schedule (`EVOLVE_INTERVAL=43200s` / 12 hours)

---

## Cron Schedule

| Time (UTC) | Script | What it does |
|------------|--------|--------------|
| 01:30 | `sync-agent-skills.sh` | Agent containers → GDrive central store |
| 02:00 | `convert-sessions.sh` | Convert sessions inside skillclaw |
| 03:00 | `sync-agent-workspaces.sh` | Agent workspace sync |
| 04:00 | `backup-fleet.sh` | Fleet backup |
| 05:05 | rclone flush nudge | Rclone cache flush |
| 06:00 | `daily-health-check.sh` | Health check |

> **Note:** Lobster cron (08:15) was removed. Evolver runs automatically after container restart or on its internal schedule (`EVOLVE_INTERVAL=43200s`).

---

## Review & Approval Workflow

```
evolved-diffs/{skill}.md
        │
        ▼
   Jazzy reviews
        │
   ┌────┴────┐
   │         │
   ▼         ▼
APPROVE    REJECT
   │         │
   ▼         ▼
approve-   reject-
skill.sh   skill.sh
   │         │
   ▼         ▼
Central    Remove from
store +    evolved-skills +
agents     SkillClaw storage
```

### Approval Flow
1. Jazzy reads diff from `/mnt/gdrive/shared/common/evolved-diffs/{skill}.md`
2. If approved: `approve-skill.sh {skill} "{agent1},{agent2},..."`
3. Script backs up existing → deploys to central store → deploys to target containers
4. Diff file cleaned up

### Rejection Flow
1. Jazzy reads diff, decides to reject
2. `reject-skill.sh {skill} [reason]`
3. Script removes from evolved-skills and SkillClaw storage
4. Central store (agent-skills/) is NOT touched

---

## Known Issues & Gotchas

| # | Issue | Impact | Status |
|---|-------|--------|--------|
| 1 | `max_tokens=1200` was too low for reasoning model — MiMo v2.5 reasoning tokens consumed entire budget, leaving 0 content tokens | Evolver produced no output | **Fixed** — bumped to 4096 in `session_judge.py` |
| 2 | Multi-file skills: Evolver only evolves `SKILL.md`. Companion files (scripts/, references/) preserved but never evolved | Companion files go stale | **Open** — infrastructure exists in `skill_bundle.py`/`agent_workspace.py` but not wired to session pipeline |
| 3 | Manifest clobbering: EvolveServer writes SKILL.md-only manifest entries | Companion file references lost if SkillHub previously pushed full bundle metadata | **Open** |
| 4 | `/data/skills` config path empty | Config says `skills.dir=/data/skills` but evolver writes to `/data/local-share/openclaw-fleet/skills/` | **Open** — config mismatch |
| 5 | Pipeline speed: 181 sessions took 73 minutes | Daily runs (fewer sessions) should be under 30 min target | **Monitoring** |
| 6 | Vector low count: Only 1 root session from 17 files | Most were subagent sessions merged into parent | **Expected** — subagent merge working as designed |
| 7 | Heredoc SSH issues | Writing scripts via SSH heredocs can mangle quotes | **Workaround** — use SCP or base64 encoding |
| 8 | Multiple `max_tokens` sites | Different values across `session_judge.py` (4096), `execution.py` (8192), `skill_verifier.py` (2000), `summarizer.py` (100000) | **By design** — don't assume one value applies everywhere |

---

## Lessons Learned

| # | Lesson | Context |
|---|--------|---------|
| 1 | **Validate before presenting (D11)** — Subagent claimed `max_tokens=1200` was root cause; James found counter-example immediately. Cross-check claims against actual logs. | Evolver debugging |
| 2 | **Reasoning models need more token budget** — Thinking tokens eat into `completion_tokens` budget. If `max_completion_tokens` is too low, content is empty. | MiMo v2.5 token limits |
| 3 | **Don't assume code paths are uniform** — Multiple LLM call sites with different `max_tokens` values. Read the actual code. | Pipeline stage analysis |
| 4 | **Heredocs in SSH mangle quotes** — Use file transfer instead. | Script deployment |
| 5 | **Subagent timeout events can be missed** — Main session must yield properly. | Session management |
| 6 | **Session hierarchy matters** — Subagent sessions are too small to evolve meaningful skills. Merging into parent sessions produces better evolution candidates. | Converter design |

---

## Roadmap

### Immediate (v1 stabilization)
- [ ] Monitor current evolver cycle with `max_tokens` fix
- [ ] Verify GDrive deploy works end-to-end
- [ ] Test approve/reject workflow with a real evolved skill
- [ ] Fix `/data/skills` config mismatch

### Short-term
- [ ] Wire up `agent-map.json` for automated domain-based targeting
- [ ] Automated approval for high-confidence skills (with safety guardrails)

### Medium-term (v2)
- [ ] Multi-file skill support — evolve companion files, not just SKILL.md
- [ ] Skill versioning and rollback
- [ ] Cross-agent skill dependency tracking

---

## Related Documentation

- **Skill Evolver Approval Skill:** `~/.openclaw/workspace/skills/skill-evolver-approval/SKILL.md`
- **Agent Skills Central Store:** `/mnt/gdrive/shared/common/agent-skills/`
- **Evolved Diffs:** `/mnt/gdrive/shared/common/evolved-diffs/`
- **Agent Map:** `/home/jazzy/docker/skillclaw/deploy/agent-map.json`
