# 작업 인계

## 목표

Claude 핸즈오프 훅 오류를 고치고, AI 설정 공유와 웹 IDE 설치를 이식성 있게 구성하며 반복 설치 시 기존 사용자 설정을 보존한다.

## 현재 상태

- `ai/hooks/session_handoff_guard.py`는 Claude를 지원하고, Claude/Codex 30%와 AGY 50% 기준을 세션별로 적용한다.
- Agent Hub 기본 경로는 `~/.config/ai/agent_hub`이며 `AGENT_HUB_DIR`·`AGENT_HUB_DB`로 바꿀 수 있다. 기본 전용 디렉터리는 `0700`, DB·메모리 파일은 `0600`이다. 사용자 지정 경로 권한은 설치기가 변경하지 않는다.
- `install.sh`는 macOS·Linux/WSL 패키지 관리자와 code-server 설치를 처리하고, 이미 있는 CLI·스킬 파일은 보존한다.
- code-server 설정 폴더와 비밀번호 파일은 `0700`·`0600`으로 제한하고, 사용자 설정 내용은 보존한다.
- `uninstall.sh`는 임시 파일 경로, Git `core.fsmonitor`, 제거 manifest 경로를 검사해 심볼릭 링크·경로 조작으로 인한 파일 덮어쓰기나 삭제를 막는다.
- Agent Hub는 대화·도구 입력 원문을 암호화하지 않고 저장한다. DB 파일 권한은 사용자 전용이므로 백업도 같은 민감도로 다룬다.

## 검증

- `python3 scripts/test-agent-config.py`: 임시 홈에서 훅 격리, SQLite 저장, 재설치, code-server 설치/제거, 악성 임시 파일·manifest 경로를 검사한다.
- Bash/Zsh 구문, 변경된 Python 모듈 컴파일, `scripts/test-codex-status-line.sh`, `git diff --check`, 공개 저장소 식별자 검사를 실행한다.
- 실제 code-server 다운로드·실행은 하지 않고 설치 흐름을 격리된 가짜 설치기로 확인한다. statusbar 검증은 tmux가 필요하다.
- ShellCheck은 환경에 설치되어 있지 않다.

## 남은 제한

- code-server 설치 스크립트는 공식 HTTPS 출처에서 내려받아 실행하므로 upstream 공급망 신뢰가 필요하다.
- SQLite 기록은 평문이다. 다른 OS 계정과 DB를 공유하지 않고, 백업을 보호한다.
- code-server 실제 기동과 Claude 앱에서의 실 세션 재시작은 별도로 확인하지 않았다.
