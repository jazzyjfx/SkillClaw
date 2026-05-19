#!/usr/bin/env python3
"""
OpenClaw → SkillClaw session converter.

Reads OpenClaw .jsonl session files and converts them to SkillClaw .json format.
Deduplicates via processed.json. Supports --backfill to ignore processed state.
"""

import re
import os
import sys
import glob
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from config import (
    OPENCLAW_SESSIONS_DIR,
    SKILLCLAW_SESSIONS_DIR,
    PROCESSED_FILE,
    EXCLUDED_AGENTS,
)


SKILL_READ_TOOLS = {"read", "file_read", "read_file", "readfile"}
SKILL_WRITE_TOOLS = {"write", "file_write", "write_file", "writefile", "create_file", "edit", "edit_file", "replace", "replace_in_file", "append", "append_file", "patch", "apply_patch"}
SKILL_PATH_RE = re.compile(r"skills/([^/]+)/SKILL\.md")


def resolve_root_session(session_id, sessions_registry, _visited=None):
    """Walk the spawnedBy chain to find the root session UUID.

    - Root session (no spawnedBy) → returns its own ID
    - Subagent → recursively resolves parent
    - Orphaned subagent (parent missing) → returns its own ID
    - Circular reference → breaks loop, returns current ID
    """
    if _visited is None:
        _visited = set()
    if session_id in _visited:
        return session_id  # circular reference
    _visited.add(session_id)

    info = sessions_registry.get(session_id)
    if not info or not isinstance(info, dict):
        return session_id  # not in registry or invalid entry

    spawned_by = info.get("spawnedBy")
    if not spawned_by:
        return session_id  # root session

    # spawned_by may be a session key; resolve to sessionId if possible
    # Look up by spawned_by as-is first, then scan for matching sessionId
    parent_id = spawned_by
    if spawned_by not in sessions_registry:
        # spawned_by might be a session key (not UUID); scan registry for matching entry
        for _sid, _entry in sessions_registry.items():
            if isinstance(_entry, dict) and _entry.get("key") == spawned_by:
                parent_id = _sid
                break
        else:
            # Parent not found — orphaned subagent
            return session_id

    return resolve_root_session(parent_id, sessions_registry, _visited)


def extract_skill_name(path):
    """Extract skill name from a skill file path."""
    match = SKILL_PATH_RE.search(str(path or ""))
    return match.group(1) if match else None


def extract_available_skills(content):
    """Extract skill names from <available_skills> blocks in system messages."""
    skills = []
    if not content:
        return skills
    text = str(content)
    # Match <available_skills> blocks and extract skill names
    import re
    # Pattern: <name>skill-name</name> inside <skill> blocks
    for match in re.finditer(r'<name>([^<]+)</name>', text):
        name = match.group(1).strip()
        if name:
            skills.append(name)
    return skills


def classify_tool_call(tool_name, args):
    """Classify a tool call as read_skill, modified_skill, or neither."""
    name = (tool_name or "").strip().lower()
    path = ""
    if isinstance(args, dict):
        path = str(args.get("path", args.get("file", args.get("file_path", ""))))
    elif isinstance(args, str):
        try:
            args_obj = json.loads(args)
            path = str(args_obj.get("path", args_obj.get("file", args_obj.get("file_path", ""))))
        except Exception:
            pass
    
    skill_name = extract_skill_name(path)
    if not skill_name:
        return None, None
    
    if name in SKILL_READ_TOOLS:
        return "read", skill_name
    if name in SKILL_WRITE_TOOLS:
        return "modified", skill_name
    return None, None


def load_processed():
    """Load the set of already-processed session IDs."""
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return json.load(f)
    return {}


def save_processed(processed):
    """Save the processed session registry."""
    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(processed, f, indent=2)


def extract_text(content):
    """Extract text from message content (string or array of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "thinking":
                    # Skip thinking blocks — internal reasoning
                    continue
                elif block.get("type") == "tool_use":
                    # Include tool call info
                    name = block.get("name", "unknown")
                    inp = block.get("input", {})
                    parts.append(f"[Tool Call: {name}] {json.dumps(inp, ensure_ascii=False)}")
                elif block.get("type") == "toolCall":
                    name = block.get("name", "unknown")
                    args = block.get("arguments", block.get("input", {}))
                    parts.append(f"[Tool Call: {name}] {json.dumps(args, ensure_ascii=False)}")
        return "\n".join(parts)
    return str(content)


def parse_jsonl_session(filepath):
    """Parse an OpenClaw .jsonl session file into structured turns."""
    messages = []
    session_meta = {}

    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # First line is typically the session marker/metadata
            if i == 0:
                session_meta = entry
                continue

            # Skip non-message entries (config events, metadata, etc.)
            if entry.get("type") != "message":
                continue

            # Extract message — could be nested under "message" key or at top level
            msg = entry.get("message", entry)
            role = msg.get("role", entry.get("role", "unknown"))
            content = msg.get("content", entry.get("content", ""))

            messages.append({
                "role": role,
                "content": content,
                "raw": entry,
            })

    return session_meta, messages


def group_into_turns(messages):
    """
    Group messages into conversation turns.

    A turn = user message + assistant response + associated tool calls/results.
    """
    turns = []
    current_turn = None
    turn_num = 0

    for msg in messages:
        role = msg["role"]

        if role == "user":
            # Start a new turn
            if current_turn:
                turns.append(current_turn)
            turn_num += 1
            current_turn = {
                "turn_num": turn_num,
                "prompt_text": extract_text(msg["content"]),
                "response_text": "",
                "read_skills": [],
                "modified_skills": [],
                "tool_calls": [],
                "tool_results": [],
                "tool_errors": [],
                "prm_score": None,
            }
        elif role == "assistant":
            if current_turn is None:
                turn_num += 1
                current_turn = {
                    "turn_num": turn_num,
                    "prompt_text": "",
                    "response_text": "",
                    "read_skills": [],
                    "modified_skills": [],
                    "tool_calls": [],
                    "tool_results": [],
                    "tool_errors": [],
                    "prm_score": None,
                }
            text = extract_text(msg["content"])
            if current_turn["response_text"]:
                current_turn["response_text"] += "\n" + text
            else:
                current_turn["response_text"] = text
            
            # Extract tool calls from assistant content and detect skill usage
            raw_msg = msg.get("raw", {}).get("message", {})
            content = raw_msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        tc_name = block.get("name", "")
                        tc_args = block.get("arguments", {})
                        current_turn["tool_calls"].append({
                            "name": tc_name,
                            "arguments": tc_args,
                        })
                        # Check if this tool call reads/writes a skill
                        action, skill_name = classify_tool_call(tc_name, tc_args)
                        if action == "read" and skill_name not in current_turn["read_skills"]:
                            current_turn["read_skills"].append(skill_name)
                        elif action == "modified" and skill_name not in current_turn["modified_skills"]:
                            current_turn["modified_skills"].append(skill_name)
        elif role == "toolResult":
            if current_turn is None:
                turn_num += 1
                current_turn = {
                    "turn_num": turn_num,
                    "prompt_text": "",
                    "response_text": "",
                    "read_skills": [],
                    "modified_skills": [],
                    "tool_calls": [],
                    "tool_results": [],
                    "tool_errors": [],
                    "prm_score": None,
                }
            raw_msg = msg.get("raw", {}).get("message", {})
            tool_name = raw_msg.get("toolName", "")
            content = extract_text(msg["content"])
            is_error = raw_msg.get("isError", False)
            details = raw_msg.get("details", {})
            exit_code = details.get("exitCode", None)
            status = details.get("status", "")
            # Check multiple error indicators (isError is unreliable)
            if not is_error and (status == "failed" or (exit_code is not None and exit_code != 0)):
                is_error = True
            current_turn["tool_results"].append({
                "name": tool_name,
                "output": content[:5000],
            })
            if is_error:
                current_turn["tool_errors"].append({
                    "name": tool_name,
                    "error": content[:2000],
                    "exit_code": exit_code,
                    "status": status,
                })
        else:
            # System or other — check for available_skills block
            raw_content = msg.get("raw", {}).get("message", {}).get("content", "")
            available = extract_available_skills(raw_content)
            if available:
                # If no current turn yet, create one
                if current_turn is None:
                    turn_num += 1
                    current_turn = {
                        "turn_num": turn_num,
                        "prompt_text": "",
                        "response_text": "",
                        "read_skills": [],
                        "modified_skills": [],
                        "tool_calls": [],
                        "tool_results": [],
                        "tool_errors": [],
                        "prm_score": None,
                    }
                for skill in available:
                    if skill not in current_turn["read_skills"]:
                        current_turn["read_skills"].append(skill)
            if current_turn:
                text = extract_text(msg["content"])
                if text:
                    current_turn["tool_results"].append({
                        "name": f"system_{role}",
                        "output": text[:5000],
                    })

    if current_turn:
        turns.append(current_turn)

    return turns


def convert_session(agent_name, session_id, session_meta, messages, output_dir):
    """Convert a parsed session to SkillClaw format and write it."""
    turns = group_into_turns(messages)

    # Build SkillClaw format
    skillclaw_session = {
        "session_id": session_id,
        "agent": agent_name,
        "source": "openclaw",
        "convertedAt": datetime.now(timezone.utc).isoformat(),
        "sessionMeta": session_meta,
        "turns": turns,
        "messageCount": len(messages),
        "turnCount": len(turns),
        "aggregate": {
            "rollout_count": 1,
            "scores": [],
            "mean_score": None,
            "success_count": 0,
            "fail_count": 0,
            "stability": None,
        },
    }

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{session_id}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(skillclaw_session, f, indent=2, ensure_ascii=False)

    return output_path


def scan_and_convert(backfill=False):
    """Main entry point: scan OpenClaw sessions and convert unprocessed ones."""
    processed = {} if backfill else load_processed()
    converted_count = 0
    skipped_count = 0
    error_count = 0

    if not os.path.isdir(OPENCLAW_SESSIONS_DIR):
        print(f"ERROR: OpenClaw sessions directory not found: {OPENCLAW_SESSIONS_DIR}")
        return

    # Scan agent directories
    agent_dirs = sorted(os.listdir(OPENCLAW_SESSIONS_DIR))
    print(f"Found {len(agent_dirs)} agent directories")

    for agent_name in agent_dirs:
        if agent_name in EXCLUDED_AGENTS:
            print(f"  SKIP (excluded): {agent_name}")
            continue

        agent_sessions_dir = os.path.join(OPENCLAW_SESSIONS_DIR, agent_name, "sessions")
        if not os.path.isdir(agent_sessions_dir):
            # Try flat structure (sessions directly under agent dir)
            agent_sessions_dir = os.path.join(OPENCLAW_SESSIONS_DIR, agent_name)
            if not os.path.isdir(agent_sessions_dir):
                continue

        # Read sessions.json if it exists
        sessions_json_path = os.path.join(agent_sessions_dir, "sessions.json")
        sessions_registry = {}  # sessionId -> entry lookup
        if os.path.exists(sessions_json_path):
            try:
                with open(sessions_json_path, "r") as f:
                    raw_registry = json.load(f)
                # Build sessionId → entry lookup (registry keys are session keys, not UUIDs)
                for _key, entry in raw_registry.items():
                    if isinstance(entry, dict):
                        sid = entry.get("sessionId")
                        if sid:
                            sessions_registry[sid] = entry
            except (json.JSONDecodeError, IOError):
                pass

        # Find .jsonl files
        jsonl_files = glob.glob(os.path.join(agent_sessions_dir, "*.jsonl"))
        print(f"  Agent {agent_name}: {len(jsonl_files)} session files")

        # First pass: collect all eligible sessions and resolve their root IDs.
        # We need this so subagent turns get merged into the correct root output.
        # Structure: root_session_id -> list of (session_id, session_meta, messages, jsonl_path)
        root_groups = {}  # root_session_id -> list of sub-sessions

        for jsonl_path in sorted(jsonl_files):
            filename = os.path.basename(jsonl_path)

            # Skip .deleted and .bak files
            if ".deleted" in filename or ".bak" in filename:
                continue

            # Skip if lock file exists
            lock_path = jsonl_path + ".lock"
            if os.path.exists(lock_path):
                continue

            # Extract session ID from filename
            session_id = filename.replace(".jsonl", "")

            # Check if already processed
            if session_id in processed:
                skipped_count += 1
                continue

            # Check sessions.json registry for status
            if sessions_registry:
                session_info = sessions_registry.get(session_id, {})
                if isinstance(session_info, dict):
                    status = session_info.get("status", "")
                    ended_at = session_info.get("endedAt")

                    # Filter: must be done or timeout, with endedAt set
                    if status not in ("done", "timeout"):
                        continue
                    if ended_at is None:
                        continue

            # Resolve to root session for hierarchy merge
            root_id = resolve_root_session(session_id, sessions_registry)

            # Parse the session
            try:
                session_meta, messages = parse_jsonl_session(jsonl_path)
                if not messages:
                    print(f"    SKIP (no messages): {session_id}")
                    continue

                root_groups.setdefault(root_id, []).append(
                    (session_id, session_meta, messages, jsonl_path)
                )

            except Exception as e:
                error_count += 1
                print(f"    ERROR: {session_id}: {e}")

        # Second pass: convert each root group, merging subagent sessions.
        for root_id, sub_sessions in root_groups.items():
            try:
                # Merge all messages from sub-sessions in order
                merged_messages = []
                all_source_ids = []
                merged_meta = {}
                total_message_count = 0

                for (session_id, session_meta, messages, _jsonl_path) in sub_sessions:
                    merged_messages.extend(messages)
                    all_source_ids.append(session_id)
                    total_message_count += len(messages)
                    # Use the root session's meta if available, else first non-empty
                    if not merged_meta and session_meta:
                        merged_meta = session_meta

                # Determine the session_id for output: root_id
                output_session_id = root_id

                # Group merged messages into turns
                turns = group_into_turns(merged_messages)

                # Build SkillClaw format
                skillclaw_session = {
                    "session_id": output_session_id,
                    "agent": agent_name,
                    "source": "openclaw",
                    "convertedAt": datetime.now(timezone.utc).isoformat(),
                    "sessionMeta": merged_meta,
                    "turns": turns,
                    "messageCount": total_message_count,
                    "turnCount": len(turns),
                    "aggregate": {
                        "rollout_count": 1,
                        "scores": [],
                        "mean_score": None,
                        "success_count": 0,
                        "fail_count": 0,
                        "stability": None,
                    },
                }

                # Add sub-session tracking if there were multiple
                if len(all_source_ids) > 1:
                    skillclaw_session["mergedFrom"] = all_source_ids

                # Write output
                os.makedirs(SKILLCLAW_SESSIONS_DIR, exist_ok=True)
                output_path = os.path.join(SKILLCLAW_SESSIONS_DIR, f"{output_session_id}.json")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(skillclaw_session, f, indent=2, ensure_ascii=False)

                converted_count += 1

                # Mark ALL source sessions as processed (dedup by original ID)
                for (session_id, _session_meta, messages, _jsonl_path) in sub_sessions:
                    processed[session_id] = {
                        "agent": agent_name,
                        "convertedAt": datetime.now(timezone.utc).isoformat(),
                        "messageCount": len(messages),
                        "outputPath": output_path,
                        "mergedInto": output_session_id if session_id != output_session_id else None,
                    }

                if len(all_source_ids) > 1:
                    print(f"    MERGED: {len(all_source_ids)} sessions → {output_session_id} ({total_message_count} messages)")
                else:
                    print(f"    CONVERTED: {all_source_ids[0]} ({total_message_count} messages)")

            except Exception as e:
                error_count += 1
                print(f"    ERROR (merge group {root_id}): {e}")

    # Save processed state
    save_processed(processed)

    # Summary
    print(f"\n{'='*50}")
    print(f"CONVERSION SUMMARY")
    print(f"  Converted: {converted_count}")
    print(f"  Skipped (already processed): {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total processed entries: {len(processed)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    backfill = "--backfill" in sys.argv
    if backfill:
        print("Running in BACKFILL mode (ignoring processed.json)")
    scan_and_convert(backfill=backfill)
