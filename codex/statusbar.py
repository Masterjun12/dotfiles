#!/usr/bin/env python3
"""Linux/WSL Codex 2줄 표시줄: 실행한 세션의 기록만 읽는다."""
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time

def real_binary():
    override = os.environ.get('CODEX_REAL_BIN')
    if override:
        return override
    for folder in os.get_exec_path():
        path = Path(folder) / 'codex'
        if not path.is_file() or not os.access(str(path), os.X_OK):
            continue
        try:
            with path.open('rb') as f:
                head = f.read(2048)
            if b'codex-statusbar' in head or b'--_run-statusbar' in head:
                continue
        except OSError:
            continue
        return str(path)
    return None


REAL = real_binary()
APP = str(Path(__file__).resolve())
BASE = Path.home() / '.local/state/codex-statusbar'
COMMANDS = set('exec review login logout mcp plugin app-server remote-control completion update doctor sandbox debug apply queue archive delete migrate-rollouts unarchive cloud exec-server features help'.split())
VALUE_FLAGS = set('-c --config -i --image -m --model -p --profile -s --sandbox -C --cd --add-dir -a --ask-for-approval --enable --disable --remote --remote-auth-token-env'.split())


def clean(value, limit=60):
    value = re.sub(r'[\x00-\x1f\x7f]', '', str(value))
    return value[:limit].replace('#', '##')


def launch_options(args):
    cwd, model, positional = os.getcwd(), '', None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--':
            break
        if arg in ('-h', '--help', '-V', '--version', '--remote') or arg.startswith('--remote='):
            return None
        if arg in VALUE_FLAGS and i + 1 < len(args):
            value = args[i + 1]
            if arg in ('-C', '--cd'):
                cwd = os.path.abspath(os.path.expanduser(value))
            if arg in ('-m', '--model'):
                model = value
            i += 2
            continue
        if arg.startswith('--cd='):
            cwd = os.path.abspath(os.path.expanduser(arg.split('=', 1)[1]))
        if arg.startswith('--model='):
            model = arg.split('=', 1)[1]
        if not arg.startswith('-') and positional is None:
            positional = arg
        i += 1
    if positional in COMMANDS:
        return None
    return cwd, model


def atomic(path, value):
    tmp = str(path) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(value)
    os.replace(tmp, str(path))


def descendants(pid):
    pending, result = [pid], []
    while pending and len(result) < 40:
        current = pending.pop(0)
        if current in result:
            continue
        result.append(current)
        try:
            children = Path('/proc/{0}/task/{0}/children'.format(current)).read_text().split()
            pending.extend(int(x) for x in children)
        except OSError:
            pass
    return result


def find_rollout(pid):
    candidates = {}
    for process in descendants(pid):
        try:
            fds = list(Path('/proc/{}/fd'.format(process)).iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(str(fd))
                if '/sessions/' not in target or not target.endswith('.jsonl'):
                    continue
                path = Path(target)
                if path in candidates:
                    continue
                with path.open(encoding='utf-8') as f:
                    meta = json.loads(f.readline()).get('payload', {})
                # 하위 에이전트의 사용량은 부모 창에 섞지 않는다.
                if isinstance(meta.get('source'), dict):
                    continue
                candidates[path] = str(meta.get('timestamp', ''))
            except (OSError, ValueError):
                continue
    return max(candidates, key=candidates.get) if candidates else None


def apply_event(state, event):
    payload = event.get('payload') or {}
    kind = event.get('type')
    if kind == 'session_meta':
        state['cwd'] = payload.get('cwd') or state['cwd']
        state['session_id'] = payload.get('id') or payload.get('session_id')
    if kind == 'turn_context':
        state['model'] = payload.get('model') or state.get('model', '')
        state['effort'] = payload.get('effort') or payload.get('reasoning_effort') or ''
        state['cwd'] = payload.get('cwd') or state['cwd']
    if payload.get('type') != 'token_count':
        return
    info = payload.get('info') or {}
    window = info.get('model_context_window')
    used = (info.get('last_token_usage') or {}).get('total_tokens')
    if window and used is not None:
        state['context'] = max(0.0, min(100.0, 100.0 * (1 - used / window)))
    limits = payload.get('rate_limits') or {}
    if limits.get('limit_id') not in (None, 'codex'):
        return
    for key in ('primary', 'secondary'):
        item = limits.get(key) or {}
        minutes, used = item.get('window_minutes'), item.get('used_percent')
        if minutes in (300, 10080) and isinstance(used, (int, float)) and math.isfinite(used):
            name = 'five_hour' if minutes == 300 else 'weekly'
            state[name] = max(0.0, min(100.0, 100 - used))
            state[name + '_resets'] = item.get('resets_at')


def read_events(path, state, offset):
    with path.open('rb') as f:
        f.seek(offset)
        # 갱신당 읽기량을 제한하고 전체 로그를 메모리에 올리지 않는다.
        read = 0
        while read < 2 * 1024 * 1024:
            start = f.tell()
            line = f.readline()
            if not line:
                break
            if not line.endswith(b'\n'):
                f.seek(start)
                break
            read += len(line)
            try:
                apply_event(state, json.loads(line))
            except (ValueError, TypeError, KeyError, ZeroDivisionError):
                pass
        return f.tell()


def bar(label, percent, width):
    base = '#[fg=#94a3b8,nobold]'
    if percent is None:
        return base + label + ' ' + '#[fg=#475569]' + '\u2591' * width + base + ' --'
    filled = max(0, min(width, int(percent * width / 100 + 0.5)))
    color = '#34d399' if percent >= 40 else '#fbbf24' if percent >= 15 else '#fb7185'
    return (base + label + ' #[fg=' + color + ']' + '\u2588' * filled +
            '#[fg=#475569]' + '\u2591' * (width - filled) +
            '#[fg=' + color + ']' + '{:3.0f}%'.format(percent))


def render(state, width=100, branch=''):
    sep = '#[fg=#475569,nobold] | '
    cwd = Path(state.get('cwd') or '/')
    project = clean(cwd.name or '/', max(8, min(24, width // 4)))
    model = clean(state.get('model') or 'Codex', 30)
    if model.startswith('gpt-'):
        model = model[4:]
    model = model[:max(5, width - len(project) - 5)]
    effort = clean(state.get('effort') or '', 10)
    row1 = '#[bg=default,fg=#7dd3fc,bold] ' + project + sep + '#[fg=#e2e8f0]' + model
    used_width = 1 + len(project.replace('##', '#')) + 3 + len(model.replace('##', '#'))
    if effort and width >= 60 and used_width + len(effort) + 1 < width:
        row1 += ' #[fg=#94a3b8]' + effort
        used_width += len(effort) + 1
    if branch and width >= 48 and width - used_width >= 8:
        row1 += sep + '#[fg=#c4b5fd]' + clean(branch, width - used_width - 4)
    row1 += '#[default]'
    slots = max(2, min(10, (width - 40) // 3))
    if width < 42:
        slots = 0
    row2 = '#[bg=default] ' + sep.join([
        bar('CTX', state.get('context'), slots),
        bar('5h', state.get('five_hour'), slots),
        bar('7d', state.get('weekly'), slots),
    ]) + '#[default]'
    return row1, row2


def configured_model():
    try:
        text = (Path(os.environ['CODEX_HOME']) / 'config.toml').read_text()
        match = re.search(r'^model\s*=\s*"([^"]+)"', text, re.M)
        return match.group(1) if match else ''
    except (OSError, KeyError):
        return ''


def run(state_dir):
    state_dir = Path(state_dir)
    config = json.loads((state_dir / 'launch.json').read_text())
    args = config['args']
    # 전용 백엔드의 열린 파일에서 해당 창의 세션을 정확히 찾는다.
    command = [REAL, '--no-daemon', '-c', 'tui.status_line=[]'] + args
    state = {'cwd': config['cwd'], 'model': config['model'] or configured_model()}
    old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    child = subprocess.Popen(command, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    def terminate(signum, frame):
        if child.poll() is None:
            child.send_signal(signum)
    old_term = signal.signal(signal.SIGTERM, terminate)
    old_hup = signal.signal(signal.SIGHUP, terminate)
    atomic(state_dir / 'process.json', json.dumps({'pid': child.pid}))
    path, offset, branch, git_tick = None, 0, '', 0
    try:
        while child.poll() is None:
            discovered = find_rollout(child.pid)
            if discovered and discovered != path:
                path, offset = discovered, 0
                state = {'cwd': config['cwd'], 'model': config['model'] or configured_model()}
            if path:
                try:
                    offset = read_events(path, state, offset)
                except OSError:
                    pass
            if time.monotonic() - git_tick > 5:
                try:
                    result = subprocess.run(['git', '-C', state['cwd'], '--no-optional-locks', 'symbolic-ref', '--short', 'HEAD'],
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
                    branch = result.stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    branch = ''
                git_tick = time.monotonic()
            # 만료된 한도는 새 데이터가 수신될 때까지 미확인으로 처리한다.
            now = time.time()
            for key in ('five_hour', 'weekly'):
                if state.get(key + '_resets') and state[key + '_resets'] <= now:
                    state.pop(key, None)
            try:
                width = os.get_terminal_size(0).columns
            except OSError:
                width = 100
            rows = render(state, width, branch)
            for i, row in enumerate(rows):
                atomic(state_dir / ('row' + str(i)), row + '\n')
            atomic(state_dir / 'metrics.json', json.dumps(state))
            time.sleep(1)
        exit_code = child.wait()
        atomic(state_dir / 'exit.json', json.dumps({'code': exit_code}))
        return exit_code
    finally:
        signal.signal(signal.SIGINT, old_handler)
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGHUP, old_hup)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def launch(args):
    if not REAL:
        print('Codex 실행 파일을 찾을 수 없습니다. Codex 설치 후 다시 실행하십시오.', file=sys.stderr)
        return 127
    options = launch_options(args)
    if options is None or os.environ.get('CODEX_PRETTY') == '0' or not (sys.stdin.isatty() and sys.stdout.isatty()) or not Path('/proc/self/fd').exists():
        os.execv(REAL, [REAL] + args)
    try:
        subprocess.run(['tmux', '-V'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.CalledProcessError):
        os.execv(REAL, [REAL] + args)
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir = Path(tempfile.mkdtemp(prefix='session-', dir=str(BASE)))
    atomic(state_dir / 'launch.json', json.dumps({'args': args, 'cwd': options[0], 'model': options[1]}))
    for i, row in enumerate(render({'cwd': options[0], 'model': options[1] or configured_model()})):
        atomic(state_dir / ('row' + str(i)), row + '\n')
    server = 'codex-pretty-{}'.format(os.getpid())
    tmux_config = state_dir / 'tmux.conf'
    command = ' '.join(shlex.quote(x) for x in [sys.executable, APP, '--_run-statusbar', str(state_dir)])
    tmux_config.write_text(
        "set -g default-terminal 'tmux-256color'\n"
        "set -g status 2\n"
        "set -g status-position bottom\n"
        "set -g status-style 'bg=default,fg=#94a3b8'\n"
        "set -g status-interval 1\n"
        "set -g history-limit 50000\n"
        "set -g set-titles off\n"
        "set -g mouse off\n"
        "set -g prefix C-]\n"
        "unbind C-b\n"
        "bind C-] send-prefix\n"
        "set -g status-format[0] '#(cat " + str(state_dir / 'row0') + ")'\n"
        "set -g status-format[1] '#(cat " + str(state_dir / 'row1') + ")'\n",
        encoding='utf-8')
    env = os.environ.copy()
    env.pop('TMUX', None)
    # 별도 소켓·설정으로 기존 tmux 서버를 보존한다.
    status = subprocess.call(['tmux', '-L', server, '-f', str(tmux_config), 'new-session', '-s', 'codex', '-c', os.getcwd(), command], env=env)
    exit_file = state_dir / 'exit.json'
    if exit_file.exists():
        return json.loads(exit_file.read_text())['code']
    return status


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--_run-statusbar':
        return run(sys.argv[2])
    if len(sys.argv) > 1 and sys.argv[1] == '--preview-statusbar':
        state = {'cwd': '/workspace/project', 'model': 'gpt-6.1-sol', 'effort': 'high', 'context': 82, 'five_hour': 64, 'weekly': 37}
        for row in render(state, 100, 'main'):
            print(re.sub(r'#\[[^\]]*\]', '', row))
        return 0
    return launch(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
