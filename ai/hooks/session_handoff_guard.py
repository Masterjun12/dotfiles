#!/usr/bin/env python3
"""세션별 실제 잔여량으로 핸즈오프를 기록하며 작업을 차단하지 않는다."""
import argparse
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

AI_DIR = Path.home() / '.config/ai'
HANDOFF_DIR = AI_DIR / 'handoffs'


def load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix='.handoff-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(value)
        os.chmod(temp, 0o600)
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def percent(value):
    try:
        value = float(value)
        return max(0.0, min(100.0, value)) if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def tail_events(path):
    try:
        with Path(path).open('rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 1024 * 1024))
            lines = f.read().splitlines()
        for line in lines:
            try:
                yield json.loads(line)
            except ValueError:
                continue
    except OSError:
        return


def metrics(agent, payload, session):
    cache = HANDOFF_DIR / 'status' / (agent + '-' + session + '.json')
    data = payload
    if not ('context_window' in payload or 'quota' in payload):
        cached = load(cache)
        if cached:
            data = cached
    context, quotas = None, {}
    cw = data.get('context_window') or {}
    context = percent(cw.get('remaining_percentage'))
    if context is None and percent(cw.get('used_percentage')) is not None:
        context = 100 - percent(cw['used_percentage'])
    quota = data.get('quota') or {}
    model = data.get('model') or payload.get('modelName') or ''
    if isinstance(model, dict):
        model = model.get('display_name') or model.get('id') or ''
    prefix = '3p-' if any(word in str(model).lower() for word in ('claude', 'sonnet', 'opus')) else 'gemini-'
    for key, item in quota.items():
        if not isinstance(item, dict) or not key.startswith(prefix):
            continue
        val = percent(item.get('remaining_percentage'))
        if item.get('remaining_fraction') is not None:
            try:
                val = percent(float(item['remaining_fraction']) * 100)
            except (TypeError, ValueError):
                val = None
        if val is None and percent(item.get('used_percentage')) is not None:
            val = 100 - percent(item['used_percentage'])
        if val is not None:
            quotas[key] = val
    path = payload.get('transcript_path') or payload.get('transcriptPath')
    if agent == 'codex' and not path:
        root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'sessions'
        matches = list(root.glob('**/*' + session + '*.jsonl'))
        if len(matches) == 1:
            path = str(matches[0])
    if agent == 'codex' and path:
        try:
            with Path(path).open() as f:
                first = json.loads(f.readline())
            if first.get('type') == 'session_meta':
                meta = first.get('payload') or {}
                recorded = meta.get('id') or meta.get('session_id')
                if recorded and recorded != session:
                    path = None
        except (OSError, ValueError):
            path = None
    users, response = [], str(payload.get('last_assistant_message') or '')[:400]
    if path:
        for event in tail_events(path):
            p = event.get('payload') or {}
            if agent == 'codex' and p.get('type') == 'token_count':
                info = p.get('info') or {}
                window = info.get('model_context_window')
                used = (info.get('last_token_usage') or {}).get('total_tokens')
                try:
                    if window and used is not None:
                        context = percent(100 * (1 - used / window))
                except (TypeError, ZeroDivisionError):
                    pass
                limits = p.get('rate_limits') or {}
                if limits.get('limit_id') in (None, 'codex'):
                    for slot in ('primary', 'secondary'):
                        item = limits.get(slot) or {}
                        minutes = item.get('window_minutes')
                        used_pct = percent(item.get('used_percent'))
                        if item.get('resets_at') and item['resets_at'] <= time.time():
                            quotas.pop(str(minutes), None)
                            continue
                        if minutes in (300, 10080) and used_pct is not None:
                            quotas[str(minutes)] = 100 - used_pct
            if p.get('type') == 'user_message':
                users.append(str(p.get('message') or '')[:200])
            if p.get('type') == 'agent_message':
                response = str(p.get('message') or '')[:400]
            if event.get('type') == 'USER_INPUT':
                users.append(str(event.get('content') or '')[:200])
            if event.get('type') == 'PLANNER_RESPONSE':
                response = str(event.get('content') or '')[:400]
    if payload.get('prompt'):
        users.append(str(payload['prompt'])[:200])
    values = ([context] if context is not None else []) + list(quotas.values())
    return {'session_id': session, 'cwd': payload.get('cwd') or (payload.get('workspace') or {}).get('current_dir') or
            (payload.get('workspacePaths') or [os.getcwd()])[0], 'context': context, 'quotas': quotas,
            'remaining': min(values) if values else None, 'users': users[-3:], 'response': response}


def snapshot(agent, threshold, data):
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (HANDOFF_DIR / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        session = data['session_id']
        path = HANDOFF_DIR / ('HANDOFF_' + agent + '_' + session + '.md')
        cwd = data['cwd']
        try:
            git = subprocess.run(['git', '-C', cwd, '--no-optional-locks', 'status', '--short'],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2)
            changes = git.stdout.splitlines()[:15]
        except (OSError, subprocess.TimeoutExpired):
            changes = []
        now = datetime.datetime.now().isoformat(timespec='seconds')
        content = ('# 자동 핸즈오프\n\n- 에이전트: ' + agent + '\n- 세션: ' + session + '\n- 생성: ' + now +
                   '\n- 작업 경로: ' + cwd + '\n- 잔여 한도: {:.1f}% (임계치 {:.0f}%)\n'.format(data['remaining'], threshold) +
                   '\n## 최근 사용자 요청\n\n' + '\n'.join('- ' + x.replace('\n', ' ') for x in data['users']) +
                   '\n\n## 최근 응답\n\n' + data['response'] + '\n\n## Git 상태\n\n' +
                   '\n'.join('- ' + x for x in changes) +
                   '\n\n## 보완할 인수인계\n\n현재 진행 상황·미결 과제·검증 결과·다음 행동을 기록한다.\n')
        # 에이전트가 보완한 문서는 반복 훅으로 덮어쓰지 않는다.
        if not path.exists():
            atomic(path, content)
        atomic(path.with_suffix('.json'), json.dumps(data, ensure_ascii=False, indent=2))
        latest = HANDOFF_DIR / 'LATEST_HANDOFF.md'
        if session not in (latest.read_text() if latest.exists() else ''):
            atomic(latest, path.read_text())
        project_memory = Path(cwd) / '.claude/memory'
        if project_memory.is_dir():
            target = project_memory / ('project_handoff_' + agent + '_' + datetime.date.today().strftime('%Y%m%d') + '.md')
            if not target.exists():
                atomic(target, path.read_text())
        memory = AI_DIR / 'MEMORY.md'
        marker = '[HANDOFF:' + agent + ':' + session + ']'
        if memory.exists() and marker not in memory.read_text():
            with memory.open('a') as f:
                f.write('\n- ' + now + ' ' + marker + ' ' + str(path) + '\n')
        return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', required=True, choices=['agy', 'codex', 'claude', 'agy-statusline'])
    parser.add_argument('--statusline', action='store_true')
    args = parser.parse_args()
    agent = 'agy' if args.agent == 'agy-statusline' else args.agent
    statusline = args.statusline or args.agent == 'agy-statusline'
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        payload = {}
    session = payload.get('session_id') or payload.get('conversationId') or payload.get('conversation_id') or payload.get('thread-id')
    if not session or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', str(session)):
        if not statusline:
            print('{}' if agent == 'agy' else '{"continue":true}')
        return
    if statusline:
        # 상태줄 입력에서 필요한 잔여량만 저장한다. 원문·인증값은 캐시하지 않는다.
        safe = {key: payload[key] for key in ('context_window', 'quota', 'model') if key in payload}
        atomic(HANDOFF_DIR / 'status' / (agent + '-' + session + '.json'), json.dumps(safe))
    data = metrics(agent, payload, session)
    threshold = float(os.environ.get('AI_HANDOFF_' + agent.upper() + '_THRESHOLD', '50' if agent == 'agy' else '30'))
    path = None
    if data['remaining'] is not None and data['remaining'] <= threshold:
        path = snapshot(agent, threshold, data)
    if statusline:
        return
    event = payload.get('hook_event_name')
    msg = '[AUTO-HANDOFF TRIGGER] ' + str(path) + ' 및 MEMORY.md에 진행 상황·미결 과제·검증·다음 행동을 보완한다.'
    if agent == 'agy':
        is_stop = 'terminationReason' in payload or 'fullyIdle' in payload
        print(json.dumps({'decision': 'allow'} if is_stop else {'injectSteps': [{'ephemeralMessage': msg}]} if path else {}))
    elif path and event == 'UserPromptSubmit':
        print(json.dumps({'continue': True, 'hookSpecificOutput': {'hookEventName': event, 'additionalContext': msg}}))
    else:
        print('{"continue":true}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError):
        # 기록 실패로 사용자 요청이나 종료를 차단하지 않는다.
        pass
