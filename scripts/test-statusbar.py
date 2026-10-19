#!/usr/bin/env python3
"""세션 격리·한도 구간·부분 기록·tmux 배치를 검증한다."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('footer', str(HERE.parent / 'codex/statusbar.py'))
footer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(footer)


def plain(text):
    return re.sub(r'#\[[^\]]*\]', '', text)


state = {'cwd': '/tmp/project'}
footer.apply_event(state, {'payload': {'type': 'token_count', 'info': {
    'model_context_window': 1000, 'last_token_usage': {'total_tokens': 200},
    'total_token_usage': {'total_tokens': 50000}}, 'rate_limits': {
        'primary': {'window_minutes': 10080, 'used_percent': 30}}}})
assert state['context'] == 80
assert state['weekly'] == 70 and 'five_hour' not in state
footer.apply_event(state, {'payload': {'type': 'token_count', 'rate_limits': {
    'limit_id': 'codex', 'primary': {'window_minutes': 300, 'used_percent': 60}}}})
assert state['weekly'] == 70 and state['five_hour'] == 40
footer.apply_event(state, {'payload': {'type': 'token_count', 'rate_limits': {
    'limit_id': 'other-model', 'primary': {'window_minutes': 300, 'used_percent': 99}}}})
assert state['five_hour'] == 40
for width in (35, 48, 60, 80, 100, 150):
    rows = footer.render(state, width, 'main')
    assert len(rows) == 2 and all('\n' not in row for row in rows)
    assert all(len(plain(row)) <= width for row in rows), (width, [plain(row) for row in rows])
assert '##' in footer.clean('#[fg=red]evil\n')
assert footer.launch_options(['-c', 'foo=true', 'exec', 'hi']) is None
assert footer.launch_options(['--help']) is None
assert footer.launch_options(['--remote=ws://localhost']) is None
assert footer.launch_options(['resume', '--last']) is not None

with tempfile.TemporaryDirectory(prefix='codex-statusbar-test-') as name:
    root = Path(name)
    rollout = root / 'sessions' / 'rollout-test.jsonl'
    rollout.parent.mkdir()
    events = [
        {'type': 'session_meta', 'payload': {'source': 'cli', 'id': 'test-session', 'cwd': '/tmp/project', 'timestamp': '2026-10-19'}},
        {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'high'}},
        {'payload': {'type': 'token_count', 'info': {'model_context_window': 1000, 'last_token_usage': {'total_tokens': 200}},
                     'rate_limits': {'primary': {'window_minutes': 300, 'used_percent': 25}, 'secondary': {'window_minutes': 10080, 'used_percent': 63}}}},
    ]
    rollout.write_text(''.join(json.dumps(x) + '\n' for x in events) + '{"type":')
    parsed = {'cwd': '/tmp'}
    offset = footer.read_events(rollout, parsed, 0)
    assert parsed['context'] == 80 and parsed['weekly'] == 37
    assert offset < rollout.stat().st_size
    with rollout.open('a') as f:
        f.write('"turn_context","payload":{"model":"gpt-6-sol"}}\n')
    footer.read_events(rollout, parsed, offset)
    assert parsed['model'] == 'gpt-6-sol'
    # 별개 프로세스가 연 기록을 선택하지 않는지 확인한다.
    foreign = subprocess.Popen(['python3', '-c', 'import time; f=open(' + repr(str(rollout)) + '); time.sleep(10)'])
    own = subprocess.Popen(['sleep', '10'])
    try:
        time.sleep(0.2)
        assert footer.find_rollout(own.pid) is None
        assert footer.find_rollout(foreign.pid) == rollout
    finally:
        foreign.terminate()
        own.terminate()
        foreign.wait()
        own.wait()
    server = 'codex-footer-check-{}'.format(os.getpid())
    conf = root / 'tmux.conf'
    for i, row in enumerate(footer.render(state, 100, 'main')):
        (root / ('row' + str(i))).write_text(row + '\n')
    conf.write_text("set -g status 2\nset -g status-interval 1\n" + ''.join(
        "set -g status-format[{}] '#(cat {}/row{})'\n".format(i, root, i) for i in (0, 1)))
    try:
        subprocess.run(['tmux', '-L', server, '-f', str(conf), 'new-session', '-d', '-x', '100', '-y', '24', 'sleep 10'], check=True)
        settings = subprocess.check_output(['tmux', '-L', server, 'show-options', '-g', 'status'], text=True)
        assert settings.strip() == 'status 2'
        data = subprocess.check_output(['tmux', '-L', server, 'show-options', '-g', 'status-format'], text=True)
        assert 'status-format[0]' in data and 'status-format[1]' in data
    finally:
        subprocess.run(['tmux', '-L', server, 'kill-server'], stderr=subprocess.DEVNULL)

print('PASS: context/quota windows, missing data, escaping, and CLI passthrough')
print('PASS: incremental/partial transcript reads and process isolation')
print('PASS: two tmux status rows and narrow terminal layout')

# 실제 기록 파일을 여는 CLI fixture로 수집 루프를 검증한다.
# 실제 Codex와 동일한 /proc 파일 연결 경로를 사용한다.
with tempfile.TemporaryDirectory(prefix='codex-collector-test-') as name:
    root = Path(name)
    sessions = root / 'sessions'
    sessions.mkdir()
    state_dir = root / 'state'
    state_dir.mkdir()
    (state_dir / 'launch.json').write_text(json.dumps({'args': [], 'cwd': str(root), 'model': ''}))
    fake = root / 'fake-codex'
    payload = [
        {'type': 'session_meta', 'payload': {'source': 'cli', 'id': 'own-exact-session', 'cwd': str(root), 'timestamp': '2026-10-19'}},
        {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol', 'effort': 'high'}},
        {'payload': {'type': 'token_count', 'info': {'model_context_window': 1000, 'last_token_usage': {'total_tokens': 200}},
                     'rate_limits': {'primary': {'window_minutes': 10080, 'used_percent': 63}, 'secondary': {'window_minutes': 300, 'used_percent': 25}}}},
    ]
    fake.write_text('#!/usr/bin/env python3\nimport time\nf=open(' + repr(str(sessions / 'rollout-own.jsonl')) + ',"w")\nf.write(' + repr(''.join(json.dumps(x) + '\n' for x in payload)) + ')\nf.flush()\ntime.sleep(3)\nraise SystemExit(7)\n')
    fake.chmod(0o700)
    previous = footer.REAL
    footer.REAL = str(fake)
    try:
        code = footer.run(str(state_dir))
        actual = json.loads((state_dir / 'metrics.json').read_text())
        assert actual['session_id'] == 'own-exact-session'
        assert actual['context'] == 80 and actual['five_hour'] == 75 and actual['weekly'] == 37
        assert code == 7 and json.loads((state_dir / 'exit.json').read_text())['code'] == 7
        assert '80%' in plain((state_dir / 'row1').read_text())
    finally:
        footer.REAL = previous
print('PASS: live collector binds exact session, updates bars, and preserves exit code')
