# Implementation Plan: SkillClaw Evolver Integration (No-Proxy)

Branch: skillclaw-evolver | Date: 2026-05-13 | Spec: spec.md

## Technical Context

- **Language:** Python 3.12 (converter script), Bash (scripts), Docker Compose (evolver)
- **Dependencies:** SkillClaw v0.4.0 (already installed in container)
- **Storage:** Local volumes (skills, share, config, logs) + GDrive mount
- **Testing:** Manual verification (converter output, evolver skills)
- **Target Platform:** NetCup VPS, Docker
- **LLM:** MiMo v2.5 via OpenRouter (xiaomi/mimo-v2.5) (`sk-or-…1cd2`)
- **Constraints:** No proxy, no sandbox changes, review before deploy
- **Exclusions:** Forge excluded entirely (skills + sessions). BMAD Method suite is a third-party methodology with ~100+ heavily nested duplicate skills, not suitable for evolution.

## Agents In Scope

10 agents: atlas, axiom, dex, dispatch, jazzy, jim, lumi, nova, prime, vector

Forge is excluded.

## Architecture

```
All Agent Skills (one-time seed + daily sync) — 10 agents, no Forge
  ~/.openclaw/agents/*/workspace/skills/
  ~/.openclaw/agents/*/.openclaw/skills/
        │
        ▼
  ┌─────────────────┐
  │  Seed/Sync       │  One-time seed + daily cron
  │  (10 agents)     │  Copies to evolver storage + GDrive
  └────────┬────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
  Evolver      GDrive
  Storage      /mnt/gdrive/shared/common/agent-skills/
  /data/       (daily snapshot of all agent skills)
  local-share/


OpenClaw Session Files (.jsonl) + sessions.json — 10 agents, no Forge
  ~/.openclaw/agents/*/sessions/*.jsonl
        │
        ▼
  ┌─────────────────┐
  │  Converter       │  Python script, runs as cron
  │  .jsonl → .json  │  Checks sessions.json for completion
  │                  │  Uses lock files as secondary check
  │                  │  Skips Forge sessions
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Local Storage   │  /data/local-share/openclaw-fleet/sessions/
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Evolver Server  │  Existing skillclaw container
  │  (workflow mode) │  Reads sessions → evolves/creates skills
  │  (direct publish)│  Publishes immediately after LLM verification
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Skills Output   │  /data/local-share/openclaw-fleet/skills/
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Deploy Script   │  Copies evolved skills to GDrive for review
  └────────┬────────┘
           │
           ▼
  GDrive: /mnt/gdrive/shared/common/evolved-skills/
```

## Data Model

### OpenClaw Session (.jsonl)
Each line is a message object:
```json
{"role": "user", "content": "...", "timestamp": "..."}
{"role": "assistant", "content": [{"type": "text", "text": "..."}, {"type": "toolCall", "id": "...", "name": "exec", "arguments": {...}}], "timestamp": "..."}
```

### SkillClaw Session (.json) — ACTUAL output format
```json
{
  "session_id": "string",
  "agent": "string",
  "source": "openclaw",
  "convertedAt": "ISO-8601",
  "sessionMeta": {},
  "turns": [
    {
      "turn_num": 1,
      "prompt_text": "user message",
      "response_text": "agent response",
      "read_skills": ["skill-name"],
      "modified_skills": ["skill-name"],
      "tool_calls": [{"name": "exec", "arguments": {...}}],
      "tool_results": [{"name": "exec", "output": "...(truncated 5000)"}],
      "tool_errors": [{"name": "exec", "error": "...", "exit_code": 1, "status": "failed"}],
      "prm_score": null
    }
  ],
  "messageCount": 42,
  "turnCount": 10,
  "aggregate": {
    "rollout_count": 1,
    "scores": [],
    "mean_score": null,
    "success_count": 0,
    "fail_count": 0,
    "stability": null
  }
}
```

**Note:** No `parentSessionId` field yet (pending Task 1). Output written to `/data/local-share/openclaw-fleet/sessions/{agent}/{session_id}.json`.

## File Structure

```
VPS Host:
/home/jazzy/docker/skillclaw/
├── docker-compose.yml          # Existing (modify)
├── config/
│   └── config.yaml             # Existing (modify)
├── converter/
│   ├── convert.py              # DEPLOYED — session converter
│   ├── config.py               # DEPLOYED — config (sessions dir, excluded agents)
│   └── processed.json          # DEPLOYED — dedup tracking
├── deploy/
│   ├── deploy_skills.sh        # DEPLOYED — skills → GDrive evolved-skills + diffs
│   ├── sync_agent_skills.sh    # DEPLOYED — GDrive → SkillClaw repo (container-side)
│   ├── run-pipeline.sh         # DEPLOYED — full pipeline: convert → evolve → deploy
│   ├── approve-skill.sh        # DEPLOYED — approve: backup → central store → agents
│   └── reject-skill.sh         # DEPLOYED — reject: remove evolved + cleanup (needs evolve-lock)
├── cron/
│   ├── sync-agent-skills.sh    # HOST script: 01:30 UTC, syncs agent skills to GDrive [NOT CREATED]
│   └── convert-sessions.sh     # HOST script: 02:00 UTC, runs converter via docker exec [NOT CREATED]

Jazzy Container:
/home/node/.openclaw/workspace/skillclaw/
├── converter/               # Converter scripts
└── deploy/
    └── report_skills.sh     # Daily report utility
```

## Implementation Tasks

### Task 1: Update Converter — Add parentSessionId [NOT STARTED]
**File:** `/home/jazzy/docker/skillclaw/converter/convert.py` (runs inside container)
- Read `spawnedBy` from `sessions.json` registry for each session
- Walk up parent chain to find root session UUID (if direct parent is also a subagent, keep walking)
- **Planned approach:** Merge subagent transcript INTO parent session (append subagent turns to parent's turn list) rather than adding a separate parentSessionId field. This gives the evolver one coherent conversation.
- Handle missing `spawnedBy` gracefully (legacy sessions → treated as root)
- Handle orphaned subagents (parent not in registry → treat as root)

**Verification:** Convert a test session with known hierarchy, confirm subagent turns appear in parent session.

**Status:** NOT STARTED. Converter currently has no hierarchy awareness. All sessions are treated as independent.

### Task 2: Update Agent Skill Sync — Bidirectional [CONTAINER SCRIPT DONE, HOST SCRIPT NEEDED]
**File:** `/home/jazzy/docker/skillclaw/deploy/sync_agent_skills.sh` (runs inside container)
- **DONE:** Container-side script syncs from GDrive central store → SkillClaw skill repository (`/data/local-share/openclaw-fleet/skills/{skill-name}/{agent}/SKILL.md`)
- **DONE:** Skips Forge
- **DONE:** Only copies if source is newer or target doesn't exist

**HOST script needed:** `/home/jazzy/docker/skillclaw/cron/sync-agent-skills.sh`
- Copies agent skills from `/home/jazzy/docker/openclaw-*/workspace/skills/` → GDrive central store
- Uses direct file operations (not docker exec)
- Detects all agents dynamically, skips Forge

**Verification:** Run host script, confirm skills flow agents → GDrive → SkillClaw repo.

### Task 3: Update Deploy Script — Generate Diffs Only [DONE]
**File:** `/home/jazzy/docker/skillclaw/deploy/deploy_skills.sh` (runs inside SkillClaw container)
- **DONE:** Copies evolved skills from container local storage → GDrive evolved-skills folder
- **DONE:** Generates diff summary comparing evolved vs live agent-skills/ baseline (correct baseline)
- **DONE:** Writes diff summaries to `/mnt/gdrive/shared/common/evolved-diffs/`
- **DONE:** Handles new skills (no baseline) separately
- **DONE:** Skips if evolved copy on GDrive is already newer

**Verification:** Run deploy, confirm GDrive evolved-skills updated with diffs.

### Task 4: Approval Flow — Simplified Architecture [SCRIPTS DEPLOYED, CRON PENDING]

**Architecture:** VPS script (pipeline) + Jazzy Discord session (approval) + VPS scripts (deploy/reject)

No Lobster. No pending-approval.json. No resume tokens.

#### Pipeline Script (VPS host) [DONE]
**File:** `/home/jazzy/docker/skillclaw/deploy/run-pipeline.sh`

- **DONE:** Single script runs full pipeline: convert → evolve → deploy to GDrive + diffs
- **DONE:** Logs to `/var/log/skillclaw/`
- **DONE:** Reports diff count at end
- **NOT IN CRON** yet

#### Jazzy Approval Flow (Discord) [SCRIPTS DONE, FLOW NOT TESTED]

Triggered after pipeline completes (Jazzy reads diffs from GDrive).

1. Read diffs: `ls /mnt/gdrive/shared/common/evolved-diffs/`
2. For each skill, categorize by domain → determine target agents:
  - **Sysadmin/DevOps** → Jazzy only
  - **Crypto** → Dex
  - **Forex/MT5** → Vector
  - **Data Science/ML** → Nova
  - **Research** → Lumi
  - **Compliance** → Axiom
  - **Project Management** → Atlas
  - **Fleet Management** → Dispatch
  - **Personal** → Jim only
  - **General** → all 11 agents (incl. Forge)
3. Present each skill on Discord with diff summary + target agents + risk
4. James approves/rejects
5. On approve: `ssh vps '/home/jazzy/docker/skillclaw/deploy/approve-skill.sh {skill} {targets}'`
6. On reject: `ssh vps '/home/jazzy/docker/skillclaw/deploy/reject-skill.sh {skill} "{reason}"'`

#### Scripts [ALL DEPLOYED TO CONTAINER]

| Script | Location (VPS) | Purpose | Status |
|--------|---------------|---------|--------|
| `run-pipeline.sh` | `/home/jazzy/docker/skillclaw/deploy/` | Full pipeline: convert → evolve → deploy to GDrive + diffs | DONE |
| `approve-skill.sh` | `/home/jazzy/docker/skillclaw/deploy/` | Approve: backup dir → central store → evolver baseline → target agents → cleanup | DONE |
| `reject-skill.sh` | `/home/jazzy/docker/skillclaw/deploy/` | Reject: backup dir → revert/remove dir → cleanup | DONE (needs evolve-lock fix) |

**Known issue with reject script:** Current reject removes evolved skill from local storage and GDrive, but does NOT apply an evolve-lock. Evolver will recreate the same skill on next cycle. Need to add a `.evolve-lock` file or reject registry.

**Verification:** Run pipeline manually, confirm diffs appear on GDrive. Then run Jazzy approval, approve one skill (verify deployed correctly), reject one (verify locked).

### Task 5: Create Host Cron Scripts [NOT STARTED]
**Files (on VPS host):**
- `/home/jazzy/docker/skillclaw/cron/sync-agent-skills.sh` — 01:30 UTC, copies agent skills → GDrive central store
- `/home/jazzy/docker/skillclaw/cron/convert-sessions.sh` — 02:00 UTC, runs converter via docker exec

Each script: host-level wrapper, uses `docker exec skillclaw` for container operations, logs to `/var/log/skillclaw/`.

**Verification:** Run each script manually, confirm it executes correctly.

### Task 6: Set Up Cron on VPS [NOT STARTED]
**Host crontab:**
- `30 1 * * * /home/jazzy/docker/skillclaw/cron/sync-agent-skills.sh`
- `0 2 * * * /home/jazzy/docker/skillclaw/cron/convert-sessions.sh`
- `15 8 * * * /home/jazzy/docker/skillclaw/deploy/run-pipeline.sh`

**Verification:** `crontab -l` shows 3 host entries.

### Task 7: Verify End-to-End [NOT STARTED]
- Run converter manually, confirm parentSessionId in output
- Run evolver, confirm it picks up converted sessions
- Run `run-pipeline.sh`, confirm diffs appear on GDrive
- Read diffs from Jazzy Discord session, present to James
- Approve skill, confirm it deploys to central store + target agents + evolver baseline
- Reject skill, confirm it reverts + applies evolve-lock

**Verification:** Full pipeline run with real data.

### Task 8: Fix Reject Script — Add Evolve-Lock [NOT STARTED]
**File:** `/home/jazzy/docker/skillclaw/deploy/reject-skill.sh`
- Add `.evolve-lock` file to SkillClaw local storage when a skill is rejected
- Evolver must check for `.evolve-lock` before processing a skill
- Lock file should contain: rejection reason, timestamp, who rejected
- On approve: remove the lock file if it exists

**Verification:** Reject a skill, confirm `.evolve-lock` exists, confirm evolver skips it on next cycle.

### Task 9: Multi-File Skill Support [NOT STARTED]
**Files:** `convert.py`, deploy scripts, evolver config
- Converter currently only tracks SKILL.md via regex (`skills/([^/]+)/SKILL\.md`)
- Skills may contain: SKILL.md, manifest.json, helper scripts, templates, config files
- Evolver only writes SKILL.md — must preserve other files in skill directory
- Deploy/approve scripts already copy entire directory (good)
- Need to update converter to track full skill directories, not just SKILL.md

**Verification:** Create a multi-file skill, run through pipeline, confirm all files preserved.

### Task 10: Manifest Clobbering Prevention [NOT STARTED]
**Risk:** Evolver may overwrite entire skill directory when evolving, destroying non-SKILL.md files.
- Evolver must only write/update SKILL.md, never touch other files
- Or: evolver writes to a staging area, deploy script copies only SKILL.md to evolved-skills/
- Need to verify evolver behavior (check if it writes single file or entire directory)

**Verification:** Add a non-SKILL.md file to a skill, run evolver, confirm file survives.

## Coverage Check

| Req | Requirement | Tasks | Coverage | Status |
|-----|------------|-------|----------|--------|
| FR-001 | Convert .jsonl → .json | T1 | Covered | DONE |
| FR-002 | Process 10 agents | T2 | Covered | DONE (container side) |
| FR-003 | Graceful error handling | T1, T3 | Covered | DONE |
| FR-004 | Local storage backend | Existing | Covered | DONE |
| FR-005 | GDrive deploy | T3 | Covered | DONE |
| FR-006 | Daily cron | T5, T6 | Covered | NOT STARTED |
| FR-007 | Deduplication | Existing | Covered | DONE |
| FR-008 | Logging | Existing | Covered | DONE |
| FR-009 | Agent skill sync | T2 | Covered | PARTIAL (container done, host pending) |
| FR-010 | Exclude Forge | T2 | Covered | DONE |
| FR-014 | Extract spawnedBy | T1 | Covered | NOT STARTED |
| FR-015 | Walk parent chain | T1 | Covered | NOT STARTED |
| FR-016 | Output parentSessionId | T1 | Covered | NOT STARTED |
| FR-017 | Handle missing spawnedBy | T1 | Covered | NOT STARTED |
| FR-018 | Multi-file skill support | T9 | New | NOT STARTED |
| FR-019 | Manifest clobbering prevention | T10 | New | NOT STARTED |
| FR-020 | Reject evolve-lock | T8 | New | NOT STARTED |
| FR-021 | Diff baseline correct | T3 | Covered | DONE |
| US1 | Daily Skill Evolution | T5, T6 | Covered | NOT STARTED (cron) |
| US2 | Review Before Deploy | T3, T4 | Covered | SCRIPTS DONE |
| US3 | Isolated Evolver | Existing | Covered | DONE |
| US4 | Daily Agent Skill Sync | T2, T5, T6 | Covered | PARTIAL |
| US5 | Session Hierarchy | T1 | Covered | NOT STARTED |
| NFR-001 | No agent container access | T2 | Covered | DONE |
| NFR-002 | Dedicated OpenRouter key | Existing | Covered | DONE |
| NFR-003 | Complete within 30min | T5, T6 | Covered | NOT TESTED |
| NFR-004 | No auto-deploy | T3, T4 | Covered | DONE |
| NFR-005 | Human review required | T3, T4 | Covered | DONE |
| NFR-006 | Backward compatible | T1 | Covered | NOT STARTED |
| NFR-007 | 30-min pipeline | T5, T6 | Covered | NOT TESTED |

## ADR: No-Proxy Architecture

**ADR-001:** Skip SkillClaw proxy, use converter + evolver only.

**Context:** SkillClaw proxy is single-model, requires sandbox off. Our fleet uses multiple models/providers.

**Decision:** Write a converter to transform OpenClaw session transcripts into SkillClaw format. Feed directly to evolver. No MITM on LLM traffic.

**Consequences:**
- (+) No sandbox changes, no proxy overhead, multi-model support
- (-) No PRM scoring, no real-time skill injection, converter maintenance
- (?) Evolver quality depends on how well raw .jsonl maps to SkillClaw's expected format

**Alternatives Considered:**
| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Run proxy per agent | Full SkillClaw features | 11 proxy instances, sandbox off, single model per instance | Too complex, security downgrade |
| Single proxy, all agents | Simpler setup | Limited to one model for entire fleet | Non-starter with 11 agents using different models |
| Patch proxy for multi-model | Full features | Fork maintenance, complexity | Unnecessary — converter is simpler |
