#!/usr/bin/env python3
"""임시 홈에서 설정 보존·훅 임계치·반복 실행·설치 복원을 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / 'ai/hooks/session_handoff_guard.py'
MANAGER = ROOT / 'scripts/agent-config.py'


class AgentConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-agents-')
        self.home = Path(self.tmp.name)
        self.env = dict(os.environ, HOME=str(self.home), CODEX_HOME=str(self.home / '.codex'))
        for key in list(self.env):
            if key.startswith('AI_HANDOFF_'):
                del self.env[key]

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, obj):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj))
        return p

    def run_cli(self, path, *args, payload=None, check=True):
        command = ['bash', str(path)] if str(path).endswith('.sh') else ['python3', str(path)]
        return subprocess.run(command + list(args), cwd=str(ROOT), env=self.env,
                              input=json.dumps(payload or {}), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, timeout=30)

    def hook(self, agent, payload, statusline=False):
        args = ['--agent', agent] + (['--statusline'] if statusline else [])
        return self.run_cli(GUARD, *args, payload=payload)

    def test_merge_restore_preserves_user_keys_and_new_hooks(self):
        original = {'model': 'user-choice', 'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'user-hook'}]}]}}
        path = self.write('.claude/settings.json', original)
        path.chmod(0o640)
        self.run_cli(MANAGER, 'apply')
        first = path.read_bytes()
        self.run_cli(MANAGER, 'apply')
        self.assertEqual(first, path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        data = json.loads(path.read_text())
        data['new_user_key'] = True
        extra = {'hooks': [{'type': 'command', 'command': 'new-user-hook'}]}
        data['hooks']['UserPromptSubmit'].append(extra)
        path.write_text(json.dumps(data))
        self.run_cli(MANAGER, 'restore')
        expected = dict(original, new_user_key=True)
        expected['hooks']['UserPromptSubmit'].append(extra)
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertFalse((self.home / '.codex/hooks.json').exists())

    def test_empty_parent_is_preserved_and_invalid_json_stops_before_mutation(self):
        path = self.write('.claude/settings.json', {'hooks': {}})
        self.run_cli(MANAGER, 'apply')
        self.run_cli(MANAGER, 'restore')
        self.assertEqual(json.loads(path.read_text()), {'hooks': {}})
        broken = self.home / '.gemini/config/hooks.json'
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text('{broken')
        before = path.read_bytes()
        self.assertNotEqual(self.run_cli(MANAGER, 'check', check=False).returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.home / '.dotfiles-backup/agent-config.json').exists())

    def test_codex_threshold_and_manual_handoff_are_preserved(self):
        transcript = self.home / 'rollout-session-one.jsonl'
        event = {'payload': {'type': 'token_count', 'info': {'model_context_window': 1000,
                 'last_token_usage': {'total_tokens': 710}}}}
        transcript.write_text(json.dumps(event) + '\n')
        payload = {'session_id': 'session-one', 'cwd': str(self.home), 'transcript_path': str(transcript),
                   'hook_event_name': 'UserPromptSubmit', 'prompt': '작업 계속'}
        out = json.loads(self.hook('codex', payload).stdout)
        self.assertIn('additionalContext', out['hookSpecificOutput'])
        md = self.home / '.config/ai/handoffs/HANDOFF_codex_session-one.md'
        md.write_text(md.read_text() + '\n사용자 검증 결과 보존\n')
        payload['hook_event_name'] = 'Stop'
        self.assertTrue(json.loads(self.hook('codex', payload).stdout)['continue'])
        self.assertIn('사용자 검증 결과 보존', md.read_text())

    def test_session_isolation_and_unknown_usage(self):
        self.hook('agy', {'conversationId': 'one', 'context_window': {'remaining_percentage': 10}}, True)
        result = json.loads(self.hook('agy', {'conversationId': 'two', 'cwd': str(self.home)}).stdout)
        self.assertEqual(result, {})
        self.assertFalse((self.home / '.config/ai/handoffs/HANDOFF_agy_two.md').exists())
        self.hook('codex', {'session_id': 'unknown-usage', 'cwd': str(self.home)})
        self.assertFalse((self.home / '.config/ai/handoffs/HANDOFF_codex_unknown-usage.md').exists())

    def test_foreign_transcript_and_expired_quota_do_not_trigger(self):
        transcript = self.home / 'rollout-other.jsonl'
        quota = {'payload': {'type': 'token_count', 'rate_limits': {
            'primary': {'window_minutes': 300, 'used_percent': 100, 'resets_at': 1}}}}
        transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'other-session'}}) + '\n' +
                              json.dumps({'payload': {'type': 'token_count', 'info': {'model_context_window': 1000,
                              'last_token_usage': {'total_tokens': 990}}}}) + '\n')
        self.hook('codex', {'session_id': 'own-session', 'transcript_path': str(transcript), 'cwd': str(self.home)})
        self.assertFalse((self.home / '.config/ai/handoffs/HANDOFF_codex_own-session.md').exists())
        transcript.write_text(json.dumps(quota) + '\n')
        self.hook('codex', {'session_id': 'expired-session', 'transcript_path': str(transcript), 'cwd': str(self.home)})
        self.assertFalse((self.home / '.config/ai/handoffs/HANDOFF_codex_expired-session.md').exists())

    def test_agy_active_model_quota_and_claude_status_snapshot(self):
        data = {'conversationId': 'agy-one', 'cwd': str(self.home), 'model': {'display_name': 'Gemini'},
                'quota': {'3p-weekly': {'remaining_fraction': 0}, 'gemini-weekly': {'remaining_fraction': 0.8}}}
        self.hook('agy', data)
        path = self.home / '.config/ai/handoffs/HANDOFF_agy_agy-one.md'
        self.assertFalse(path.exists())
        data['quota']['gemini-weekly']['remaining_fraction'] = 0.5
        self.hook('agy', data)
        self.assertTrue(path.exists())
        self.hook('claude', {'session_id': 'claude-one', 'cwd': str(self.home), 'context_window': {'remaining_percentage': 29}}, True)
        out = json.loads(self.hook('claude', {'session_id': 'claude-one', 'cwd': str(self.home), 'hook_event_name': 'UserPromptSubmit'}).stdout)
        self.assertIn('additionalContext', out['hookSpecificOutput'])

    def test_install_twice_and_uninstall_restore_broken_links(self):
        # 패키지·폰트·네트워크를 건드리지 않고 파일 설치 경로를 실제로 실행한다.
        fakebin = self.home / 'fakebin'
        fakebin.mkdir()
        for name, body in {'zsh': 'exit 0', 'starship': 'exit 0', 'sudo': 'exit 1', 'curl': 'exit 97'}.items():
            p = fakebin / name
            p.write_text('#!/bin/sh\n' + body + '\n')
            p.chmod(0o755)
        self.env['PATH'] = str(fakebin) + ':' + self.env['PATH']
        fonts = self.home / '.local/share/fonts'
        fonts.mkdir(parents=True)
        for name in ('JetBrainsMono', 'D2Coding'):
            (fonts / ('.nerd-font-' + name + '-installed')).touch()
        settings = self.write('.claude/settings.json', {'model': 'preserve-model', 'hooks': {}})
        memory = self.home / '.config/ai/MEMORY.md'
        memory.parent.mkdir(parents=True)
        memory.write_text('사용자 기존 메모리\n')
        agent = self.home / '.claude/agents/go-expert.md'
        agent.parent.mkdir()
        agent.symlink_to(self.home / 'missing-original-agent.md')
        self.run_cli(ROOT / 'install.sh')
        self.assertTrue(agent.is_file())
        self.assertFalse(agent.is_symlink())
        self.assertEqual(len(list((self.home / '.codex/agents').glob('*.toml'))), 10)
        first = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file() and '.dotfiles-backup' not in p.parts}
        self.run_cli(ROOT / 'install.sh')
        second = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file() and '.dotfiles-backup' not in p.parts}
        self.assertEqual(first, second)
        self.run_cli(ROOT / 'uninstall.sh')
        self.assertTrue(agent.is_symlink())
        self.assertEqual(os.readlink(str(agent)), str(self.home / 'missing-original-agent.md'))
        self.assertEqual(json.loads(settings.read_text()), {'model': 'preserve-model', 'hooks': {}})
        self.assertEqual(memory.read_text(), '사용자 기존 메모리\n')
        self.assertFalse((self.home / '.local/bin/codex-pretty').exists())
        self.assertFalse((self.home / '.codex/hooks.json').exists())
        self.assertFalse((self.home / '.gemini/config/plugins/dotfiles-agent-adapters/plugin.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
