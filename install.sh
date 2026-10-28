#!/usr/bin/env bash
# dotfiles install — zsh + starship 표준 셸 환경 부트스트랩
#
# 사용법:
#   git clone https://github.com/wooring12/dotfiles.git && cd dotfiles && ./install.sh
#
# 동작 (섹션 번호 = 아래 주석 번호 = README 단계 표):
#   0.   의존성 사전 검사 — 누락 시 홈 파일을 하나도 바꾸지 않고 종료. Git Bash/MSYS/Cygwin 은 지원하지 않음(WSL2 에서 실행)
#   1.   zsh / starship / 플러그인 / jq 설치 (없을 때만; macOS 는 eza·bat·zoxide 포함)
#   2.   starship.toml 배치 (~/.config/starship.toml)
#   2.5. Nerd Fonts 설치 (JetBrainsMono, D2Coding; 마커 파일로 재설치 방지)
#        WSL 에서는 건너뛰고 안내만 — 글리프는 Windows 쪽 터미널이 그리므로 폰트도 Windows 에 설치해야 한다
#   3.   OS 에 맞는 zshrc 배치 (~/.zshrc). 머신별 alias/함수는 ~/.zshrc.local (미추적, 이 스크립트가 만들지 않음)
#   4.   Claude Code statusline 스크립트 배치 (~/.claude/statusline-command.sh)
#        + settings.json 의 statusLine 및 ui.footer 키 merge (python3, 원자적 쓰기)
#   5.   Antigravity (agy) statusline 스크립트 배치 (~/.gemini/antigravity-cli/statusline-command.sh)
#        + settings.json 의 statusLine 및 ui.footer 키 merge
#   6.   Codex CLI status line — ~/.codex/config.toml 의 [tui] status_line 키만 merge (codex/status-line.py)
#        CLI 설치 여부와 무관하게 3사 설정·어댑터를 첫 실행에 함께 준비한다.
#   7.   Global AI Agent Rules & SSOT Memory + 3사 훅·에이전트·설정 템플릿
#        - ~/.config/ai/AGENTS.md 배치 및 ~/.config/ai/MEMORY.md 초기화
#        - ~/.claude/CLAUDE.md, ~/.gemini/AGENTS.md, ~/.codex/AGENTS.md 심볼릭 링크 연결
#        - Codex 2줄 보조 표시줄(codex-pretty), 10개 역할의 런타임 어댑터, 핸즈오프 훅
#   7.1. 3사 Agent Hub와 스킬 저장소 — 중앙 SQLite 및 통합 스킬 경로
#   7.2. 터미널 파일 뷰어 — yazi·glow·chafa (없을 때만), ~/.local/bin/fview, ~/.config/yazi/{yazi,keymap}.toml, piper 플러그인
#   7.3. Claude Code 외부 확장 — claude/extensions.txt 의 저장소를 DOTFILES_EXT_DIR 에 클론하고
#        ~/.claude/{output-styles,commands,skills} 아래에 심볼릭 링크
#   7.4. 웹 IDE — code-server 를 macOS Homebrew 또는 Linux/WSL 사용자 영역에 설치 (기존 설치는 건너뜀)
#   8.   기본 셸이 zsh 가 아니면 chsh 안내
#
# 런타임 의존성: curl, unzip, python3, tar (0 단계에서 검사). macOS 는 Homebrew 필수. Windows 는 WSL2 안에서 실행.
#   jq 는 statusline 스크립트 런타임 전용 — 1 단계에서 brew/Linux 패키지 관리자로 설치 (권한이 없으면 경고만).
# 멱등(idempotent): 재실행해도 안전하다. 배치 대상은 내용이 다를 때만 .bak 백업 후 덮어쓴다.
#
# 되돌리기: ./uninstall.sh — 최초 실행 시 ~/.dotfiles-backup/ 에 보관한 원본과 manifest 를 기준으로 복원한다.
#   - <name>.orig     : 덮어쓰기 전 원본 (최초 1회만 기록, 이후 실행은 갱신하지 않음)
#   - <name>.absent   : 원래 그 파일이 없었다는 표시
#   - brew-installed.txt / pkg-installed.txt / bin-installed.txt : 이 스크립트가 새로 설치한 것만 기록
#   - ext-cloned.txt : 7.3 단계가 새로 클론한 확장 저장소 (--purge 때만 삭제)
#   - code-server-installed.txt : 7.4 단계가 새로 설치한 사용자 영역 버전 디렉터리
#   - yazi-piper.installed : 7.2 단계가 piper 플러그인을 설치했다는 표시
#   - settings.json.orig : settings.json 설치 전 전체 내용 (없었으면 settings.json.absent)
#   - gemini-settings.json.orig : ~/.gemini/antigravity-cli/settings.json 설치 전 전체 내용
#   - codex-config.toml.orig : ~/.codex/config.toml 설치 전 전체 내용 (없었으면 codex-config.toml.absent)

set -euo pipefail
umask 077
cd "$(dirname "$0")"

OS="$(uname -s)"
info() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[install] 오류:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. 의존성 사전 검사 (홈 파일 변경 전) ────────────────────
# 여기서 실패하면 ~/.dotfiles-backup 을 포함해 아무것도 만들거나 바꾸지 않는다.
case "$OS" in
  MINGW*|MSYS*|CYGWIN*)
    die "Git Bash/MSYS/Cygwin 은 지원하지 않음 (zsh·패키지 매니저 없음) — WSL2 를 설치(wsl --install)하고 그 안에서 실행 (홈 파일은 변경하지 않았음)" ;;
esac
case "$OS" in
  Darwin|Linux) ;;
  *) die "지원 OS는 macOS와 Linux/WSL2 — 현재: $OS (홈 파일은 변경하지 않았음)" ;;
esac
missing=()
for cmd in curl unzip python3 tar; do command -v "$cmd" >/dev/null || missing+=("$cmd"); done
if [ "$OS" = "Darwin" ]; then
  command -v brew >/dev/null || missing+=("brew (https://brew.sh)")
else
  if command -v dnf >/dev/null; then PKG_MANAGER=dnf
  elif command -v apt-get >/dev/null; then PKG_MANAGER=apt
  elif command -v pacman >/dev/null; then PKG_MANAGER=pacman
  elif command -v zypper >/dev/null; then PKG_MANAGER=zypper
  elif command -v apk >/dev/null; then PKG_MANAGER=apk
  else missing+=("dnf, apt-get, pacman, zypper 또는 apk"); fi
fi
if [ "${#missing[@]}" -gt 0 ]; then
  die "필수 명령 누락: ${missing[*]} — 설치 후 다시 실행 (홈 파일은 변경하지 않았음)"
fi
# settings.json 이 있는데 깨진 JSON 이면 4, 5 단계에서 손댈 수 없으므로 시작 전에 막는다
if [ -f "$HOME/.claude/settings.json" ]; then
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$HOME/.claude/settings.json" 2>/dev/null \
    || die "$HOME/.claude/settings.json 이 올바른 JSON 이 아님 — 수동으로 고친 뒤 다시 실행 (홈 파일은 변경하지 않았음)"
fi
if [ -f "$HOME/.gemini/antigravity-cli/settings.json" ]; then
  python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$HOME/.gemini/antigravity-cli/settings.json" 2>/dev/null \
    || die "$HOME/.gemini/antigravity-cli/settings.json 이 올바른 JSON 이 아님 — 수동으로 고친 뒤 다시 실행 (홈 파일은 변경하지 않았음)"
fi
# ~/.codex/config.toml 이 깨진 TOML 이거나 [tui] 표기가 아니면 6 단계에서 손댈 수 없으므로 시작 전에 막는다
if [ -f "$HOME/.codex/config.toml" ] || { [ -n "${CODEX_HOME:-}" ] && [ -f "$CODEX_HOME/config.toml" ]; }; then
  python3 codex/status-line.py check || die "codex config.toml 을 편집할 수 없음 — 수동으로 고친 뒤 다시 실행 (홈 파일은 변경하지 않았음)"
fi

python3 scripts/agent-config.py check || die "에이전트 훅 JSON을 병합할 수 없음 — 홈 파일 변경 전 중단"

# WSL 여부 — 커널 버전 문자열에 microsoft 가 들어 있다. DOTFILES_PROC_VERSION 은 시험용(다른 파일을 읽게 한다)
is_wsl() {
  local f="${DOTFILES_PROC_VERSION:-/proc/version}"
  [ "$OS" != "Darwin" ] && [ -r "$f" ] && grep -qi microsoft "$f"
}

BACKUP_DIR="$HOME/.dotfiles-backup"
mkdir -p "$BACKUP_DIR"
if [ ! -L "$BACKUP_DIR" ]; then chmod 700 "$BACKUP_DIR"; fi
mkdir -p "$HOME/.config/ai"
if [ ! -L "$HOME/.config/ai" ]; then chmod 700 "$HOME/.config/ai"; fi

# 최초 실행 시에만 원본 상태를 기록 (있으면 .orig 로 복사, 없으면 .absent 마커)
preserve_original() {   # preserve_original <대상 경로> <기록 이름>
  local target="$1" name="$2"
  [ -e "$BACKUP_DIR/$name.orig" ] || [ -L "$BACKUP_DIR/$name.orig" ] || [ -e "$BACKUP_DIR/$name.absent" ] && return 0
  if [ -e "$target" ] || [ -L "$target" ]; then cp -P "$target" "$BACKUP_DIR/$name.orig"; else touch "$BACKUP_DIR/$name.absent"; fi
}

# 파일 배치: 원본 기록 → 내용 다르면 .bak 1세대 백업 → 복사
deploy_file() {         # deploy_file <원본(레포)> <대상(홈)> <기록 이름>
  local src="$1" dst="$2" name="$3"
  mkdir -p "$(dirname "$dst")"
  preserve_original "$dst" "$name"
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
    rm -f "$dst.bak"
    cp -P "$dst" "$dst.bak"
    info "기존 $(basename "$dst") → .bak 백업"
  fi
  # 원본 스킬을 가리키는 링크의 대상을 덮어쓰지 않는다(깨진 링크도 처리).
  if [ -L "$dst" ]; then rm -f "$dst"; fi
  cp "$src" "$dst"
}

# 심볼릭 링크 배치: 원본 기록 → 다르면 .bak 1세대 백업 → 심볼릭 링크 생성
deploy_symlink() {      # deploy_symlink <대상 심볼릭 타겟> <생성할 심볼릭 링크 경로> <기록 이름>
  local target="$1" link="$2" name="$3"
  mkdir -p "$(dirname "$link")"
  preserve_original "$link" "$name"
  if [ -L "$link" ] || [ -e "$link" ]; then
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
      return 0
    fi
    cp -P "$link" "$link.bak" 2>/dev/null || true
    rm -f "$link"
  fi
  ln -s "$target" "$link"
  info "심볼릭 링크 배치: $link → $target"
}

# manifest 에 한 줄 추가 (중복 없이)
record() {              # record <manifest 파일명> <값>
  grep -qxF -- "$2" "$BACKUP_DIR/$1" 2>/dev/null || printf '%s\n' "$2" >> "$BACKUP_DIR/$1"
}

# ── 1. 패키지 설치 ──────────────────────────────────────────
run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else return 127; fi
}
can_install_system_packages() {
  [ "$(id -u)" -eq 0 ] || { command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; }
}
plugin_files_exist() {
  case "$1" in
    zsh-autosuggestions)
      [ -f /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh ] \
        || [ -f /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh ] ;;
    zsh-syntax-highlighting)
      [ -f /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ] \
        || [ -f /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ] ;;
    *) return 1 ;;
  esac
}
install_system_packages() {
  case "$PKG_MANAGER" in
    dnf) run_privileged dnf install -y "$@" ;;
    apt) run_privileged apt-get install -y "$@" ;;
    pacman) run_privileged pacman -S --needed --noconfirm "$@" ;;
    zypper) run_privileged zypper --non-interactive install "$@" ;;
    apk) run_privileged apk add "$@" ;;
  esac
}
package_is_installed() {
  case "$PKG_MANAGER" in
    dnf) rpm -q "$1" >/dev/null 2>&1 ;;
    apt) dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed' ;;
    pacman) pacman -Q "$1" >/dev/null 2>&1 ;;
    zypper) rpm -q "$1" >/dev/null 2>&1 ;;
    apk) apk info -e "$1" >/dev/null 2>&1 ;;
  esac
}
if [ "$OS" = "Darwin" ]; then
  for pkg in starship eza bat zoxide fzf fd jq zsh-autosuggestions zsh-syntax-highlighting; do
    brew list "$pkg" >/dev/null 2>&1 || { info "brew install $pkg"; brew install "$pkg"; record brew-installed.txt "$pkg"; }
  done
else
  # Linux 배포판 계열별 패키지 관리자: Fedora/RHEL, Debian/Ubuntu, Arch, openSUSE, Alpine.
  command -v zsh >/dev/null || {
    info "zsh 설치"
    install_system_packages zsh || die "zsh 설치 실패 — 패키지 관리자 권한·저장소를 확인한 뒤 다시 실행"
    record pkg-installed.txt zsh
  }
  command -v starship >/dev/null || {
    info "starship 설치 (공식 스크립트 → /usr/local/bin, sudo 불가 시 ~/.local/bin)"
    if sudo -n true 2>/dev/null; then
      curl -sS https://starship.rs/install.sh | sh -s -- -y
      record bin-installed.txt /usr/local/bin/starship
    else
      mkdir -p "$HOME/.local/bin"
      curl -sS https://starship.rs/install.sh | sh -s -- -y -b "$HOME/.local/bin"
      record bin-installed.txt "$HOME/.local/bin/starship"
    fi
  }
  plugins_missing=()
  for pkg in zsh-autosuggestions zsh-syntax-highlighting; do
    if ! plugin_files_exist "$pkg" && ! package_is_installed "$pkg"; then plugins_missing+=("$pkg"); fi
  done
  if [ "${#plugins_missing[@]}" -gt 0 ]; then
    if can_install_system_packages; then
      if [ "$PKG_MANAGER" = dnf ] && ! rpm -q epel-release >/dev/null 2>&1; then
        if run_privileged dnf install -y epel-release >/dev/null 2>&1; then record pkg-installed.txt epel-release; fi
      fi
      info "zsh 자동완성 플러그인 설치"
      if install_system_packages "${plugins_missing[@]}"; then
        for pkg in "${plugins_missing[@]}"; do record pkg-installed.txt "$pkg"; done
      else
        info "경고: zsh 자동완성 플러그인 설치 실패 — 저장소·권한을 확인"
      fi
    else
      info "경고: zsh 자동완성 플러그인 설치 건너뜀 — 관리자 권한이 필요"
    fi
  fi
  # jq — statusline 런타임 전용. 기본 셸은 jq 없이도 동작한다.
  if ! command -v jq >/dev/null; then
    if can_install_system_packages; then
      info "jq 설치"
      if install_system_packages jq; then record pkg-installed.txt jq
      else info "경고: jq 설치 실패 — Claude/AGY statusline은 jq 설치 전까지 제한"; fi
    else
      info "경고: jq 설치 건너뜀 — 관리자 권한이 없어 statusline에서 jq를 사용할 수 없음"
    fi
  fi
fi

# ── 2. starship.toml ───────────────────────────────────────
deploy_file starship/starship.toml "$HOME/.config/starship.toml" starship.toml
info "starship.toml 배치 완료"

# ── 2.5. Nerd Fonts (JetBrainsMono, D2Coding) ──────────────
if [ "$OS" = "Darwin" ]; then FONT_DIR="$HOME/Library/Fonts"; else FONT_DIR="$HOME/.local/share/fonts"; fi
install_nerd_font() {
  local name="$1"
  local marker="$FONT_DIR/.nerd-font-${name}-installed"
  if [ -f "$marker" ]; then
    return
  fi
  info "Nerd Font 설치: $name"
  local tmp; tmp="$(mktemp -d)"
  # 폰트는 부가 요소 — 다운로드/압축해제 실패 시 경고만 남기고 다음 단계로 진행 (마커 미생성 → 재실행 시 재시도).
  # trap RETURN 은 함수 밖으로 새어 이후 모든 함수 리턴에 발화하므로 쓰지 않고, 정리는 단일 지점에서 한 번만.
  # 설치한 파일명을 manifest(.nerd-font-<name>-files.txt) 에 남겨 uninstall.sh 가 정확히 그 파일만 지운다.
  local ok=1
  { curl -fsSL -o "$tmp/$name.zip" "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/$name.zip" \
      && unzip -oq "$tmp/$name.zip" -d "$tmp/$name" \
      && find "$tmp/$name" \( -iname "*.ttf" -o -iname "*.otf" \) -exec basename {} \; > "$FONT_DIR/.nerd-font-${name}-files.txt" \
      && find "$tmp/$name" \( -iname "*.ttf" -o -iname "*.otf" \) -exec cp {} "$FONT_DIR/" \; \
      && touch "$marker"; } || ok=0
  rm -rf "$tmp"
  [ "$ok" = 1 ] || info "경고: Nerd Font $name 다운로드/압축해제 실패 — 건너뜀 (네트워크·GitHub 릴리스 확인 후 재실행)"
}
if is_wsl; then
  # 글리프를 그리는 것은 Windows 쪽 터미널이다. WSL 안에 설치해도 효과가 없고, Windows 사용자 프로필은 $HOME 밖이라 자동 설치하지 않는다.
  info "WSL 감지 — Nerd Font 설치 건너뜀. Windows 에 JetBrainsMono Nerd Font(또는 D2Coding Nerd Font)를 설치하고 터미널 프로필의 글꼴로 지정 (README 'Windows (WSL2)' 절)"
else
  mkdir -p "$FONT_DIR"
  for font in JetBrainsMono D2Coding; do
    install_nerd_font "$font"
  done
  if [ "$OS" = "Darwin" ]; then
    info "Nerd Font 설치 완료 (Font Book 자동 등록)"
  else
    command -v fc-cache >/dev/null && fc-cache -f "$FONT_DIR" >/dev/null
    info "Nerd Font 설치 완료 (fc-cache 반영)"
  fi
fi

# ── 3. zshrc ───────────────────────────────────────────────
if [ "$OS" = "Darwin" ]; then SRC=zsh/zshrc.macos; else SRC=zsh/zshrc.linux; fi
deploy_file "$SRC" "$HOME/.zshrc" zshrc
info ".zshrc 배치 완료 ($SRC)"
[ -f "$HOME/.zshrc.local" ] || info "참고: 머신별 alias/함수는 ~/.zshrc.local 에 (템플릿: zsh/zshrc.local.example). 없으면 건너뜀"

# ── 4. Claude Code statusline ──────────────────────────────
# 스크립트 복사 + settings.json 에 statusLine 및 ui.footer 키 merge (다른 키는 건드리지 않음)
deploy_file claude/statusline-command.sh "$HOME/.claude/statusline-command.sh" statusline-command.sh
chmod 700 "$HOME/.claude/statusline-command.sh"
command -v jq >/dev/null || info "경고: statusline 스크립트는 jq 필요 — 배포판 패키지 관리자로 설치 권장"
python3 - <<'PYEOF'
import json, os, sys, tempfile
home = os.path.expanduser("~")
p = os.path.join(home, ".claude", "settings.json")
backup = os.path.join(home, ".dotfiles-backup")

def atomic_write_json(path, obj):
    """같은 디렉터리의 임시 파일에 쓰고 os.replace 로 교체 — 중단돼도 원본은 온전. 기존 mode 보존."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2); f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

d = {}
existed = os.path.exists(p)
if existed:
    try:
        with open(p) as f:
            d = json.load(f)
    except ValueError as e:
        print(f"[install] 오류: {p} 이 올바른 JSON 이 아님 ({e}) — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    if not isinstance(d, dict):
        print(f"[install] 오류: {p} 최상위가 객체가 아님 — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
# 최초 1회: settings.json 자체 유무와 이전 내용을 기록 (uninstall 복원용)
if not os.path.exists(os.path.join(backup, "settings.json.orig")) and not os.path.exists(os.path.join(backup, "settings.json.absent")):
    if existed:
        atomic_write_json(os.path.join(backup, "settings.json.orig"), d)
    else:
        open(os.path.join(backup, "settings.json.absent"), "w").close()

changed = False
want = {"type": "command", "command": f"bash {home}/.claude/statusline-command.sh"}
if d.get("statusLine") != want:
    d["statusLine"] = want
    changed = True

ui = d.setdefault("ui", {})
if not isinstance(ui, dict):
    ui = {}
    d["ui"] = ui
footer = ui.setdefault("footer", {})
if not isinstance(footer, dict):
    footer = {}
    ui["footer"] = footer
if footer.get("hideContextPercentage") is not False:
    footer["hideContextPercentage"] = False
    changed = True

if changed:
    atomic_write_json(p, d)
    print("[install] settings.json statusLine/ui.footer 키 갱신")
else:
    print("[install] settings.json statusLine/ui.footer 이미 최신")
PYEOF
info "Claude statusline 배치 완료"

# ── 5. Antigravity (agy) statusline ────────────────────────
# 스크립트 복사 + settings.json 에 statusLine 및 ui.footer 키 merge (다른 키는 건드리지 않음)
if :; then  # CLI 설치 여부와 무관하게 3사 설정을 준비한다.
  deploy_file agy/statusline-command.sh "$HOME/.gemini/antigravity-cli/statusline-command.sh" agy-statusline-command.sh
  chmod 700 "$HOME/.gemini/antigravity-cli/statusline-command.sh"
  python3 - <<'PYEOF'
import json, os, sys, tempfile
home = os.path.expanduser("~")
p = os.path.join(home, ".gemini", "antigravity-cli", "settings.json")
backup = os.path.join(home, ".dotfiles-backup")

def atomic_write_json(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2); f.write("\n")
            f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

d = {}
existed = os.path.exists(p)
if existed:
    try:
        with open(p) as f:
            d = json.load(f)
    except ValueError as e:
        print(f"[install] 오류: {p} 이 올바른 JSON 이 아님 ({e}) — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    if not isinstance(d, dict):
        print(f"[install] 오류: {p} 최상위가 객체가 아님 — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)

orig_p = os.path.join(backup, "gemini-settings.json.orig")
absent_p = os.path.join(backup, "gemini-settings.json.absent")
if not os.path.exists(orig_p) and not os.path.exists(absent_p):
    if existed:
        atomic_write_json(orig_p, d)
    else:
        open(absent_p, "w").close()

changed = False
want_cmd = {"type": "command", "command": f"bash {home}/.gemini/antigravity-cli/statusline-command.sh"}
if d.get("statusLine") != want_cmd:
    d["statusLine"] = want_cmd
    changed = True

ui = d.setdefault("ui", {})
if not isinstance(ui, dict):
    ui = {}
    d["ui"] = ui
footer = ui.setdefault("footer", {})
if not isinstance(footer, dict):
    footer = {}
    ui["footer"] = footer
if footer.get("hideContextPercentage") is not False:
    footer["hideContextPercentage"] = False
    changed = True

if changed:
    atomic_write_json(p, d)
    print("[install] agy settings.json statusLine/ui.footer 키 갱신")
else:
    print("[install] agy settings.json statusLine/ui.footer 이미 최신")
PYEOF
  info "Antigravity (agy) statusline 배치 완료"
fi

# ── 6. Codex CLI status line ───────────────────────────────
# Codex 는 외부 명령 status line 이 없어 스크립트 대신 config.toml 의 [tui] status_line 키만 merge (다른 키는 건드리지 않음)
if :; then  # 에이전트 어댑터와 함께 기본 상태줄 설정도 첫 실행에 준비한다.
  python3 codex/status-line.py apply
  info "Codex status line 배치 완료"
fi

# ── 7. Global AI Agent Rules & SSOT Memory ──────────────────
# ~/.config/ai/AGENTS.md 를 단일 원본(SSOT)으로 배치하고 각 에이전트 경로에 심볼릭 링크
deploy_file ai/AGENTS.md "$HOME/.config/ai/AGENTS.md" ai-agents.md
chmod 600 "$HOME/.config/ai/AGENTS.md"
if [ ! -f "$HOME/.config/ai/MEMORY.md" ]; then
  deploy_file ai/MEMORY.example.md "$HOME/.config/ai/MEMORY.md" ai-memory.md
  info "새 MEMORY.md 템플릿 생성 (~/.config/ai/MEMORY.md)"
else
  info "기존 MEMORY.md 유지 (~/.config/ai/MEMORY.md)"
fi
if [ -f "$HOME/.config/ai/MEMORY.md" ] && [ ! -L "$HOME/.config/ai/MEMORY.md" ]; then
  chmod 600 "$HOME/.config/ai/MEMORY.md"
fi

# Claude Code: ~/.claude/CLAUDE.md -> ~/.config/ai/AGENTS.md
deploy_symlink "$HOME/.config/ai/AGENTS.md" "$HOME/.claude/CLAUDE.md" claude-claude.md

# Antigravity CLI: ~/.gemini/AGENTS.md -> ~/.config/ai/AGENTS.md
deploy_symlink "$HOME/.config/ai/AGENTS.md" "$HOME/.gemini/AGENTS.md" gemini-agents.md

# Codex CLI: ~/.codex/AGENTS.md -> ~/.config/ai/AGENTS.md
deploy_symlink "$HOME/.config/ai/AGENTS.md" "$HOME/.codex/AGENTS.md" codex-agents.md
if [ -n "${CODEX_HOME:-}" ] && [ "$CODEX_HOME" != "$HOME/.codex" ] && [ -d "$CODEX_HOME" ]; then
  deploy_symlink "$HOME/.config/ai/AGENTS.md" "$CODEX_HOME/AGENTS.md" codex-home-agents.md
fi
info "글로벌 에이전트 규칙(AGENTS.md) 배포 및 심볼릭 링크 완료"

# 3사 공용 훅·설정 템플릿·역할 어댑터: 기존 사용자 설정은 키 단위로 보존한다.
deploy_file ai/hooks/session_handoff_guard.py "$HOME/.config/ai/hooks/session_handoff_guard.py" session-handoff-guard.py
if [ ! -L "$HOME/.config/ai/hooks" ]; then chmod 700 "$HOME/.config/ai/hooks"; fi
if [ ! -L "$HOME/.config/ai/hooks/session_handoff_guard.py" ]; then chmod 600 "$HOME/.config/ai/hooks/session_handoff_guard.py"; fi
deploy_file codex/statusbar.py "$HOME/.local/share/codex-statusbar/statusbar.py" codex-statusbar.py
deploy_file codex/codex-pretty "$HOME/.local/bin/codex-pretty" codex-pretty
chmod 700 "$HOME/.local/bin/codex-pretty"
for setting in claude.json agy.json gemini-cli.json codex.toml; do
  deploy_file "settings/$setting" "$HOME/.config/ai/settings/$setting" "agent-setting-$setting"
done
for src in ai/agents/claude/*.md; do
  name="$(basename "$src")"
  deploy_file "$src" "$HOME/.claude/agents/$name" "agent-claude-$name"
done
for src in ai/agents/codex/*.toml; do
  name="$(basename "$src")"
  deploy_file "$src" "${CODEX_HOME:-$HOME/.codex}/agents/$name" "agent-codex-$name"
done
for src in ai/agents/agy/*.md; do
  name="$(basename "$src")"
  deploy_file "$src" "$HOME/.gemini/config/plugins/dotfiles-agent-adapters/agents/$name" "agent-agy-$name"
done
deploy_file ai/agents/plugin.json "$HOME/.gemini/config/plugins/dotfiles-agent-adapters/plugin.json" agent-plugin.json
python3 scripts/agent-config.py apply
info "3사 훅·역할 어댑터·설정 템플릿 배치 완료 (스킬 본문은 원본 저장소에서 설치)"

# ── 7.1. 3사 공용 에이전트 허브 (Agent Hub) 및 스킬 통합 ──────
if [ -n "${AGENT_HUB_DIR:-}" ]; then
  HUB_TARGET="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$AGENT_HUB_DIR")"
  HUB_TARGET_CUSTOM=1
else
  HUB_TARGET="$HOME/.config/ai/agent_hub"
  HUB_TARGET_CUSTOM=0
fi
HUB_TARGET_SYMLINK=0
[ -L "$HUB_TARGET" ] && HUB_TARGET_SYMLINK=1
mkdir -p "$HUB_TARGET/scripts" "$HUB_TARGET/schema" "$HUB_TARGET/skills" "$HOME/.local/bin" \
  || die "Agent Hub 경로를 만들 수 없음: $HUB_TARGET"
HUB_TARGET="$(cd "$HUB_TARGET" && pwd -P)"
if [ "$HUB_TARGET_CUSTOM" = 0 ] && [ "$HUB_TARGET_SYMLINK" = 0 ]; then chmod 700 "$HUB_TARGET"; fi
export AGENT_HUB_DIR="$HUB_TARGET"
if [ -n "${AGENT_HUB_DB:-}" ]; then
  AGENT_HUB_DB="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$AGENT_HUB_DB")"
else
  AGENT_HUB_DB="$HUB_TARGET/agent_hub.db"
fi
export AGENT_HUB_DB
mkdir -p "$(dirname "$AGENT_HUB_DB")" || die "Agent Hub DB 디렉터리를 만들 수 없음: $(dirname "$AGENT_HUB_DB")"

deploy_file ai/agent_hub/schema/schema.sql "$HUB_TARGET/schema/schema.sql" agent-hub-schema.sql
deploy_file ai/agent_hub/scripts/ingest_sessions.py "$HUB_TARGET/scripts/ingest_sessions.py" agent-hub-ingest.py
deploy_file ai/agent_hub/scripts/agent_hub_cli.py "$HUB_TARGET/scripts/agent_hub_cli.py" agent-hub-cli.py
chmod 700 "$HUB_TARGET/scripts/"*.py 2>/dev/null || true

# agent-hub CLI 및 codex 래퍼 심볼릭 링크/배치
if [ -L "$HOME/.local/bin/agent-hub" ] \
  && [ "$(readlink "$HOME/.local/bin/agent-hub")" = "$HUB_TARGET/scripts/agent_hub_cli.py" ]; then
  :
elif [ ! -e "$HOME/.local/bin/agent-hub" ] && [ ! -L "$HOME/.local/bin/agent-hub" ]; then
  deploy_symlink "$HUB_TARGET/scripts/agent_hub_cli.py" "$HOME/.local/bin/agent-hub" agent-hub-bin
else
  info "기존 ~/.local/bin/agent-hub 유지 — 링크 설치 건너뜀"
fi
if [ -f codex/bin/codex ]; then
  if [ ! -e "$HOME/.local/bin/codex" ] && [ ! -L "$HOME/.local/bin/codex" ] \
    || grep -q '^# DOTFILES_CODEX_WRAPPER=1$' "$HOME/.local/bin/codex" 2>/dev/null \
    || { [ -f "$BACKUP_DIR/codex-bin.absent" ] && grep -q '^# Codex CLI 래퍼 스크립트 (환경 자동 감지)$' "$HOME/.local/bin/codex" 2>/dev/null; }; then
    deploy_file codex/bin/codex "$HOME/.local/bin/codex" codex-bin
    chmod 700 "$HOME/.local/bin/codex" 2>/dev/null || true
  else
    info "기존 ~/.local/bin/codex CLI 유지 — 래퍼 설치 건너뜀"
  fi
fi

# 스키마 보완 (sqlite3 CLI가 없어도 Python 표준 라이브러리를 사용하며, 기존 행은 건드리지 않는다)
if ! python3 - "$AGENT_HUB_DB" <<'PYEOF'
import sqlite3, sys
try:
    conn = sqlite3.connect(sys.argv[1])
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    raise SystemExit(0 if {"sessions", "turns", "tool_executions", "handoffs", "turns_fts"} <= names else 1)
except sqlite3.Error:
    raise SystemExit(1)
PYEOF
then
  python3 -c 'import os,sqlite3,sys; os.umask(0o077); db,schema=sys.argv[1:]; conn=sqlite3.connect(db); conn.executescript(open(schema, encoding="utf-8").read()); conn.close()' \
    "$AGENT_HUB_DB" "$HUB_TARGET/schema/schema.sql" \
    || die "Agent Hub SQLite 초기화 실패: $AGENT_HUB_DB"
fi
chmod 600 "$AGENT_HUB_DB"

# 3사 스킬 디렉터리 통합 링크. 기존 실제 디렉터리·다른 링크는 사용자 자료로 보고 보존한다.
for skill_dir in "$HOME/.claude/skills" "$HOME/.gemini/antigravity-cli/skills" "${CODEX_HOME:-$HOME/.codex}/skills" "$HOME/.config/ai/skills"; do
  skill_link_name="skills-link-$(basename "$(dirname "$skill_dir")")"
  if [ -L "$skill_dir" ]; then
    if [ "$(readlink "$skill_dir")" != "$HUB_TARGET/skills" ]; then
      info "기존 스킬 링크 유지 — $skill_dir"
    fi
  elif [ -e "$skill_dir" ]; then
    info "기존 스킬 디렉터리 유지 — $skill_dir (공유 링크는 건너뜀)"
  else
    deploy_symlink "$HUB_TARGET/skills" "$skill_dir" "$skill_link_name"
  fi
done
info "3사 공용 에이전트 허브 및 스킬 단일 원본(SSOT) 배포 완료"

# ── 7.2. 터미널 파일 뷰어 (yazi + glow + chafa, fview 미리보기) ──
# 바이너리는 없을 때만 설치한다. macOS 는 brew, Linux 는 GitHub 릴리스의 정적 바이너리를 ~/.local/bin 에 둔다.
# 내려받기에 실패해도 셸 환경과 무관하므로 경고만 하고 계속한다.
fetch_release_bin() {   # fetch_release_bin <URL> <실행 파일 이름...> — 압축을 풀어 ~/.local/bin 에 배치
  local url="$1" tmp f name; shift
  tmp="$(mktemp -d)"
  if curl -fsSL "$url" -o "$tmp/pkg" && case "$url" in *.zip) unzip -q "$tmp/pkg" -d "$tmp/x" ;; *) mkdir -p "$tmp/x" && tar xzf "$tmp/pkg" -C "$tmp/x" ;; esac; then
    for name in "$@"; do
      f="$(find "$tmp/x" -type f -name "$name" | head -1)"
      if [ -n "$f" ]; then
        mkdir -p "$HOME/.local/bin"
        install -m 755 "$f" "$HOME/.local/bin/$name"
        record bin-installed.txt "$HOME/.local/bin/$name"
        info "$name 설치 (~/.local/bin)"
      else
        info "경고: $url 안에 $name 없음"
      fi
    done
  else
    info "경고: 내려받기 실패 — $url"
  fi
  rm -rf "$tmp"
}
if [ "$OS" = "Darwin" ]; then
  for pkg in yazi glow chafa; do
    brew list "$pkg" >/dev/null 2>&1 || { info "brew install $pkg"; brew install "$pkg" && record brew-installed.txt "$pkg"; }
  done
else
  case "$(uname -m)" in
    x86_64)        ARCH=x86_64;  GLOW_ARCH=x86_64 ;;
    aarch64|arm64) ARCH=aarch64; GLOW_ARCH=arm64 ;;
    *)             ARCH="" ;;
  esac
  if [ -z "$ARCH" ]; then
    info "경고: $(uname -m) 용 뷰어 바이너리 없음 — yazi·glow·chafa 설치 건너뜀"
  else
    command -v yazi >/dev/null || [ -x "$HOME/.local/bin/yazi" ] || fetch_release_bin \
      "https://github.com/sxyazi/yazi/releases/latest/download/yazi-$ARCH-unknown-linux-musl.zip" yazi ya
    command -v glow >/dev/null || [ -x "$HOME/.local/bin/glow" ] || {
      GLOW_VER="$(curl -fsSL https://api.github.com/repos/charmbracelet/glow/releases/latest 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))' 2>/dev/null || true)"
      if [ -n "$GLOW_VER" ]; then
        fetch_release_bin "https://github.com/charmbracelet/glow/releases/download/v$GLOW_VER/glow_${GLOW_VER}_Linux_$GLOW_ARCH.tar.gz" glow
      else
        info "경고: glow 최신 버전 확인 실패 — 설치 건너뜀"
      fi
    }
    command -v chafa >/dev/null || [ -x "$HOME/.local/bin/chafa" ] || {
      CHAFA_TGZ="$(curl -fsSL https://hpjansson.org/chafa/releases/static/ 2>/dev/null \
        | grep -oE "chafa-[0-9.]+-[0-9]+-$ARCH-linux-gnu\.tar\.gz" | sort -uV | tail -1 || true)"
      if [ -n "$CHAFA_TGZ" ]; then
        fetch_release_bin "https://hpjansson.org/chafa/releases/static/$CHAFA_TGZ" chafa
      else
        info "경고: chafa 정적 빌드 확인 실패 — 설치 건너뜀"
      fi
    }
  fi
fi
deploy_file viewer/fview "$HOME/.local/bin/fview" fview
chmod 700 "$HOME/.local/bin/fview"
deploy_file viewer/yazi.toml "$HOME/.config/yazi/yazi.toml" yazi.toml
deploy_file viewer/keymap.toml "$HOME/.config/yazi/keymap.toml" yazi-keymap.toml
# piper: 명령 출력을 미리보기로 쓰는 공식 플러그인. fview 연결에 필요하다.
YA="$(command -v ya || true)"; [ -z "$YA" ] && [ -x "$HOME/.local/bin/ya" ] && YA="$HOME/.local/bin/ya"
if [ -d "$HOME/.config/yazi/plugins/piper.yazi" ]; then
  :
elif [ -n "$YA" ]; then
  preserve_original "$HOME/.config/yazi/package.toml" yazi-package.toml
  if "$YA" pkg add yazi-rs/plugins:piper >/dev/null 2>&1; then
    touch "$BACKUP_DIR/yazi-piper.installed"
    info "yazi piper 플러그인 설치"
  else
    info "경고: yazi piper 플러그인 설치 실패 — 문서형 미리보기는 yazi 기본값으로 동작"
  fi
else
  info "경고: ya 없음 — yazi piper 플러그인 설치 건너뜀"
fi
info "터미널 파일 뷰어 배치 완료 (실행: yazi, 단독 미리보기: fview <파일> 100 -p)"

# ── 7.3. Claude Code 외부 확장 (출력 스타일·명령·스킬) ──────
# claude/extensions.txt 의 저장소를 DOTFILES_EXT_DIR(기본 ~/.local/share/dotfiles-ext)에 클론하고
# ~/.claude 아래에 심볼릭 링크로 연결한다. 이미 클론돼 있으면 그대로 쓰고(갱신은 git pull), 실제 파일·폴더가 있는 자리는 건드리지 않는다.
EXT_DIR="${DOTFILES_EXT_DIR:-$HOME/.local/share/dotfiles-ext}"
if ! command -v git >/dev/null; then
  info "경고: git 없음 — Claude 외부 확장 건너뜀"
else
  while read -r repo slug src link; do
    case "$repo" in ''|'#'*) continue ;; esac
    dir="$EXT_DIR/$repo"
    if [ ! -d "$dir/.git" ]; then
      if [ -e "$dir" ]; then info "경고: $dir 이 git 저장소가 아님 — $repo 건너뜀"; continue; fi
      mkdir -p "$EXT_DIR"
      if git clone -q --depth 1 "https://github.com/$slug.git" "$dir"; then
        record ext-cloned.txt "$dir"
        info "클론: $slug → $dir"
      else
        info "경고: $slug 클론 실패 — 건너뜀"; continue
      fi
    fi
    [ -e "$dir/$src" ] || { info "경고: $repo 에 $src 없음 — 건너뜀"; continue; }
    dst="$HOME/.claude/$link"
    if [ -e "$dst" ] && [ ! -L "$dst" ]; then info "경고: $dst 이 실제 파일·폴더라 유지 — 링크 건너뜀"; continue; fi
    deploy_symlink "$dir/$src" "$dst" "claude-ext-$(printf '%s' "$link" | tr '/' '-')"
  done < claude/extensions.txt
  info "Claude 외부 확장 연결 완료 (출력 스타일 선택: /style 또는 /config)"
fi

# ── 7.4. 웹 IDE (code-server) ──────────────────────────────
# 서비스는 자동 시작하지 않는다. Linux/WSL 은 사용자 영역에 standalone 설치한다.
code_server_config="$HOME/.config/code-server"
mkdir -p "$code_server_config"
if [ -d "$code_server_config" ] && [ ! -L "$code_server_config" ]; then
  chmod 700 "$code_server_config"
  if [ -f "$code_server_config/config.yaml" ] && [ ! -L "$code_server_config/config.yaml" ]; then
    chmod 600 "$code_server_config/config.yaml"
  fi
fi
if command -v code-server >/dev/null 2>&1 || [ -x "$HOME/.local/bin/code-server" ]; then
  info "code-server 이미 설치됨 — 건너뜀"
elif [ -e "$HOME/.local/bin/code-server" ] || [ -L "$HOME/.local/bin/code-server" ]; then
  info "경고: ~/.local/bin/code-server 파일이 있지만 실행할 수 없어 기존 파일을 보존하고 설치를 건너뜀"
elif [ "$OS" = "Darwin" ]; then
  if brew list code-server >/dev/null 2>&1; then
    info "code-server 이미 Homebrew 에 설치됨 — 건너뜀"
  elif brew install code-server; then
    record brew-installed.txt code-server
    info "code-server 설치 완료 (서버는 자동 시작하지 않음)"
  else
    info "경고: code-server 설치 실패 — brew 상태를 확인한 뒤 재실행"
  fi
else
  case "$(uname -m)" in
    x86_64|aarch64|arm64)
      code_server_tmp="$(mktemp -d)"
      if curl -fsSL -o "$code_server_tmp/install.sh" https://code-server.dev/install.sh \
        && XDG_CACHE_HOME="$code_server_tmp/cache" sh "$code_server_tmp/install.sh" \
          --method standalone --prefix "$HOME/.local" > "$code_server_tmp/install.log" 2>&1; then
        code_server_bin="$HOME/.local/bin/code-server"
        if [ -x "$code_server_bin" ]; then
          code_server_target="$(readlink -f "$code_server_bin" 2>/dev/null || true)"
          code_server_dir="$(dirname "$(dirname "$code_server_target")")"
          case "$code_server_dir" in
            "$HOME"/.local/lib/code-server-*)
              record bin-installed.txt "$code_server_bin"
              record code-server-installed.txt "$code_server_dir"
              info "code-server 설치 완료 (~/.local, 서버는 자동 시작하지 않음)" ;;
            *)
              info "경고: code-server 는 설치됐지만 버전 디렉터리를 확인하지 못해 --purge 기록을 남기지 못함" ;;
          esac
        else
          info "경고: code-server 설치 스크립트는 종료됐지만 ~/.local/bin/code-server 를 확인하지 못함"
        fi
      else
        if [ -s "$code_server_tmp/install.log" ]; then tail -n 3 "$code_server_tmp/install.log"; fi
        info "경고: code-server 설치 실패 — 네트워크·운영체제 지원 여부를 확인한 뒤 재실행"
      fi
      rm -rf "$code_server_tmp" ;;
    *)
      info "경고: $(uname -m) 은 code-server standalone 릴리스 미지원 — 설치 건너뜀" ;;
  esac
fi

# ── 8. 기본 셸 ─────────────────────────────────────────────
ZSH_PATH="$(command -v zsh)"
if [ "${SHELL:-}" != "$ZSH_PATH" ]; then
  info "기본 셸이 zsh 가 아님 → 변경하려면: chsh -s $ZSH_PATH"
fi

info "완료. 새 셸을 열거나 'exec zsh' 로 적용."
