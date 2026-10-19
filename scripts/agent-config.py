#!/usr/bin/env python3
"""3사 훅과 AGY 어댑터 등록만 병합하고 해당 항목만 복원한다."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

HOME = Path.home()
BACKUP = HOME / '.dotfiles-backup/agent-config.json'
CODEX = Path(os.environ.get('CODEX_HOME', str(HOME / '.codex')))


def load(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(str(path) + ': JSON 객체가 필요하다')
    return data


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix='.agent-config-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.chmod(temp, mode)
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def command(agent):
    return 'python3 "$HOME/.config/ai/hooks/session_handoff_guard.py" --agent ' + agent


def plans():
    result = []
    for path, agent in [(HOME / '.claude/settings.json', 'claude'), (CODEX / 'hooks.json', 'codex')]:
        for event in ('UserPromptSubmit', 'Stop'):
            item = {'hooks': [{'type': 'command', 'command': command(agent), 'timeout': 10}]}
            result.append((path, ['hooks', event], item, 'append'))
    agy = {'enabled': True}
    for event in ('PreInvocation', 'Stop'):
        agy[event] = [{'type': 'command', 'command': command('agy'), 'timeout': 10}]
    result.append((HOME / '.gemini/config/hooks.json', ['session-handoff-guard-agy'], agy, 'set'))
    result.append((HOME / '.gemini/config/config.json', ['plugins', 'dotfiles-agent-adapters', 'enabled'], True, 'set'))
    return result


def parent(data, keys, create=False):
    for key in keys[:-1]:
        if key not in data:
            if not create:
                return None
            data[key] = {}
        data = data[key]
        if not isinstance(data, dict):
            raise ValueError('설정 부모 키는 객체여야 한다: ' + '.'.join(keys))
    return data


def check():
    load(BACKUP)
    documents = {}
    for path, keys, value, mode in plans():
        data = documents.setdefault(str(path), load(path))
        node = parent(data, keys)
        if node is not None and keys[-1] in node:
            current = node[keys[-1]]
            if mode == 'append' and not isinstance(current, list):
                raise ValueError(str(path) + ': hooks 이벤트는 배열이어야 한다')
    return documents


def apply():
    docs = check()
    saved = load(BACKUP)
    for path, keys, value, mode in plans():
        path_key = str(path)
        record = saved.setdefault(path_key, {'existed': path.exists(), 'changes': []})
        data = docs[path_key]
        existing = data
        created_parents = []
        for depth, key in enumerate(keys[:-1], 1):
            if key not in existing:
                created_parents.append(keys[:depth])
                existing = {}
            else:
                existing = existing[key]
        node = parent(data, keys, True)
        exists = keys[-1] in node
        old = copy.deepcopy(node.get(keys[-1]))
        if mode == 'append':
            items = node.setdefault(keys[-1], [])
            expected = os.path.expandvars(value['hooks'][0]['command'].replace('"', ''))
            equivalent = any(os.path.expandvars(h.get('command', '').replace('"', '')) == expected
                             for group in items if isinstance(group, dict)
                             for h in group.get('hooks', []) if isinstance(h, dict))
            if value in items or equivalent:
                continue
            items.append(value)
        else:
            if old == value:
                continue
            node[keys[-1]] = value
        if not any(c['keys'] == keys for c in record['changes']):
            record['changes'].append({'keys': keys, 'old_exists': exists, 'old': old, 'managed': value,
                                      'mode': mode, 'created_parents': created_parents})
    # 복원 기록을 먼저 남긴 뒤 실제 설정을 원자적으로 바꾼다.
    write(BACKUP, saved)
    for name, data in docs.items():
        path = Path(name)
        if data != load(path):
            write(path, data)


def restore():
    saved = load(BACKUP)
    # 깨진 JSON이면 다른 파일을 변경하기 전에 중단한다.
    docs = {name: load(Path(name)) for name in saved}
    for name, record in saved.items():
        data = docs[name]
        for change in reversed(record['changes']):
            keys = change['keys']
            node = parent(data, keys)
            if node is None or keys[-1] not in node:
                continue
            current = node[keys[-1]]
            if change['mode'] == 'append':
                if not isinstance(current, list):
                    continue
                current[:] = [x for x in current if x != change['managed']]
                if not current and not change['old_exists']:
                    del node[keys[-1]]
            elif current == change['managed']:
                if change['old_exists']:
                    node[keys[-1]] = change['old']
                else:
                    del node[keys[-1]]
            for created in reversed(change.get('created_parents', [])):
                owner = parent(data, created)
                if owner is not None and owner.get(created[-1]) == {}:
                    del owner[created[-1]]
        path = Path(name)
        if not data and not record['existed']:
            if path.exists():
                path.unlink()
        elif data != load(path):
            write(path, data)
    if BACKUP.exists():
        BACKUP.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'apply', 'restore'])
    args = parser.parse_args()
    {'check': check, 'apply': apply, 'restore': restore}[args.action]()


if __name__ == '__main__':
    main()
