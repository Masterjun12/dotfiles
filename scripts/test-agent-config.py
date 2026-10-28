#!/usr/bin/env python3
"""임시 홈에서 설정 보존·훅 임계치·반복 실행·설치 복원을 검사한다."""
import json
import importlib.util
import os
from pathlib import Path
import sqlite3
import stat
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
            if key.startswith('AI_HANDOFF_') or key in {'AGENT_HUB_DIR', 'AGENT_HUB_DB', 'AGENT_HUB_CODEX_BACKUP_TAR', 'DOTFILES_EXT_DIR'}:
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
        event['payload']['info']['last_token_usage']['total_tokens'] = 650
        transcript.write_text(json.dumps(event) + '\n')
        out = json.loads(self.hook('codex', payload).stdout)
        self.assertTrue(out['continue'])
        self.assertFalse((self.home / '.config/ai/handoffs/HANDOFF_codex_session-one.md').exists())
        event['payload']['info']['last_token_usage']['total_tokens'] = 710
        transcript.write_text(json.dumps(event) + '\n')
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
        transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'expired-session'}}) + '\n' +
                              json.dumps(quota) + '\n')
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

    def test_codex_wrapper_uses_home_default_and_configured_binary(self):
        real_cli = self.home / 'real-codex'
        real_cli.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "$CODEX_HOME" "$1"\n')
        real_cli.chmod(0o755)
        env = dict(self.env, CODEX_REAL_BIN=str(real_cli))
        env.pop('CODEX_HOME', None)
        result = subprocess.run(['bash', str(ROOT / 'codex/bin/codex'), 'version'], env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True, timeout=10)
        self.assertEqual(result.stdout.splitlines(), [str(self.home / '.codex'), 'version'])

    def test_private_handoff_writes_ignore_predictable_symlink_temp_files(self):
        spec = importlib.util.spec_from_file_location('session_handoff_guard', GUARD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sentinel = self.home / 'must-not-overwrite.txt'
        sentinel.write_text('keep this content\n')
        target = self.home / 'handoffs' / 'snapshot.json'
        target.parent.mkdir()
        module.HANDOFF_DIR = str(target.parent)
        poisoned = Path(str(target) + f'.{os.getpid()}.tmp')
        poisoned.symlink_to(sentinel)

        module.write_private_json(str(target), {'private': True})
        self.assertEqual(sentinel.read_text(), 'keep this content\n')
        self.assertEqual(json.loads(target.read_text()), {'private': True})
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
        module.save_json_safe(str(target), {'state': 'private'})
        self.assertEqual(sentinel.read_text(), 'keep this content\n')
        self.assertEqual(json.loads(target.read_text()), {'state': 'private'})
        shared_dir = self.home / 'shared-dir'
        shared_dir.mkdir(mode=0o755)
        shared_dir.chmod(0o755)
        module.write_private_text(str(shared_dir / 'latest.md'), 'private content\n')
        self.assertEqual(stat.S_IMODE(shared_dir.stat().st_mode), 0o755)

    def test_git_summary_does_not_run_repository_fsmonitor_hook(self):
        spec = importlib.util.spec_from_file_location('session_handoff_guard', GUARD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        repo = self.home / 'untrusted-repo'
        repo.mkdir()
        subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True, timeout=10)
        marker = self.home / 'fsmonitor-ran'
        hook = self.home / 'fsmonitor'
        hook.write_text('#!/bin/sh\ntouch "$MARKER"\nprintf "token\\n"\n')
        hook.chmod(0o755)
        subprocess.run(['git', '-C', str(repo), 'config', 'core.fsmonitor', str(hook)], check=True, timeout=10)
        previous_marker = os.environ.get('MARKER')
        os.environ['MARKER'] = str(marker)
        try:
            module.get_git_summary(str(repo))
        finally:
            if previous_marker is None:
                os.environ.pop('MARKER', None)
            else:
                os.environ['MARKER'] = previous_marker
        self.assertFalse(marker.exists())

    def test_uninstall_purge_rejects_untrusted_manifest_paths(self):
        backup = self.home / '.dotfiles-backup'
        backup.mkdir()
        bin_victim = self.home / 'important' / 'keep-bin'
        bin_victim.parent.mkdir()
        bin_victim.write_text('preserve bin\n')
        (backup / 'bin-installed.txt').write_text(str(bin_victim) + '\n')
        (backup / 'pkg-installed.txt').write_text('--help\n')

        ext_victim = self.home / 'important' / 'keep-repo'
        (ext_victim / '.git').mkdir(parents=True)
        (ext_victim / 'sentinel').write_text('preserve repo\n')
        ext_root = self.home / '.local/share/dotfiles-ext'
        allowed_repo = ext_root / 'attention-span'
        (allowed_repo / '.git').mkdir(parents=True)
        (allowed_repo / 'tracked-file').write_text('remove cloned repo\n')
        (backup / 'ext-cloned.txt').write_text(str(ext_victim) + '\n' + str(allowed_repo) + '\n')

        font_dir = self.home / '.local/share/fonts'
        font_dir.mkdir(parents=True)
        font_victim = self.home / '.config/keep-font-target'
        font_victim.parent.mkdir(parents=True)
        font_victim.write_text('preserve font target\n')
        font_file = font_dir / 'installed-font.ttf'
        font_file.write_text('remove installed font\n')
        (font_dir / '.nerd-font-JetBrainsMono-files.txt').write_text(
            '../../../.config/keep-font-target\ninstalled-font.ttf\n')

        self.run_cli(ROOT / 'uninstall.sh', '--purge')
        self.assertEqual(bin_victim.read_text(), 'preserve bin\n')
        self.assertEqual((ext_victim / 'sentinel').read_text(), 'preserve repo\n')
        self.assertFalse(allowed_repo.exists())
        self.assertEqual(font_victim.read_text(), 'preserve font target\n')
        self.assertFalse(font_file.exists())

    def test_default_agent_hub_uses_private_directory_and_database(self):
        fakebin = self.home / 'fakebin'
        fakebin.mkdir()
        for name in ('zsh', 'starship', 'jq', 'code-server', 'sqlite3', 'git', 'ya'):
            path = fakebin / name
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o755)
        sudo = fakebin / 'sudo'
        sudo.write_text('#!/bin/sh\nexit 1\n')
        sudo.chmod(0o755)
        self.env['PATH'] = str(fakebin) + ':' + self.env['PATH']
        self.env.pop('AGENT_HUB_DIR', None)
        self.env.pop('AGENT_HUB_DB', None)
        fonts = self.home / '.local/share/fonts'
        fonts.mkdir(parents=True)
        for name in ('JetBrainsMono', 'D2Coding'):
            (fonts / ('.nerd-font-' + name + '-installed')).touch()

        self.run_cli(ROOT / 'install.sh')
        hub = self.home / '.config/ai/agent_hub'
        db = hub / 'agent_hub.db'
        self.assertEqual(stat.S_IMODE(hub.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)

    def test_ingest_keeps_database_and_latest_handoff_private(self):
        db = self.home / '.shared/agent_hub/agent_hub.db'
        env = dict(self.env, AGENT_HUB_DB=str(db))
        result = subprocess.run(['python3', str(ROOT / 'ai/agent_hub/scripts/ingest_sessions.py')],
                                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True, timeout=10)
        self.assertIn('All done successfully', result.stdout)
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        module_spec = importlib.util.spec_from_file_location(
            'ingest_sessions', ROOT / 'ai/agent_hub/scripts/ingest_sessions.py')
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        db.parent.chmod(0o755)
        latest = db.parent / 'LATEST_HANDOFF.md'
        latest.write_text('old handoff\n')
        latest.chmod(0o644)
        module.write_private_text(str(latest), 'new private handoff\n')
        self.assertEqual(latest.read_text(), 'new private handoff\n')
        self.assertEqual(stat.S_IMODE(latest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(db.parent.stat().st_mode), 0o755)

    def test_handoff_records_to_configured_agent_hub_database(self):
        hub = self.home / '.shared/agent_hub'
        hub.mkdir(parents=True)
        hub.chmod(0o755)
        db = hub / 'agent_hub.db'
        conn = sqlite3.connect(db)
        conn.executescript((ROOT / 'ai/agent_hub/schema/schema.sql').read_text())
        conn.close()
        self.env['AGENT_HUB_DIR'] = str(hub)
        transcript = self.home / 'rollout-handoff-session.jsonl'
        transcript.write_text(json.dumps({'payload': {'type': 'token_count', 'info': {
            'model_context_window': 1000, 'last_token_usage': {'total_tokens': 710}}}}) + '\n')
        payload = {'session_id': 'handoff-session', 'cwd': str(self.home),
                   'transcript_path': str(transcript), 'hook_event_name': 'UserPromptSubmit'}
        self.hook('codex', payload)
        conn = sqlite3.connect(db)
        row = conn.execute('SELECT source_agent, session_id FROM handoffs').fetchone()
        conn.close()
        self.assertEqual(row, ('codex', 'handoff-session'))
        self.assertTrue((hub / 'LATEST_HANDOFF.md').is_file())

    def test_code_server_standalone_install_skip_and_purge(self):
        fakebin = self.home / 'fakebin'
        fakebin.mkdir()
        scripts = {
            'zsh': 'exit 0', 'starship': 'exit 0', 'jq': 'exit 0', 'sudo': 'exit 1',
            'sqlite3': 'exit 97', 'git': 'exit 97', 'ya': 'exit 97',
        }
        for name, body in scripts.items():
            path = fakebin / name
            path.write_text('#!/bin/sh\n' + body + '\n')
            path.chmod(0o755)
        fake_curl = fakebin / 'curl'
        fake_curl.write_text('''#!/bin/sh
out=""; url=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *code-server.dev/install.sh)
    cat > "$out" <<'INSTALL'
#!/bin/sh
mkdir -p "$HOME/.local/lib/code-server-test/bin" "$HOME/.local/bin"
printf '#!/bin/sh\\nexit 0\\n' > "$HOME/.local/lib/code-server-test/bin/code-server"
chmod +x "$HOME/.local/lib/code-server-test/bin/code-server"
ln -sfn ../lib/code-server-test/bin/code-server "$HOME/.local/bin/code-server"
INSTALL
    ;;
  *) exit 97 ;;
esac
''')
        fake_curl.chmod(0o755)
        self.env['PATH'] = str(fakebin) + ':' + self.env['PATH']
        self.env['AGENT_HUB_DIR'] = str(self.home / '.shared/agent_hub')
        code_config = self.home / '.config/code-server/config.yaml'
        code_config.parent.mkdir(parents=True)
        code_config.write_text('auth: password\npassword: test-only\n')
        code_config.chmod(0o644)
        fonts = self.home / '.local/share/fonts'
        fonts.mkdir(parents=True)
        for name in ('JetBrainsMono', 'D2Coding'):
            (fonts / ('.nerd-font-' + name + '-installed')).touch()
        first = self.run_cli(ROOT / 'install.sh')
        self.assertIn('code-server 설치 완료', first.stdout)
        self.assertEqual(stat.S_IMODE(code_config.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(code_config.stat().st_mode), 0o600)
        server = self.home / '.local/bin/code-server'
        self.assertTrue(server.is_symlink())
        second = self.run_cli(ROOT / 'install.sh')
        self.assertIn('code-server 이미 설치됨', second.stdout)
        self.assertTrue(server.is_symlink())
        outside = self.home / 'important' / 'code-server-keep'
        outside.mkdir(parents=True)
        (outside / 'sentinel').write_text('preserve\n')
        manifest = self.home / '.dotfiles-backup/code-server-installed.txt'
        with manifest.open('a') as f:
            f.write(str(self.home / '.local/lib/code-server-test/../../../important/code-server-keep') + '\n')
        self.run_cli(ROOT / 'uninstall.sh', '--purge')
        self.assertFalse(server.exists())
        self.assertFalse((self.home / '.local/lib/code-server-test').exists())
        self.assertEqual((outside / 'sentinel').read_text(), 'preserve\n')
        self.assertEqual(code_config.read_text(), 'auth: password\npassword: test-only\n')

    def test_install_twice_and_uninstall_restore_broken_links(self):
        # 패키지·폰트·네트워크를 건드리지 않고 파일 설치 경로를 실제로 실행한다.
        fakebin = self.home / 'fakebin'
        fakebin.mkdir()
        for name, body in {'zsh': 'exit 0', 'starship': 'exit 0', 'code-server': 'exit 0', 'sqlite3': 'exit 97',
                           'sudo': 'exit 1', 'curl': 'exit 97', 'git': 'exit 97', 'ya': 'exit 97'}.items():
            p = fakebin / name
            p.write_text('#!/bin/sh\n' + body + '\n')
            p.chmod(0o755)
        self.env['PATH'] = str(fakebin) + ':' + self.env['PATH']
        self.env['AGENT_HUB_DIR'] = str(self.home / '.shared/agent_hub')
        custom_hub = self.home / '.shared/agent_hub'
        custom_hub.mkdir(parents=True)
        custom_hub.chmod(0o755)
        codex_cli = self.home / '.local/bin/codex'
        codex_cli.parent.mkdir(parents=True)
        codex_cli.write_text('#!/bin/sh\nexit 0\n')
        codex_cli.chmod(0o755)
        existing_skills = self.home / '.claude/skills'
        existing_skills.mkdir(parents=True)
        (existing_skills / 'local-skill.md').write_text('사용자 스킬\n')
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
        first_install = self.run_cli(ROOT / 'install.sh')
        self.assertIn('code-server 이미 설치됨', first_install.stdout)
        self.assertIn('기존 ~/.local/bin/codex CLI 유지', first_install.stdout)
        self.assertIn('기존 스킬 디렉터리 유지', first_install.stdout)
        self.assertEqual((existing_skills / 'local-skill.md').read_text(), '사용자 스킬\n')
        db = self.home / '.shared/agent_hub/agent_hub.db'
        self.assertTrue(db.is_file())
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(db.parent.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.home / '.config/ai').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.home / '.config/ai/AGENTS.md').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.home / '.config/ai/MEMORY.md').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.home / '.config/ai/hooks').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.home / '.config/ai/hooks/session_handoff_guard.py').stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.home / '.dotfiles-backup').stat().st_mode), 0o700)
        conn = sqlite3.connect(db)
        self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='handoffs'").fetchone())
        conn.close()
        self.assertTrue(agent.is_file())
        self.assertFalse(agent.is_symlink())
        self.assertEqual(len(list((self.home / '.codex/agents').glob('*.toml'))), 10)
        first = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file() and '.dotfiles-backup' not in p.parts}
        db.chmod(0o644)
        second_install = self.run_cli(ROOT / 'install.sh')
        self.assertIn('code-server 이미 설치됨', second_install.stdout)
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        second = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file() and '.dotfiles-backup' not in p.parts}
        self.assertEqual(first, second)
        self.run_cli(ROOT / 'uninstall.sh')
        self.assertTrue(agent.is_symlink())
        self.assertEqual(os.readlink(str(agent)), str(self.home / 'missing-original-agent.md'))
        self.assertEqual(json.loads(settings.read_text()), {'model': 'preserve-model', 'hooks': {}})
        self.assertEqual(memory.read_text(), '사용자 기존 메모리\n')
        self.assertFalse((self.home / '.local/bin/codex-pretty').exists())
        self.assertEqual(codex_cli.read_text(), '#!/bin/sh\nexit 0\n')
        self.assertFalse((self.home / '.local/bin/agent-hub').exists())
        self.assertFalse((self.home / '.gemini/antigravity-cli/skills').exists())
        self.assertEqual((existing_skills / 'local-skill.md').read_text(), '사용자 스킬\n')
        self.assertFalse((self.home / '.codex/hooks.json').exists())
        self.assertFalse((self.home / '.gemini/config/plugins/dotfiles-agent-adapters/plugin.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
