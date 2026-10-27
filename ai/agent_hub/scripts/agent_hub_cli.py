#!/usr/bin/env python3
"""
3사(Claude, Antigravity, Codex) 공용 세션 및 핸즈오프 허브 CLI 도구
사용법:
  agent-hub search <키워드>       - 3사 대화 및 해결 코드 초고속 FTS 검색
  agent-hub handoff             - 최신 인수인계 원장 확인
  agent-hub sessions            - 최근 3사 세션 목록 조회
  agent-hub sync                - 3사 세션 증분 동기화 실행
  agent-hub stats               - 세션 적재 통계 요약
"""

import sys
import os
import sqlite3
import argparse

DEFAULT_DB_DIR = "/data4/shared/agent_hub" if os.path.isdir("/data4/shared/agent_hub") else os.path.expanduser("~/.config/ai/agent_hub")
DB_PATH = os.getenv("AGENT_HUB_DB", os.path.join(DEFAULT_DB_DIR, "agent_hub.db"))
LATEST_HANDOFF_MD = os.path.join(DEFAULT_DB_DIR, "LATEST_HANDOFF.md")
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def get_conn():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB file not found: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_search(args):
    query = args.query
    limit = args.limit
    agent_filter = args.agent

    conn = get_conn()
    cur = conn.cursor()

    sql = """
        SELECT t.agent_type, t.session_id, t.role, t.user_query, t.agent_response, t.turn_timestamp, s.project_path
        FROM turns_fts f
        JOIN turns t ON f.rowid = t.id
        LEFT JOIN sessions s ON t.session_id = s.session_id
        WHERE turns_fts MATCH ?
    """
    params = [query]
    if agent_filter:
        sql += " AND t.agent_type = ?"
        params.append(agent_filter)

    sql += f" ORDER BY t.id DESC LIMIT {limit}"

    try:
        cur.execute(sql, params)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        return

    if not rows:
        print(f"[-] 검색 결과 없음: '{query}'")
        return

    print(f"\n[+] '{query}' 검색 결과 (최신 {len(rows)}건):")
    print("=" * 80)
    for r in rows:
        agent_tag = f"[{r['agent_type'].upper():6s}]"
        ts = r["turn_timestamp"] or "N/A"
        sess = r["session_id"][:12]
        cwd = r["project_path"] or "N/A"

        print(f"{agent_tag} {ts} | 세션: {sess} | 작업경로: {cwd}")
        if r["user_query"]:
            q = r["user_query"].strip().replace("\n", " ")
            print(f"  - 질문: {q[:120]}...")
        if r["agent_response"]:
            ans = r["agent_response"].strip().replace("\n", " ")
            print(f"  - 답변: {ans[:140]}...")
        print("-" * 80)


def cmd_handoff(args):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT h.source_agent, h.session_id, h.work_done, h.created_at
        FROM handoffs h
        ORDER BY h.id DESC LIMIT ?
    """, (args.limit,))
    rows = cur.fetchall()

    if not rows:
        if os.path.exists(LATEST_HANDOFF_MD):
            with open(LATEST_HANDOFF_MD, "r", encoding="utf-8") as f:
                print(f.read())
        else:
            print("[-] 등록된 핸즈오프 기록이 없습니다.")
        return

    print("\n[+] 3사 최신 인수인계(Handoff) 기록:")
    print("=" * 80)
    for r in rows:
        agent_tag = f"[{r['source_agent'].upper():6s}]"
        print(f"{agent_tag} 시각: {r['created_at']} | 세션: {r['session_id'][:12]}")
        if r["work_done"]:
            lines = [l.strip() for l in r["work_done"].splitlines() if l.strip()]
            for l in lines[:5]:
                print(f"  {l}")
        print("-" * 80)


def cmd_sessions(args):
    conn = get_conn()
    cur = conn.cursor()
    sql = """
        SELECT agent_type, session_id, turn_count, started_at, summary, project_path
        FROM sessions
    """
    params = []
    if args.agent:
        sql += " WHERE agent_type = ?"
        params.append(args.agent)

    sql += f" ORDER BY updated_at DESC LIMIT {args.limit}"
    cur.execute(sql, params)
    rows = cur.fetchall()

    print(f"\n[+] 최근 3사 세션 목록 ({len(rows)}건):")
    print(f"{'AGENT':8s} | {'시각':19s} | {'턴수':4s} | {'세션 ID':12s} | 요약")
    print("-" * 80)
    for r in rows:
        tag = f"[{r['agent_type'].upper()}]"
        ts = (r["started_at"] or "N/A")[:19]
        tc = str(r["turn_count"])
        sid = r["session_id"][:12]
        summ = (r["summary"] or "").replace("\n", " ")[:40]
        print(f"{tag:8s} | {ts:19s} | {tc:>4s} | {sid:12s} | {summ}")


def cmd_stats(args):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT agent_type, COUNT(*) as cnt FROM sessions GROUP BY agent_type")
    sess_counts = {r["agent_type"]: r["cnt"] for r in cur.fetchall()}

    cur.execute("SELECT COUNT(*) FROM turns")
    total_turns = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM tool_executions")
    total_tools = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM handoffs")
    total_handoffs = cur.fetchone()[0]

    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)

    print("\n[+] 3사 중앙 에이전트 허브 (Agent Hub) 통계")
    print("=" * 50)
    print(f"- DB 경로: {DB_PATH} ({db_size:.2f} MB)")
    print(f"- Claude 세션:      {sess_counts.get('claude', 0):>5d} 개")
    print(f"- Antigravity 세션: {sess_counts.get('agy', 0):>5d} 개")
    print(f"- Codex 세션:       {sess_counts.get('codex', 0):>5d} 개")
    print(f"- 총 대화 턴(Turns):{total_turns:>5d} 건")
    print(f"- 총 도구 실행:     {total_tools:>5d} 건")
    print(f"- 공용 핸즈오프:    {total_handoffs:>5d} 건")
    print("=" * 50)


def cmd_sync(args):
    print("[+] 3사 세션 동기화 실행 중...")
    from ingest_sessions import main as ingest_main

    ingest_main()


def main():
    parser = argparse.ArgumentParser(description="3사 공용 에이전트 허브 CLI")
    sub = parser.add_subparsers(dest="command")

    # search
    p_s = sub.add_parser("search", help="3사 대화 및 코드 검색")
    p_s.add_argument("query", help="검색할 키워드")
    p_s.add_argument("--limit", type=int, default=5, help="최대 결과 수")
    p_s.add_argument("--agent", choices=["claude", "agy", "codex"], help="특정 에이전트만 필터")

    # handoff
    p_h = sub.add_parser("handoff", help="최신 인수인계 내역 확인")
    p_h.add_argument("--limit", type=int, default=3, help="출력할 핸즈오프 개수")

    # sessions
    p_sess = sub.add_parser("sessions", help="세션 목록 조회")
    p_sess.add_argument("--limit", type=int, default=10, help="출력할 세션 개수")
    p_sess.add_argument("--agent", choices=["claude", "agy", "codex"], help="특정 에이전트 필터")

    # stats
    sub.add_parser("stats", help="적재 통계 확인")

    # sync
    sub.add_parser("sync", help="3사 세션 즉시 동기화")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "search": cmd_search,
        "handoff": cmd_handoff,
        "sessions": cmd_sessions,
        "stats": cmd_stats,
        "sync": cmd_sync,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
