# AGENTS.md

이 저장소에서 작업하는 AI 에이전트와 기여자를 위한 안내. 사용자용 설치·사용법은 [README.md](README.md) 에 있고, 여기서는 **무엇을 하는 프로젝트인지, 무엇을 깨면 안 되는지, 어떻게 검증하는지**를 다룬다.

## 프로젝트 개요

새 머신에 셸 환경을 한 번에 맞추는 개인 dotfiles 부트스트랩이다. 셸 설정과 3사 에이전트 설정을 관리한다.

1. **zsh 설정** — macOS 용(`zsh/zshrc.macos`)과 Linux 서버용(`zsh/zshrc.linux`). 같은 섹션 순서를 따르고, 외부 도구는 설치돼 있을 때만 활성화한다.
2. **starship 프롬프트** — `starship/starship.toml`. Catppuccin Mocha 팔레트, 2줄 프롬프트, Nerd Font 글리프. OS 공통.
3. **Claude Code statusline** — `claude/statusline-command.sh` 와, `~/.claude/settings.json` 의 `statusLine` 및 `ui.footer` 키.
4. **Antigravity (agy) statusline** — `agy/statusline-command.sh` 와, `~/.gemini/antigravity-cli/settings.json` 의 `statusLine` 및 `ui.footer` 키.
5. **Codex CLI status line** — `~/.codex/config.toml` 의 `[tui]` `status_line` 키. `codex/status-line.py`가 내장 항목을 관리하고, Linux/WSL의 `codex-pretty`는 tmux 2줄 보조 표시줄을 제공한다.
6. **Global AI Agent Rules & Memory** — `ai/AGENTS.md` (SSOT), `ai/MEMORY.example.md` (~/.config/ai/MEMORY.md 템플릿).
7. **code-server 웹 IDE** — macOS Homebrew 또는 Linux/WSL2 사용자 영역 설치. 없는 경우에만 설치하고 서비스는 자동 시작하지 않는다.

이들을 `install.sh` 가 홈 디렉터리에 배치하고 `uninstall.sh` 가 설치 전 상태로 되돌린다. 프레임워크(oh-my-zsh 등)나 dotfile 매니저(stow, chezmoi)는 쓰지 않는다 — 셸 스크립트 두 개와 복사할 파일들이 전부다. 빌드·패키지·테스트 러너도 없다.

대상 환경: macOS(Apple Silicon/Intel, Homebrew 필수), Linux/WSL2(`dnf`, `apt-get`, `pacman`, `zypper`, `apk`). Git Bash/MSYS/Cygwin 은 지원하지 않고 0 단계에서 중단한다. 웹 IDE standalone 설치는 Linux x86_64/arm64만 지원한다. 셸 스크립트는 bash, 배치되는 설정은 zsh.

## 디렉터리와 파일별 역할

| 경로 | 배치 위치 | 역할 |
|---|---|---|
| `install.sh` | — | 부트스트랩. 의존성 검사 → 패키지 → starship.toml → Nerd Fonts → zshrc → Claude statusline → agy statusline → Codex status line → Global AI rules → Agent Hub → 터미널 파일 뷰어 → Claude 외부 확장 → code-server → chsh 안내 |
| `uninstall.sh` | — | `install.sh` 의 역연산. `--purge`(새로 설치한 패키지까지), `--keep-backup` |
| `starship/starship.toml` | `~/.config/starship.toml` | 프롬프트 정의 |
| `zsh/zshrc.macos` | `~/.zshrc` (Darwin) | brew 기반. `HOMEBREW_PREFIX` 자동 감지 |
| `zsh/zshrc.linux` | `~/.zshrc` (그 외) | 미니멀판. 도구가 없으면 기본 프롬프트·`ls --color`·일반 `cd` 로 폴백 |
| `zsh/zshrc.local.example` | 배치 안 함 | `~/.zshrc.local` 템플릿. 사용자가 직접 복사한다. **placeholder 만** 담는다 |
| `claude/statusline-command.sh` | `~/.claude/statusline-command.sh` | Claude Code statusLine JSON(stdin) → 두 줄 출력. `jq` 필요 |
| `agy/statusline-command.sh` | `~/.gemini/antigravity-cli/statusline-command.sh` | Antigravity CLI statusline JSON(stdin) → 두 줄 출력. `jq` 필요 |
| `codex/status-line.py` | 배치 안 함 | `check`/`apply`/`restore`. `~/.codex/config.toml` 의 `[tui]` `status_line` 키만 편집. |
| `ai/AGENTS.md` | `~/.config/ai/AGENTS.md` | 에이전트 공통 응답 규칙, DB 책임, 출력 절제 SSOT (~/.claude, ~/.gemini, ~/.codex 심볼릭 링크) |
| `ai/MEMORY.example.md` | `~/.config/ai/MEMORY.md` | 머신별 서버/환경 메모리 템플릿 (미추적) |
| `ai/agent_hub/` | 기본 `~/.config/ai/agent_hub/`, `AGENT_HUB_DIR`로 변경 가능 | 3사 공용 세션/핸즈오프 SQLite 스키마 및 agent-hub CLI |
| `codex/bin/codex` | `~/.local/bin/codex` | 기존 CLI가 없을 때만 설치하는 Codex 실행 래퍼. `CODEX_REAL_BIN` 또는 PATH에서 원본을 찾고 `CODEX_HOME`은 `~/.codex`를 기본값으로 사용 |
| `viewer/fview` | `~/.local/bin/fview` | 확장자별 미리보기 변환기. 도구가 없으면 원문으로 폴백. bash 3.2(macOS)에서도 동작 |
| `viewer/yazi.toml`, `viewer/keymap.toml` | `~/.config/yazi/` | yazi 미리보기·열기를 `fview` 에 연결, 미리보기 스크롤 키 |
| `claude/extensions.txt` | 배치 안 함 | 7.3 단계가 읽는 외부 확장 목록. install·uninstall 이 같은 목록을 쓴다. 외부 본문은 복제하지 않는다 |
| `scripts/test-codex-status-line.sh` | — | 위 스크립트의 임시 `HOME` 왕복 시험 |
| `scripts/test-windows-paths.sh` | — | Git Bash 거부(어느 OS 에서나)와 WSL 폰트 건너뛰기(Linux 에서만) 시험 |
| `.gitignore` | — | 머신별·시크릿 파일명 차단 |

홈에 생기는 부산물: `~/.dotfiles-backup/`(원본 기록과 설치 manifest), 배치 대상 옆의 `*.bak`(1세대), 폰트 디렉터리의 `.nerd-font-<name>-installed` 마커와 `.nerd-font-<name>-files.txt` manifest.

## 추적 범위 — 가장 중요한 규칙

이 저장소는 공개 저장소다. **어느 머신에나 그대로 적용 가능한 것만 커밋한다.**

커밋하지 않는 것:

- 실제 호스트명, IP(공인·사설 모두), SSH 포트, 내부 도메인·URL, 클러스터·네임스페이스·시크릿 이름
- API 키·토큰·비밀번호, 그리고 그것을 조회하는 구체적인 절차
- 개인 에이전트 지침, 인증값·서버별 MCP·신뢰 경로·승인 캐시가 포함된 실제 설정 전체
- 특정 머신 목록이나 "어느 서버에 적용했는지" 같은 운영 현황
- 절대 경로에 박힌 사용자명(`/Users/<name>/...`) — `$HOME` 을 쓴다

대신 두는 곳:

- 머신별 alias/함수 → `~/.zshrc.local` (두 zshrc 가 플러그인 직전에 `source`)
- 시크릿 → `~/.secrets.zsh` (mode 600, zshrc 는 `source` 만 한다)

`zshrc.local.example`, README, 주석에 예시가 필요하면 `<host>`, `<container>` 같은 placeholder 를 쓴다. 홈 파일을 저장소로 가져와 동기화할 때가 제일 새기 쉬운 지점이다 — 커밋 전에 `git diff --cached` 를 직접 읽고 아래 검증 절의 식별자 검사를 돌린다.

## 불변 규칙 (스크립트를 고칠 때)

- **멱등**: `install.sh`·`uninstall.sh` 는 몇 번을 재실행해도 결과가 같아야 한다. 패키지는 없을 때만 설치하고, 파일은 내용이 다를 때만 덮어쓴다.
- **개인 데이터 권한**: 설치 스크립트는 `umask 077`을 쓰며 기본 `~/.config/ai`, Agent Hub, 핸즈오프, 설치 백업은 사용자만 접근할 수 있게 유지한다. Agent Hub DB와 메모리 파일은 `0600`, 전용 디렉터리는 `0700`으로 둔다. `AGENT_HUB_DIR` 사용자 지정 경로는 다른 공용 디렉터리 권한을 바꾸지 않고 DB 파일만 `0600`으로 제한한다.
- code-server 기본 설정 폴더와 `config.yaml`은 각각 `0700`·`0600`으로 제한한다. 심볼릭 링크로 연결된 사용자 설정 경로는 chmod 대상에서 제외한다.
- **실패는 변경 전에**: 의존성 검사(0 단계)에서 실패하면 `~/.dotfiles-backup` 을 포함해 홈에 아무것도 만들지 않는다. 새 전제 조건은 0 단계에 추가한다.
- **기존 설치 건너뛰기**: 명령·패키지·플러그인 파일·폰트 마커·code-server 경로를 확인한 뒤 없는 항목만 설치한다. Agent Hub DB는 Python 표준 SQLite로 새로 만들고 기존 DB는 보존한다.
- **덮어쓰기 전 백업**: 홈 파일 배치는 반드시 `deploy_file` 을 거친다(최초 원본을 `.orig`/`.absent` 로 기록 → 내용이 다르면 `.bak` → 복사). `cp` 직접 호출 금지. 최초 기록은 재실행 때 갱신하지 않는다.
- **`settings.json` 은 키 단위 merge**: 상태줄·이 저장소의 훅·AGY 어댑터 활성화 키만 병합한다. 그 밖의 설정값은 `settings/` 템플릿으로 제공하며 기존 권한·모델은 바꾸지 않는다. 쓰기는 같은 디렉터리의 임시 파일 + `os.replace` 로 원자적으로, 기존 mode 를 보존한다. 깨진 JSON 이면 손대지 않고 중단한다.
- **`config.toml` 도 키 단위 merge**: `[tui]` 의 `status_line` 외에는 읽거나 바꾸지 않는다. TOML writer 가 없으므로 그 키의 줄만 교체하고 나머지는 바이트 그대로 둔다. `tomllib` 이 있으면 쓰기 전에 "`status_line` 외에는 같다"를 검증하고, 깨진 TOML·미지원 표기면 손대지 않고 중단한다. `install.sh` 와 `uninstall.sh` 가 같은 파서를 쓰도록 로직은 `codex/status-line.py` 한 곳에만 둔다. 3사 설정·역할 어댑터를 첫 실행에 함께 준비하며 CLI 자체는 설치하지 않는다.
- **WSL 에서는 `$HOME` 밖을 건드리지 않는다**: WSL 은 `/proc/version` 의 `microsoft` 로 감지하고(`is_wsl`), Nerd Font 단계를 건너뛰고 안내만 한다. Windows 사용자 프로필에 폰트를 설치하는 식의 자동화는 넣지 않는다 — 역연산과 임시 `HOME` 왕복 시험이 성립하지 않는다. `DOTFILES_PROC_VERSION` 은 감지에 쓸 파일을 바꾸는 시험용 변수다.
- **설치한 것만 지운다**: `--purge` 는 manifest(`brew-installed.txt`·`pkg-installed.txt`·`bin-installed.txt`)에 기록된 것만, 폰트는 파일 manifest 에 적힌 것만 제거한다. 원래 있던 것을 지우지 않는다.
- **사용자 파일은 건드리지 않는다**: `~/.zshrc.local`, `~/.secrets.zsh`, `~/.claude/CLAUDE.md` 는 만들지도 지우지도 않는다.
- **install 과 uninstall 은 한 쌍**: `install.sh` 가 홈에 뭔가를 새로 만들면 같은 변경에서 `uninstall.sh` 에 역연산을 넣는다.
- **번호 동기화**: `install.sh` 의 섹션 번호, 헤더 주석의 동작 목록, README 의 단계 표는 항상 같은 번호를 쓴다. 단계를 바꾸면 세 곳을 같이 고친다.
- **zshrc 구조**: 두 zshrc 는 같은 섹션 순서(환경·PATH → 히스토리·옵션 → 자동완성 → 툴 초기화 → alias → 시크릿 → 머신별 → 플러그인)를 지킨다. 도구·디렉터리는 존재할 때만 활성화하고 없으면 조용히 건너뛴다. `zsh-syntax-highlighting` 은 맨 마지막에 source 한다. PATH 는 `typeset -U path` 로 중복을 막는다.
- **`trap ... RETURN` 금지**: bash 에서 함수 밖으로 새어 이후 모든 함수 리턴에 발화한다. 임시 디렉터리 정리는 단일 지점에서 한다.
- **프롬프트 심볼은 Nerd Font 글리프**: 이모지를 쓰지 않는다. `starship.toml` 은 starship 1.22(Linux 배포판 버전)에서도 동작해야 한다.

## 검증

테스트 스위트가 없으므로 아래를 직접 돌린다.

```bash
# 문법
bash -n install.sh uninstall.sh claude/statusline-command.sh scripts/test-codex-status-line.sh scripts/test-windows-paths.sh
python3 -m py_compile codex/status-line.py
zsh -n zsh/zshrc.macos zsh/zshrc.linux zsh/zshrc.local.example

# 실제 홈에 영향 없이 설치/제거 왕복 (패키지는 이미 설치된 머신 기준)
T="$(mktemp -d)"
# CODEX_HOME 이 설정된 머신에서는 임시 HOME 이어도 실제 Codex 폴더를 바꾸므로 반드시 뺀다
env -u CODEX_HOME HOME="$T" ./install.sh && env -u CODEX_HOME HOME="$T" ./install.sh      # 두 번째 실행에서 변경이 없어야 한다
env -u CODEX_HOME HOME="$T" ./uninstall.sh && find "$T" -type f -not -path '*/Library/Caches/*'   # 남는 파일이 없어야 한다 (macOS 는 brew 캐시가 임시 홈에 생긴다)

# statusline
echo '{"workspace":{"current_dir":"/tmp"},"model":{"display_name":"test"}}' | bash claude/statusline-command.sh

# Codex status line — 임시 HOME 에서 apply 2회 → restore 후 원본과 바이트 비교, 깨진 TOML·미지원 표기 거부
scripts/test-codex-status-line.sh

# Windows 경로 — Git Bash 거부는 어느 OS 에서나, WSL 흉내 왕복은 Linux 에서만 돈다 (macOS 에서는 컨테이너로)
scripts/test-windows-paths.sh
podman run --rm -v "$PWD":/src:ro docker.io/library/ubuntu:24.04 bash -c \
  'apt-get update -qq && apt-get install -y -qq sudo curl unzip python3 ca-certificates >/dev/null && cp -r /src /work && cd /work && scripts/test-windows-paths.sh'

# 공개 전 식별자 검사 — 결과가 없어야 한다
git grep -nIE '([0-9]{1,3}\.){3}[0-9]{1,3}|/Users/[a-z0-9]+|/home/[a-z0-9]+|glpat-|ghp_|BEGIN [A-Z ]*PRIVATE KEY' -- ':!AGENTS.md'
```

`HOME` 을 바꾼 왕복 시험은 Nerd Font 를 실제로 내려받는다(수십 MB). 폰트와 무관한 변경이면 임시 홈의 폰트 디렉터리에 `.nerd-font-JetBrainsMono-installed`, `.nerd-font-D2Coding-installed` 마커를 미리 만들어 건너뛸 수 있다.

## 작업 흐름

- Issues 기능이 켜져 있으면 이슈를 먼저 등록하고 번호를 브랜치·커밋에 넣는다: `feat/issue-<n>-<slug>`, 커밋 제목 `feat(#<n>): ...` (`feat`/`fix`/`docs`/`chore`).
- 기본 브랜치는 `main`. 직접 커밋하지 않고 브랜치 → PR 로 올린다.
- 동작을 바꾸면 README 의 해당 절과 스크립트 헤더 주석을 같은 커밋에서 갱신한다.
- 커밋 메시지·문서·주석은 한국어, 표준 문어체.

## 3사 설정 확장

- `ai/hooks/session_handoff_guard.py`: AGY 50%, Claude·Codex 30% 기준의 세션별 실제 수치·핸즈오프. 추정 사용량과 다른 세션의 최신 로그를 사용하지 않는다.
- `scripts/agent-config.py`: 훅·플러그인 키 병합/복원 기록, 개인 설정 보존.
- `ai/agents/`: 10개 역할의 Claude·Codex·AGY 어댑터. 업무 절차 SSOT인 외부 스킬 본문은 복제하지 않는다.
- `settings/`: 3사 설정의 공개 가능한 템플릿. 인증·서버·훅 승인 상태를 포함하지 않는다.
- 추가 검증: `python3 scripts/test-agent-config.py`, `python3 scripts/test-statusbar.py`.
