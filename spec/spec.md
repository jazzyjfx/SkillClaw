# Feature: SkillClaw Evolver Integration (No-Proxy)

Created: 2026-05-13
Status: Draft
Input: Install SkillClaw skill evolution without using its proxy component

## Overview

Deploy SkillClaw's evolver server as a standalone Docker container that reads OpenClaw session transcripts, converts them to SkillClaw format, and evolves reusable skills daily. Evolved skills land on Google Drive for human review before deployment. No proxy, no sandbox changes, no MITM on LLM traffic.

**Forge excluded** — BMAD Method suite is a third-party methodology with ~100+ heavily nested duplicate skills, not suitable for evolution. Agents in scope: atlas, axiom, dex, dispatch, jazzy, jim, lumi, nova, prime, vector (10 agents).

## User Stories

### US1: Daily Skill Evolution (Priority: P1)
As an operator, I want the evolver to process agent sessions daily and produce candidate skills so that I can review and deploy useful patterns discovered across the fleet.

Independent Test: Run converter + evolver on a single day's sessions, verify evolved skills appear in output directory.

Acceptance Criteria:
- Given 10 agents produce session transcripts daily, When the daily cron runs, Then all new sessions are converted and fed to the evolver.
- Given the evolver processes sessions, When it identifies reusable patterns, Then it writes evolved SKILL.md files to the output directory.
- Given evolved skills exist in output, When the deploy script runs, Then skills are copied to GDrive at `/mnt/gdrive/shared/common/evolved-skills/`.

### US2: Review Before Deploy (Priority: P1)
As an operator, I want evolved skills on GDrive before deployment so that I can review, edit, or reject them.

Independent Test: Verify skills appear on GDrive and are NOT auto-deployed to agent skill directories.

Acceptance Criteria:
- Given evolved skills exist in the evolver output, When the sync runs, Then skills appear in `/mnt/gdrive/shared/common/evolved-skills/`.
- Given skills are on GDrive, When no manual action is taken, Then skills are NOT copied to any agent's active skills directory.

### US3: Isolated Evolver (Priority: P2)
As an operator, I want the evolver running in its own container with a dedicated API key so that evolution costs are tracked separately and the evolver has no access to agent runtimes.

Independent Test: Verify evolver container is running, has its own OpenRouter key, and has no mount to agent containers.

Acceptance Criteria:
- Given the evolver is deployed, When checking Docker, Then it runs as a standalone container.
- Given the evolver needs an LLM, When it makes API calls, Then it uses a dedicated OpenRouter key (not shared with agents).

### US4: Daily Agent Skill Sync (Priority: P1)
As an operator, I want all agent skills synced to a shared GDrive folder daily so that I have a cross-agent skill inventory for review.

Independent Test: Verify agent skills appear on GDrive under `/mnt/gdrive/shared/common/agent-skills/{agent}/`.

Acceptance Criteria:
- Given 10 agents have skills installed, When the daily sync runs, Then all SKILL.md files are copied to GDrive under their agent name.
- Given Forge is excluded, When the sync runs, Then no Forge skills appear on GDrive.

### US5: Session Hierarchy Awareness (Priority: P1)
As the evolver, I want subagent sessions to carry hierarchy metadata so that downstream tools can distinguish parent sessions from subagent tool calls.

Independent Test: Converter output JSON includes parentSessionId for subagent sessions.

Acceptance Criteria:
- Given a session with spawnedBy in sessions.json, When the converter processes it, Then the output includes parentSessionId pointing to the ROOT session UUID (walking up the chain if the direct parent is also a subagent)
- Given a session with no spawnedBy in sessions.json (root or legacy), When the converter processes it, Then parentSessionId is null
- Given a nested subagent (subagent spawned by subagent), When the converter processes it, Then parentSessionId points to the same root session as all other subagents in that tree

**Implementation Status: NOT IMPLEMENTED** — The converter currently does NOT read `spawnedBy` from sessions.json and does NOT output `parentSessionId`. This is pending (see plan Task 1). The planned approach: subagent sessions will be merged into their parent session's transcript (not a separate parentSessionId field), so the evolver sees one coherent conversation.

## Functional Requirements

- FR-001: System MUST convert OpenClaw `.jsonl` session transcripts to SkillClaw's `.json` session format.
- FR-002: System MUST process sessions from 10 agents (atlas, axiom, dex, dispatch, jazzy, jim, lumi, nova, prime, vector). Forge is excluded.
- FR-003: Converter MUST handle sessions that are incomplete or have errors (graceful skip, log warning).
- FR-004: Evolver MUST run with `--storage-backend local` and `--local-root /data/skillclaw`.
- FR-005: Evolver MUST consume converted sessions from `{local_root}/{group_id}/sessions/`.
- FR-006: Evolver MUST write evolved skills to `{local_root}/{group_id}/skills/{skill-name}/SKILL.md`.
- FR-007: Deploy script MUST copy evolved skills to `/mnt/gdrive/shared/common/evolved-skills/`.
- FR-008: Daily cron MUST trigger the full pipeline: convert → evolve → deploy evolved skills → sync agent skills.
- FR-009: Converter MUST deduplicate — only process sessions not already converted (track by session ID).
- FR-010: System MUST log what it does — how many sessions converted, how many evolved, any errors.
- FR-011: Agent skill sync MUST copy all SKILL.md files from 10 agents to `/mnt/gdrive/shared/common/agent-skills/{agent-name}/`.
- FR-012: Converter MUST use `sessions.json` to detect completed sessions and `.jsonl.lock` files as secondary check.
- FR-013: Evolver MUST use `publish_mode: direct` — no crowd-validation, we review on GDrive.
- FR-014: Converter MUST extract spawnedBy from sessions.json for each session **[NOT IMPLEMENTED — pending]**
- FR-015: Converter MUST resolve spawnedBy to the ROOT session UUID by walking up the parent chain (not just the direct parent) **[NOT IMPLEMENTED — pending]**
- FR-016: Converter MUST output parentSessionId (UUID or null) in the converted session JSON **[NOT IMPLEMENTED — pending; planned approach: merge subagent transcript into parent session instead]**
- FR-017: Converter MUST handle missing spawnedBy gracefully (treat as root session, parentSessionId = null) **[NOT IMPLEMENTED — pending]**
- FR-018: Converter MUST support multi-file skills (not just SKILL.md — skills may contain multiple .md files, scripts, templates) **[GAP IDENTIFIED — converter only tracks SKILL.md, evolver only writes SKILL.md]**
- FR-019: Evolver MUST NOT clobber non-SKILL.md files in skill directories when evolving (manifest, scripts, templates) **[RISK IDENTIFIED — evolver may overwrite entire skill directory]**
- FR-020: Reject script MUST apply evolve-lock to prevent re-evolution of rejected skills **[FIX NEEDED — current reject script removes from local storage, evolver will just recreate it]**
- FR-021: Deploy script MUST compare evolved skills against live agent-skills/ baseline (not evolved-skills/) for diff generation **[IMPLEMENTED — deploy_skills.sh already uses agent-skills/ as baseline]**

## Non-Functional Requirements

- NFR-001: Evolver MUST NOT have access to agent containers or their runtime.
- NFR-002: Evolver MUST use a dedicated OpenRouter API key (not shared with agents).
- NFR-003: Converter MUST complete within 10 minutes for a full day's sessions across 10 agents.
- NFR-004: Evolver MUST NOT auto-deploy skills to active agent skill directories.
- NFR-005: All evolved skills MUST pass through human review before deployment.
- NFR-006: Converter changes must be backward compatible — existing sessions without hierarchy data are treated as root sessions
- NFR-007: Daily pipeline must complete within 30 minutes (convert + evolve + deploy)

## Success Criteria

- SC-001: Daily cron produces evolved skills on GDrive within 30 minutes of trigger.
- SC-002: Converter handles sessions from 10 agents without errors.
- SC-003: Evolved skills are reviewable on GDrive before any deployment action.
- SC-004: Agent skills are synced to GDrive daily with all 10 agents represented.
- SC-005: Converter output includes parentSessionId (root UUID or null) for all sessions with hierarchy data
- SC-006: Legacy sessions (no hierarchy data) continue to process correctly as root sessions

## Edge Cases

- **Empty sessions:** Converter skips sessions with no meaningful turns (e.g., heartbeat-only).
- **Duplicate sessions:** Converter tracks processed session IDs to avoid re-processing.
- **Evolver failures:** If the evolver fails, sessions remain in the input directory for retry on next run.
- **GDrive mount unavailable:** Deploy script logs error, skills remain in local output for manual retrieval.
- **Rate limits on OpenRouter:** Evolver respects rate limits, retries with backoff.
- **Zombie sessions:** Sessions with `status == "running"` but no lock file + >24h old are skipped with warning.
- **Orphaned subagents**: Parent not in sessions.json → treat as root session
- **Deep nesting** (subagent spawned by subagent): Walk up to root parent
- **Large fan-out**: Parent with 50+ subagents → truncate/summarize judge payload

## Pipeline Scheduling

### Current State (2026-05-19)
- Converter: Script deployed to container at `/data/converter/convert.py`. No cron yet — manual run only.
- Deploy to GDrive: Script deployed at `/data/deploy/deploy_skills.sh`. Uses agent-skills/ as diff baseline (correct).
- Agent skill sync: Container-side script at `/data/deploy/sync_agent_skills.sh` (GDrive → SkillClaw repo). Host-side sync script needed.
- Pipeline script: `/data/deploy/run-pipeline.sh` deployed. Not yet in cron.
- Approve script: `/data/deploy/approve-skill.sh` deployed. Multi-dir copy (entire skill dir, not just SKILL.md).
- Reject script: `/data/deploy/reject-skill.sh` deployed. **FIX NEEDED:** removes from local storage but doesn't apply evolve-lock — evolver will recreate rejected skills.
- Lobster: REMOVED from architecture — not needed. Pipeline is VPS script + Jazzy Discord approval + VPS scripts.
- Agent domain map: Exists for routing evolved skills to target agents by domain (sysadmin→Jazzy, crypto→Dex, etc.)
- Cron: None configured yet on VPS host.

### Pipeline Flow

```
Agent Skills (all agents)
    │
    ▼
GDrive Central Store (/mnt/gdrive/shared/common/agent-skills/)
    │
    ▼
SkillClaw Skill Repository (converter reads from here)
    │
    ▼
Converter (02:00 UTC daily)
    │
    ▼
Evolver (internal 12h timer, picks up converted sessions)
    │
    ▼
Evolved Skills (local storage)
    │
    ▼
GDrive Evolved Skills (08:15 UTC)
    │
    ▼
Approval Gate (per-skill, Discord notification with change summary)
    │
    ├─ Approved → Deploy to Central Store + All Relevant Agents
    └─ Rejected → Skip, carry forward to next cycle
```

### Cron Jobs Required

| Cron Entry | Time (UTC) | Description |
|------------|-----------|-------------|
| `docker exec skillclaw bash /data/deploy/sync_agent_skills.sh` | 01:30 | Sync agent skills from all agents → GDrive central store → SkillClaw repo |
| `docker exec skillclaw python3 /data/converter/convert.py` | 02:00 | Run session converter (evolver picks up on next cycle) |
| `docker exec skillclaw bash /data/deploy/deploy_skills.sh` | 08:15 | Copy evolved skills to GDrive evolved-skills folder |

### Deployment Process

1. **01:30 UTC** — Agent skill sync: copy latest skills from ALL agents → GDrive central store (`/mnt/gdrive/shared/common/agent-skills/`) → SkillClaw skill repository
2. **02:00 UTC** — Converter runs: convert new .jsonl sessions → .json for evolver
3. **~02:00-14:00 UTC** — Evolver runs on internal 12h timer: picks up converted sessions, judges, evolves skills
4. **08:15 UTC** — Deploy script: copy evolved skills from container → GDrive evolved-skills folder (`/mnt/gdrive/shared/common/evolved-skills/`)
5. **08:15 UTC** — Approval gate: for each evolved skill, notify James on Discord with:
   - Skill name
   - What changed (diff summary)
   - Which agents are affected
6. **On approval per skill:**
   - 6a. Deploy to central store (GDrive `/mnt/gdrive/shared/common/agent-skills/`)
   - 6b. Deploy to ALL relevant agents (not just jazzy/dex/vector — any agent whose sessions contributed to the skill)

### Approval Process

- **Granularity:** Per-skill (each evolved skill requires individual approval)
- **Notification:** Discord message per skill with:
  - Skill name and version
  - Change summary (what was added/modified/removed)
  - List of agents affected (which agents' sessions contributed)
- **Approval:** James replies to approve/reject each skill
- **On approve:**
  - Copy skill to GDrive central store (`/mnt/gdrive/shared/common/agent-skills/{skill-name}/`)
  - Copy skill to workspace directories of ALL relevant agents
- **On reject:** Skip deployment, skill remains in container for next cycle
- **Timeout:** If no approval within 24h, skill carries forward to next cycle
- **Relevant agents:** Determined by which agents' sessions contributed to the skill evolution (not a fixed list)

## Known Issues & Gaps (2026-05-19)

1. **parentSessionId NOT IMPLEMENTED** — Converter does not read `spawnedBy` from sessions.json. Plan: merge subagent transcripts into parent session.
2. **Multi-file skill gap** — Converter only tracks SKILL.md via regex. Skills may contain multiple files (manifests, scripts, templates). Evolver also only writes SKILL.md. Need to support full skill directories.
3. **Manifest clobbering risk** — If evolver overwrites a skill directory, non-SKILL.md files (manifest.json, helper scripts, templates) could be destroyed. Evolver must preserve or skip non-SKILL.md files.
4. **Reject script: no evolve-lock** — Current reject script removes evolved skill from local storage, but evolver will recreate it on next cycle. Need an evolve-lock mechanism (e.g., `.evolve-lock` file or reject registry) to prevent re-evolution.
5. **Diff baseline: CORRECT** — deploy_skills.sh compares evolved vs live agent-skills/ (not evolved-skills/). This was verified.
6. **Lobster: REMOVED** — Approval flow uses VPS scripts + Jazzy Discord session. No Lobster needed.
7. **Agent domain map: EXISTS** — Skills are routed to target agents by domain (sysadmin→Jazzy, crypto→Dex, forex→Vector, etc.)

## Assumptions

- OpenClaw session transcripts contain enough information for skill extraction (tool calls, responses, patterns).
- The evolver can extract useful skills from raw `.jsonl` format without the proxy's enriched metadata (PRM scores, skill references).
- MiMo v2.5 via OpenRouter is sufficient for skill evolution (cost-effective batch model).
- James will create a dedicated OpenRouter API key before deployment.

## Out of Scope

- SkillClaw client proxy (not installing — single-model limitation, sandbox conflict).
- Auto-deployment of evolved skills to agents.
- Real-time skill evolution (batch only, daily).
- PRM scoring or rollout aggregation (proxy features we can't use).
- Modifying agent configs or sandbox settings.
- Forge agent (BMAD Method suite — third-party methodology, not suitable for evolution).

## Resolved Questions

- [x] Model: MiMo v2.5 via OpenRouter (xiaomi/mimo-v2.5) (cost-effective for batch processing)
- [x] Group ID: `openclaw-fleet`
- [x] Backfill: Yes, process historical sessions
- [x] Publish mode: `direct` (no crowd-validation)
- [x] Forge: Excluded entirely (skills + sessions)

## Existing Infrastructure

- **Container:** `skillclaw` already running on VPS (v0.4.0, Python 3.12, unhealthy)
- **Compose:** `/home/jazzy/docker/skillclaw/docker-compose.yml`
- **Config:** `/home/jazzy/docker/skillclaw/config/config.yaml`
- **Volumes:** skills (`/data/skills`), share (`/data/local-share`), config (`/data/config`), logs (`/data/logs`)
- **Ports:** 8787 (proxy), 8080 (API — not listening)
- **Current LLM:** MiniMax-M2.7 (needs switching to OpenRouter)
