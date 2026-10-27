#!/usr/bin/env python3
"""
Global Automatic Session Handoff Memory Guard for Antigravity (AGY) and OpenAI Codex.
- AGY threshold:   <= 50.0% remaining (context window or active model quota)
- Codex threshold: <= 50.0% remaining (context window or 5h/weekly rate limit)
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys

AI_DIR = os.path.expanduser("~/.config/ai")
HANDOFF_DIR = os.path.join(AI_DIR, "handoffs")
MEMORY_FILE = os.path.join(AI_DIR, "MEMORY.md")
STATE_FILE = os.path.join(HANDOFF_DIR, ".handoff_state.json")


def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json_safe(path, obj):
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def get_git_summary(cwd):
    if not cwd or not os.path.isdir(cwd):
        return "N/A", []
    try:
        branch = subprocess.run(
            ["git", "-C", cwd, "--no-optional-locks", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2
        ).stdout.strip() or "DETACHED"
        status_lines = subprocess.run(
            ["git", "-C", cwd, "--no-optional-locks", "status", "--short"],
            capture_output=True, text=True, timeout=2
        ).stdout.splitlines()[:15]
        return branch, status_lines
    except Exception:
        return "N/A", []


def extract_agy_metrics_and_recent(payload):
    conv_id = (
        payload.get("conversationId")
        or payload.get("conversation_id")
        or payload.get("session_id")
        or "unknown"
    )
    workspaces = payload.get("workspacePaths") or []
    cwd = (
        payload.get("cwd")
        or (payload.get("workspace") or {}).get("current_dir")
        or (workspaces[0] if workspaces else "/data4/workspace")
    )
    transcript_path = payload.get("transcriptPath") or payload.get("transcript_path") or ""

    # Read statusline snapshot if available
    sl_data = payload if "context_window" in payload or "quota" in payload else {}
    if not sl_data:
        per_sess = f"/tmp/agy_statusline_{conv_id}.json"
        if os.path.exists(per_sess):
            sl_data = load_json_safe(per_sess)
        elif os.path.exists("/tmp/agy_statusline_payload.json"):
            cand = load_json_safe("/tmp/agy_statusline_payload.json")
            if cand.get("conversation_id") in (conv_id, None) or conv_id == "unknown":
                sl_data = cand

    ctx_rem = 100.0
    cw = sl_data.get("context_window") or {}
    if cw.get("remaining_percentage") is not None:
        ctx_rem = float(cw["remaining_percentage"])
    elif cw.get("used_percentage") is not None:
        ctx_rem = max(0.0, 100.0 - float(cw["used_percentage"]))
    elif transcript_path and os.path.exists(transcript_path):
        # Fallback heuristic from transcript byte size vs ~4MB full context
        sz = os.path.getsize(transcript_path)
        ctx_rem = max(0.0, 100.0 - (sz / (4.0 * 1024 * 1024)) * 100.0)

    quota_rem = 100.0
    quota_details = []
    quota = sl_data.get("quota")
    model_name = ""
    if isinstance(sl_data.get("model"), dict):
        model_name = (sl_data["model"].get("display_name") or sl_data["model"].get("id") or "").lower()
    elif isinstance(payload.get("modelName"), str):
        model_name = payload.get("modelName", "").lower()

    if isinstance(quota, dict):
        for k, v in quota.items():
            if not isinstance(v, dict):
                continue
            rem_pct = None
            if v.get("remaining_fraction") is not None:
                rem_pct = float(v["remaining_fraction"]) * 100.0
            elif v.get("remaining_percentage") is not None:
                rem_pct = float(v["remaining_percentage"])
            elif v.get("used_percentage") is not None:
                rem_pct = 100.0 - float(v["used_percentage"])
            if rem_pct is not None:
                quota_details.append(f"{k}:{rem_pct:.1f}%")
                # Match displayed 5h/weekly quota buckets
                if "claude" in model_name or "sonnet" in model_name or "opus" in model_name:
                    if k in ("3p-5h", "3p-weekly"):
                        quota_rem = min(quota_rem, rem_pct)
                else:
                    if k in ("gemini-5h", "gemini-weekly"):
                        quota_rem = min(quota_rem, rem_pct)

    effective_rem = min(ctx_rem, quota_rem)

    # Extract last 3 user inputs & last planner response from transcript.jsonl
    recent_users = []
    last_agent = ""
    if not transcript_path or not os.path.exists(transcript_path):
        cand_t = os.path.expanduser(
            f"~/.gemini/antigravity-cli/brain/{conv_id}/.system_generated/logs/transcript.jsonl"
        )
        if os.path.exists(cand_t):
            transcript_path = cand_t

    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-60:]
            for line in lines:
                obj = json.loads(line)
                stype = obj.get("type", "")
                content = (obj.get("content") or "").strip()
                if stype == "USER_INPUT" and content:
                    clean = content.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                    recent_users.append(clean.splitlines()[0][:200])
                elif stype == "PLANNER_RESPONSE" and content:
                    last_agent = " / ".join(l.strip() for l in content.splitlines() if l.strip())[:400]
        except Exception:
            pass

    return {
        "session_id": conv_id,
        "cwd": cwd,
        "ctx_rem": ctx_rem,
        "quota_rem": quota_rem,
        "effective_rem": effective_rem,
        "quota_summary": ", ".join(quota_details) if quota_details else "N/A",
        "recent_users": recent_users[-3:],
        "last_agent": last_agent,
    }


def extract_codex_metrics_and_recent(payload):
    sess_id = payload.get("session_id") or payload.get("thread-id") or "unknown"
    cwd = payload.get("cwd") or "/data4/workspace"
    transcript_path = payload.get("transcript_path") or ""

    if not transcript_path or not os.path.exists(transcript_path):
        codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
        candidates = sorted(
            glob.glob(os.path.join(codex_home, "sessions", "**", "*.jsonl"), recursive=True),
            key=os.path.getmtime,
        )
        if sess_id != "unknown":
            matched = [c for c in candidates if sess_id in os.path.basename(c)]
            if matched:
                transcript_path = matched[-1]
        if not transcript_path and candidates:
            transcript_path = candidates[-1]

    ctx_rem = 100.0
    quota_rem = 100.0
    quota_details = []
    recent_users = []
    last_agent = (payload.get("last_assistant_message") or payload.get("last-assistant-message") or "").strip()[:400]

    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-120:]
            for line in lines:
                if '"token_count"' in line or '"user_message"' in line or '"agent_message"' in line:
                    obj = json.loads(line)
                    p = obj.get("payload") or {}
                    ptype = p.get("type")
                    if ptype == "token_count":
                        info = p.get("info") or {}
                        win = float(info.get("model_context_window") or 475000)
                        last_u = info.get("last_token_usage") or {}
                        in_tok = float(last_u.get("input_tokens") or last_u.get("total_tokens") or 0)
                        if win > 0 and in_tok > 0:
                            ctx_rem = max(0.0, 100.0 * (1.0 - in_tok / win))
                        rl = p.get("rate_limits") or {}
                        for rk in ("primary", "secondary"):
                            rv = rl.get(rk)
                            if isinstance(rv, dict) and rv.get("used_percent") is not None:
                                rem = max(0.0, 100.0 - float(rv["used_percent"]))
                                quota_rem = min(quota_rem, rem)
                                quota_details.append(f"{rk}:{rem:.1f}%")
                    elif ptype == "user_message":
                        msg = (p.get("message") or "").strip()
                        if msg:
                            recent_users.append(msg.splitlines()[0][:200])
                    elif ptype == "agent_message" and not last_agent:
                        msg = (p.get("message") or "").strip()
                        if msg:
                            last_agent = " / ".join(l.strip() for l in msg.splitlines() if l.strip())[:400]
        except Exception:
            pass

    if payload.get("prompt"):
        recent_users.append(str(payload["prompt"]).strip().splitlines()[0][:200])

    effective_rem = min(ctx_rem, quota_rem)
    return {
        "session_id": sess_id,
        "cwd": cwd,
        "ctx_rem": ctx_rem,
        "quota_rem": quota_rem,
        "effective_rem": effective_rem,
        "quota_summary": ", ".join(quota_details[-2:]) if quota_details else "N/A",
        "recent_users": recent_users[-3:],
        "last_agent": last_agent,
    }


def write_handoff_files(agent_label, threshold_pct, info):
    os.makedirs(HANDOFF_DIR, mode=0o700, exist_ok=True)
    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    date_tag = now_dt.strftime("%Y%m%d")
    short_id = str(info["session_id"])[:12]
    branch, git_status = get_git_summary(info["cwd"])

    handoff_path = os.path.join(HANDOFF_DIR, f"HANDOFF_{agent_label}_{short_id}.md")
    latest_path = os.path.join(HANDOFF_DIR, "LATEST_HANDOFF.md")

    user_bullets = "\n".join(f"  - `{u}`" for u in info["recent_users"]) if info["recent_users"] else "  - (최근 사용자 입력 없음)"
    git_bullets = "\n".join(f"  - `{g}`" for g in git_status) if git_status else "  - `clean`"

    content = f"""# [{agent_label.upper()}] 자동 핸즈오프 메모리 (임계치 {threshold_pct:.0f}% 이하 도달)

- **생성 시각**: `{now_str}`
- **에이전트 / 세션 ID**: `{agent_label}` / `{info['session_id']}`
- **잔여 한도**: 최저 `{info['effective_rem']:.1f}%` (컨텍스트 잔여 `{info['ctx_rem']:.1f}%`, 쿼터/레이트리밋 잔여 `{info['quota_rem']:.1f}%` [{info['quota_summary']}])
- **작업 디렉터리 및 브랜치**: `{info['cwd']}` (`{branch}`)

## 1. 최근 사용자 요청 흐름
{user_bullets}

## 2. 직전 에이전트 응답/진행 요약
- {info['last_agent'] or '(진행 중 요약 대기)'}

## 3. Git 워킹트리 변경 상태 (최대 15건)
{git_bullets}

## 4. 후속 세션 인수인계 지침
- 본 문서는 `{agent_label}` 세션 한도가 `{threshold_pct:.0f}%` 이하(`{info['effective_rem']:.1f}%`)로 도달하여 훅에 의해 자동 생성되었습니다.
- 현재 세션의 에이전트는 즉시 미결 작업·검증 상태·다음 단계(Next Steps)를 아래 또는 `~/.config/ai/MEMORY.md`에 보완 기록하십시오.
"""

    central_latest = "/data4/shared/agent_hub/LATEST_HANDOFF.md"
    for target in (handoff_path, latest_path, central_latest):
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(target, 0o600)
        except Exception:
            pass

    # Record into central Agent Hub SQLite DB
    try:
        hub_db = "/data4/shared/agent_hub/agent_hub.db"
        if os.path.exists(hub_db):
            import sqlite3
            with sqlite3.connect(hub_db, timeout=5.0) as conn:
                conn.execute("""
                    INSERT INTO handoffs (session_id, source_agent, cwd, git_branch, git_status, work_done, context_remaining_pct, quota_remaining_pct, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(info["session_id"]),
                    agent_label,
                    str(info["cwd"]),
                    branch,
                    "\n".join(git_status),
                    str(info['last_agent'] or ''),
                    float(info.get('ctx_rem', 100.0)),
                    float(info.get('quota_rem', 100.0)),
                    now_str
                ))
    except Exception:
        pass

    # Also write to workspace .claude/memory if present
    cwd = info["cwd"]
    if cwd and os.path.isdir(os.path.join(cwd, ".claude", "memory")):
        ws_handoff = os.path.join(cwd, ".claude", "memory", f"project_handoff_{agent_label}_{date_tag}.md")
        try:
            with open(ws_handoff, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    # Update 1-line pointer in ~/.config/ai/MEMORY.md (idempotent per session_id)
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8", errors="ignore") as f:
                mem_txt = f.read()
            marker = f"[HANDOFF:{agent_label}:{short_id}]"
            line_entry = (
                f"- {now_dt.strftime('%Y-%m-%d')} {marker} `{agent_label}` 세션(`{short_id}`, `{info['cwd']}`) "
                f"잔여 한도 `{info['effective_rem']:.1f}%`(임계치 `{threshold_pct:.0f}%`) 도달로 자동 핸즈오프 스냅샷을 "
                f"`~/.config/ai/handoffs/LATEST_HANDOFF.md` 및 `{handoff_path}`에 생성했다.\n"
            )
            if marker not in mem_txt:
                with open(MEMORY_FILE, "a", encoding="utf-8") as f:
                    if not mem_txt.endswith("\n"):
                        f.write("\n")
                    f.write(line_entry)
        except Exception:
            pass

    return handoff_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", required=True, choices=["agy", "agy-statusline", "codex"])
    args = parser.parse_args()

    raw_in = ""
    if not sys.stdin.isatty():
        try:
            raw_in = sys.stdin.read()
        except Exception:
            raw_in = ""
    payload = {}
    if raw_in.strip():
        try:
            payload = json.loads(raw_in)
        except Exception:
            payload = {}

    if args.agent in ("agy", "agy-statusline"):
        threshold = 50.0
        info = extract_agy_metrics_and_recent(payload)
        triggered = info["effective_rem"] <= threshold

        if args.agent == "agy-statusline":
            if triggered:
                write_handoff_files("agy", threshold, info)
            return

        # Lifecycle hook for AGY (PreInvocation or Stop)
        is_stop = "terminationReason" in payload or "fullyIdle" in payload
        if not triggered:
            if is_stop:
                print(json.dumps({"decision": "allow"}))
            else:
                print(json.dumps({}))
            return

        handoff_path = write_handoff_files("agy", threshold, info)
        state = load_json_safe(STATE_FILE)
        notified_key = f"agy_notified_{info['session_id']}"

        if is_stop:
            print(json.dumps({"decision": "allow"}))
            return

        # PreInvocation: inject ephemeral reminder so AGY enriches the handoff memory
        if not state.get(notified_key):
            state[notified_key] = info["effective_rem"]
            save_json_safe(STATE_FILE, state)
            msg = (
                f"[AUTO-HANDOFF TRIGGER: AGY 잔여 한도 {info['effective_rem']:.1f}% <= 50%] "
                f"자동 핸즈오프 스냅샷이 `{handoff_path}` 및 `~/.config/ai/handoffs/LATEST_HANDOFF.md`에 생성되었습니다. "
                f"이번 턴에 현재 작업 진행 상황, 미결 과제, 검증 결과, 다음 단계를 핸즈오프 파일과 `~/.config/ai/MEMORY.md`에 즉시 요약·갱신하고, "
                f"답변 마지막 줄에 `[자동 핸즈오프 알림: 잔여 한도 {info['effective_rem']:.1f}% 도달로 공용 허브에 인계를 완료했습니다]`를 반드시 출력하십시오."
            )
            print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
        else:
            print(json.dumps({}))
        return

    if args.agent == "codex":
        threshold = 50.0
        info = extract_codex_metrics_and_recent(payload)
        triggered = info["effective_rem"] <= threshold
        event_name = payload.get("hook_event_name") or ""

        if not triggered:
            print(json.dumps({"continue": True}))
            return

        handoff_path = write_handoff_files("codex", threshold, info)
        state = load_json_safe(STATE_FILE)
        notified_key = f"codex_notified_{info['session_id']}"

        if event_name == "UserPromptSubmit" and not state.get(notified_key):
            state[notified_key] = info["effective_rem"]
            save_json_safe(STATE_FILE, state)
            msg = (
                f"[AUTO-HANDOFF TRIGGER: Codex 잔여 한도 {info['effective_rem']:.1f}% <= 50%] "
                f"자동 핸즈오프 스냅샷이 `{handoff_path}` 및 `~/.config/ai/handoffs/LATEST_HANDOFF.md`에 생성되었습니다. "
                f"현재 진행 상황·미결 이슈·다음 단계를 핸즈오프 파일과 `~/.config/ai/MEMORY.md`에 즉시 보완 기록하고, "
                f"답변 마지막 줄에 `[자동 핸즈오프 알림: 잔여 한도 {info['effective_rem']:.1f}% 도달로 공용 허브에 인계를 완료했습니다]`를 반드시 출력하십시오."
            )
            print(
                json.dumps(
                    {
                        "continue": True,
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": msg,
                        },
                    }
                )
            )
        else:
            print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
