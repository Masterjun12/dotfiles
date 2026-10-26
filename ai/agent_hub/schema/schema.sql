-- ==============================================================================
-- 3사 에이전트(Claude Code, Antigravity, OpenAI Codex) 공용 세션 및 핸즈오프 스키마
-- 위치: agent_hub.db (기본값: /data4/shared/agent_hub/agent_hub.db)
-- ==============================================================================

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

-- 1. 세션 기본 원장
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL CHECK(agent_type IN ('claude', 'agy', 'codex', 'unknown')),
    project_path TEXT,
    model_name TEXT,
    started_at TEXT,
    ended_at TEXT,
    turn_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'HANDOFF', 'COMPLETED', 'INTERRUPTED')),
    summary TEXT,
    raw_source_path TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 2. 대화 턴 원장
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    agent_type TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    user_query TEXT,
    agent_response TEXT,
    thinking TEXT,
    turn_timestamp TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(session_id, turn_index)
);

-- 3. 도구 실행 및 파일 수정 원장
CREATE TABLE IF NOT EXISTS tool_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    turn_id INTEGER REFERENCES turns(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    target_path TEXT,
    tool_input TEXT,
    tool_output TEXT,
    status TEXT DEFAULT 'SUCCESS',
    executed_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 4. 3사 공용 인수인계(핸즈오프) 원장
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    source_agent TEXT NOT NULL,
    cwd TEXT,
    git_branch TEXT,
    git_status TEXT,
    work_done TEXT,
    pending_tasks TEXT,
    context_remaining_pct REAL,
    quota_remaining_pct REAL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_type, updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_tool_session ON tool_executions(session_id, tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_target ON tool_executions(target_path);
CREATE INDEX IF NOT EXISTS idx_handoffs_created ON handoffs(created_at DESC);

-- FTS5 전문 검색 (대화 턴 검색 최적화)
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_id UNINDEXED,
    agent_type UNINDEXED,
    user_query,
    agent_response,
    thinking,
    content='turns',
    content_rowid='id'
);

-- FTS 동기화 트리거
CREATE TRIGGER IF NOT EXISTS trg_turns_ai AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, session_id, agent_type, user_query, agent_response, thinking)
    VALUES (new.id, new.session_id, new.agent_type, new.user_query, new.agent_response, new.thinking);
END;

CREATE TRIGGER IF NOT EXISTS trg_turns_ad AFTER DELETE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, session_id, agent_type, user_query, agent_response, thinking)
    VALUES('delete', old.id, old.session_id, old.agent_type, old.user_query, old.agent_response, old.thinking);
END;

CREATE TRIGGER IF NOT EXISTS trg_turns_au AFTER UPDATE ON turns BEGIN
    INSERT INTO turns_fts(turns_fts, rowid, session_id, agent_type, user_query, agent_response, thinking)
    VALUES('delete', old.id, old.session_id, old.agent_type, old.user_query, old.agent_response, old.thinking);
    INSERT INTO turns_fts(rowid, session_id, agent_type, user_query, agent_response, thinking)
    VALUES (new.id, new.session_id, new.agent_type, new.user_query, new.agent_response, new.thinking);
END;
