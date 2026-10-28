#!/usr/bin/env python3
"""
3사(Claude Code, Antigravity, OpenAI Codex) 세션 및 핸즈오프 통합 수집기
- 대상 DB: agent_hub.db (기본 경로: ~/.config/ai/agent_hub/agent_hub.db, AGENT_HUB_DIR/AGENT_HUB_DB로 재지정 가능)
- 대화 세션 및 도구 실행, 핸즈오프 기록을 정규화하여 적재
"""

import os
import sys
import glob
import json
import sqlite3
import datetime
import tarfile
import tempfile

HOME = os.path.expanduser("~")


def resolve_agent_hub_dir():
    configured = os.environ.get("AGENT_HUB_DIR")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.join(HOME, ".config", "ai", "agent_hub")


DEFAULT_DB_DIR = resolve_agent_hub_dir()
DB_PATH = os.path.abspath(os.path.expanduser(
    os.getenv("AGENT_HUB_DB", os.path.join(DEFAULT_DB_DIR, "agent_hub.db"))
))
HUB_DATA_DIR = os.path.dirname(DB_PATH)

CLAUDE_PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
AGY_BRAIN_DIR = os.path.join(HOME, ".gemini", "antigravity-cli", "brain")

CODEX_HOME = os.path.abspath(os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex")))
CODEX_SESSIONS_DIR = os.path.join(CODEX_HOME, "sessions")
CODEX_BACKUP_TAR = os.path.abspath(os.path.expanduser(os.environ.get(
    "AGENT_HUB_CODEX_BACKUP_TAR",
    os.path.join(HUB_DATA_DIR, "backups", "codex_sessions_backup.tar.gz"),
)))
HANDOFFS_DIR = os.path.join(HOME, ".config", "ai", "handoffs")
LATEST_HANDOFF_MD = os.path.join(HUB_DATA_DIR, "LATEST_HANDOFF.md")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
    finally:
        os.umask(old_umask)
    return conn


def write_private_text(path, content):
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def extract_codex_text(content):
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts).strip()
    return str(content)


def parse_and_insert_codex_stream(conn, file_obj, fname, mtime, cur):
    session_id = fname.replace("rollout-", "").replace(".jsonl", "")
    turns = []
    turn_idx = 0
    first_user = ""
    project_path = HOME
    model_name = "codex-o3-mini"
    tool_calls = []

    for line in file_obj:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="ignore")
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue

        ev_type = d.get("type", "")
        payload = d.get("payload") or {}
        ts = d.get("timestamp") or mtime

        if ev_type == "session_meta":
            if payload.get("cwd"):
                project_path = payload.get("cwd")
            if payload.get("model_provider"):
                model_name = payload.get("model_provider")

        elif ev_type == "response_item":
            p_type = payload.get("type")
            role = payload.get("role")
            raw_c = payload.get("content")

            if p_type == "message":
                text = extract_codex_text(raw_c)
                if role == "user":
                    if not first_user and text and not text.startswith("# AGENTS.md"):
                        first_user = text[:200]
                    turns.append({
                        "turn_index": turn_idx,
                        "role": "user",
                        "user_query": text,
                        "agent_response": None,
                        "thinking": None,
                        "timestamp": ts
                    })
                    turn_idx += 1
                elif role in ("assistant", "agent"):
                    turns.append({
                        "turn_index": turn_idx,
                        "role": "assistant",
                        "user_query": None,
                        "agent_response": text,
                        "thinking": None,
                        "timestamp": ts
                    })
                    turn_idx += 1

            elif p_type in ("custom_tool_call", "function_call"):
                tool_name = payload.get("name") or "tool"
                args = payload.get("input") or {}
                tool_calls.append({
                    "name": tool_name,
                    "args": args,
                    "timestamp": ts
                })

    summary = first_user if first_user else f"Codex Session {session_id[:12]}"
    cur.execute("""
        INSERT INTO sessions (session_id, agent_type, project_path, model_name, started_at, ended_at, turn_count, status, summary, raw_source_path, updated_at)
        VALUES (?, 'codex', ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            turn_count = excluded.turn_count,
            summary = excluded.summary,
            updated_at = excluded.updated_at
    """, (session_id, project_path, model_name, mtime, mtime, len(turns), summary, fname, mtime))

    for t in turns:
        cur.execute("""
            INSERT OR REPLACE INTO turns (session_id, agent_type, turn_index, role, user_query, agent_response, thinking, turn_timestamp)
            VALUES (?, 'codex', ?, ?, ?, ?, ?, ?)
        """, (session_id, t["turn_index"], t["role"], t["user_query"], t["agent_response"], t["thinking"], t["timestamp"]))

    for tc in tool_calls:
        cur.execute("""
            INSERT INTO tool_executions (session_id, tool_name, tool_input, status, executed_at)
            VALUES (?, ?, ?, 'SUCCESS', ?)
        """, (session_id, tc["name"], json.dumps(tc["args"], ensure_ascii=False)[:500], tc["timestamp"]))


def ingest_codex_sessions(conn):
    """OpenAI Codex 세션 수집"""
    print("[Ingest] Scanning Codex sessions...")
    cur = conn.cursor()
    count = 0

    pattern = os.path.join(CODEX_SESSIONS_DIR, "*", "*", "*", "rollout-*.jsonl")
    files = glob.glob(pattern)

    for filepath in files:
        fname = os.path.basename(filepath)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                parse_and_insert_codex_stream(conn, f, fname, mtime, cur)
            conn.commit()
            count += 1
        except Exception:
            conn.rollback()

    if os.path.exists(CODEX_BACKUP_TAR):
        try:
            with tarfile.open(CODEX_BACKUP_TAR, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.endswith(".jsonl"):
                        fname = os.path.basename(member.name)
                        mtime = datetime.datetime.fromtimestamp(member.mtime).strftime("%Y-%m-%d %H:%M:%S")
                        f = tar.extractfile(member)
                        if f:
                            parse_and_insert_codex_stream(conn, f, fname, mtime, cur)
                            conn.commit()
                            count += 1
        except Exception:
            conn.rollback()

    print(f"[Ingest] Ingested {count} Codex sessions.")


def ingest_claude_sessions(conn, limit_files=100):
    """Claude Code 세션 JSONL 파일 수집"""
    print("[Ingest] Scanning Claude Code sessions...")
    pattern = os.path.join(CLAUDE_PROJECTS_DIR, "*", "*.jsonl")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    count = 0

    for filepath in files[:limit_files]:
        session_id = os.path.splitext(os.path.basename(filepath))[0]
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")
        proj_folder = os.path.basename(os.path.dirname(filepath))
        project_path = proj_folder.replace("-", "/")
        if not project_path.startswith("/"):
            project_path = "/" + project_path

        first_user_query = ""
        model_name = "claude-sonnet"
        turns = []
        turn_idx = 0

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue

                    ev_type = d.get("type", "")
                    
                    if ev_type in ("session-metadata", "session_start"):
                        if d.get("model"):
                            model_name = d.get("model")
                        if d.get("cwd"):
                            project_path = d.get("cwd")

                    elif ev_type in ("user-input", "user"):
                        content = d.get("content") or d.get("text") or d.get("query") or ""
                        if isinstance(content, list):
                            content = " ".join(str(c) for c in content)
                        content = str(content)
                        if not first_user_query and content:
                            first_user_query = content[:200]
                        turns.append({
                            "turn_index": turn_idx,
                            "role": "user",
                            "user_query": content,
                            "agent_response": None,
                            "thinking": None,
                            "timestamp": d.get("timestamp") or mtime
                        })
                        turn_idx += 1

                    elif ev_type in ("model-response", "assistant", "assistant-response"):
                        content = d.get("content") or d.get("text") or d.get("response") or ""
                        thinking = d.get("thinking") or ""
                        if isinstance(content, list):
                            content = " ".join(str(c) for c in content)
                        content = str(content)
                        turns.append({
                            "turn_index": turn_idx,
                            "role": "assistant",
                            "user_query": None,
                            "agent_response": content,
                            "thinking": str(thinking) if thinking else None,
                            "timestamp": d.get("timestamp") or mtime
                        })
                        turn_idx += 1

        except Exception:
            continue

        try:
            cur = conn.cursor()
            summary = first_user_query if first_user_query else f"Claude Session {session_id[:8]}"
            cur.execute("""
                INSERT INTO sessions (session_id, agent_type, project_path, model_name, started_at, ended_at, turn_count, status, summary, raw_source_path, updated_at)
                VALUES (?, 'claude', ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    turn_count = excluded.turn_count,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
            """, (session_id, project_path, model_name, mtime, mtime, len(turns), summary, filepath, mtime))

            for t in turns:
                cur.execute("""
                    INSERT OR REPLACE INTO turns (session_id, agent_type, turn_index, role, user_query, agent_response, thinking, turn_timestamp)
                    VALUES (?, 'claude', ?, ?, ?, ?, ?, ?)
                """, (session_id, t["turn_index"], t["role"], t["user_query"], t["agent_response"], t["thinking"], t["timestamp"]))

            conn.commit()
            count += 1
        except Exception:
            conn.rollback()

    print(f"[Ingest] Ingested {count} Claude sessions.")


def ingest_agy_sessions(conn, limit_files=100):
    """Antigravity 세션 transcript.jsonl 수집"""
    print("[Ingest] Scanning Antigravity sessions...")
    pattern = os.path.join(AGY_BRAIN_DIR, "*", ".system_generated", "logs", "transcript.jsonl")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    count = 0

    for filepath in files[:limit_files]:
        parts = filepath.split(os.sep)
        session_id = parts[-4] if len(parts) >= 4 else "unknown"
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d %H:%M:%S")

        turns = []
        turn_idx = 0
        first_user = ""
        project_path = HOME
        model_name = "gemini-3.8-flash"

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue

                    source = d.get("source", "")
                    step_type = d.get("type", "")
                    content = d.get("content") or ""
                    thinking = d.get("thinking") or ""
                    tool_calls = d.get("tool_calls") or []
                    created_at = d.get("created_at") or mtime

                    if isinstance(content, list):
                        content = " ".join(str(c) for c in content)
                    content = str(content)

                    if source == "USER_EXPLICIT" or step_type == "USER_INPUT":
                        if not first_user and content:
                            first_user = content[:200]
                        turns.append({
                            "turn_index": turn_idx,
                            "role": "user",
                            "user_query": content,
                            "agent_response": None,
                            "thinking": None,
                            "tool_calls": [],
                            "timestamp": created_at
                        })
                        turn_idx += 1
                    elif source == "MODEL" or step_type == "PLANNER_RESPONSE":
                        turns.append({
                            "turn_index": turn_idx,
                            "role": "assistant",
                            "user_query": None,
                            "agent_response": content,
                            "thinking": str(thinking) if thinking else None,
                            "tool_calls": tool_calls,
                            "timestamp": created_at
                        })
                        turn_idx += 1

        except Exception:
            continue

        try:
            cur = conn.cursor()
            summary = first_user if first_user else f"Antigravity Session {session_id[:8]}"
            cur.execute("""
                INSERT INTO sessions (session_id, agent_type, project_path, model_name, started_at, ended_at, turn_count, status, summary, raw_source_path, updated_at)
                VALUES (?, 'agy', ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    turn_count = excluded.turn_count,
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
            """, (session_id, project_path, model_name, mtime, mtime, len(turns), summary, filepath, mtime))

            for t in turns:
                cur.execute("""
                    INSERT OR REPLACE INTO turns (session_id, agent_type, turn_index, role, user_query, agent_response, thinking, turn_timestamp)
                    VALUES (?, 'agy', ?, ?, ?, ?, ?, ?)
                """, (session_id, t["turn_index"], t["role"], t["user_query"], t["agent_response"], t["thinking"], t["timestamp"]))

                turn_row_id = cur.lastrowid
                for tc in t.get("tool_calls", []):
                    tool_name = tc.get("name") or tc.get("tool_name") or "tool"
                    args = tc.get("args") or {}
                    target = args.get("Path") or args.get("path") or args.get("CommandLine", "")[:100]
                    cur.execute("""
                        INSERT INTO tool_executions (session_id, turn_id, tool_name, target_path, tool_input, status, executed_at)
                        VALUES (?, ?, ?, ?, ?, 'SUCCESS', ?)
                    """, (session_id, turn_row_id, tool_name, str(target), json.dumps(args, ensure_ascii=False)[:500], t["timestamp"]))

            conn.commit()
            count += 1
        except Exception:
            conn.rollback()

    print(f"[Ingest] Ingested {count} Antigravity sessions.")


def ingest_handoff_memories(conn):
    """~/.config/ai/handoffs/ 의 핸즈오프 기록 수집 및 중앙 LATEST_HANDOFF.md 생성"""
    print("[Ingest] Ingesting handoff memory files...")
    handoff_files = glob.glob(os.path.join(HANDOFFS_DIR, "HANDOFF_*.md"))
    handoff_files.sort(key=os.path.getmtime, reverse=True)
    count = 0

    latest_content = ""
    if os.path.exists(os.path.join(HANDOFFS_DIR, "LATEST_HANDOFF.md")):
        with open(os.path.join(HANDOFFS_DIR, "LATEST_HANDOFF.md"), "r", encoding="utf-8") as f:
            latest_content = f.read()

    for hp in handoff_files:
        fname = os.path.basename(hp)
        parts = fname.replace(".md", "").split("_")
        agent = parts[1] if len(parts) >= 2 else "unknown"
        sess_id = "_".join(parts[2:]) if len(parts) >= 3 else fname
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(hp)).strftime("%Y-%m-%d %H:%M:%S")

        try:
            with open(hp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            
            work_done = ""
            if "직전 에이전트 응답/진행 요약" in content:
                work_done = content.split("직전 에이전트 응답/진행 요약")[-1].split("##")[0].strip()
            elif "최근 사용자 요청" in content:
                work_done = content.split("최근 사용자 요청")[-1].split("##")[0].strip()

            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO sessions (session_id, agent_type, project_path, started_at, ended_at, status, summary, updated_at)
                VALUES (?, ?, ?, ?, ?, 'HANDOFF', ?, ?)
            """, (sess_id, agent, HOME, mtime, mtime, work_done[:200] if work_done else "Handoff Snapshot", mtime))

            cur.execute("""
                INSERT INTO handoffs (session_id, source_agent, cwd, work_done, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (sess_id, agent, HOME, work_done, mtime))
            conn.commit()
            count += 1
        except Exception:
            continue

    if latest_content:
        write_private_text(LATEST_HANDOFF_MD, latest_content)
        print(f"[Ingest] Synced central {LATEST_HANDOFF_MD}")

    print(f"[Ingest] Ingested {count} handoff memories.")


def main():
    old_umask = os.umask(0o077)
    try:
        conn = get_db()
        try:
            ingest_claude_sessions(conn)
            ingest_agy_sessions(conn)
            ingest_codex_sessions(conn)
            ingest_handoff_memories(conn)
            print("[Ingest] All done successfully!")
        finally:
            conn.close()
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    main()
