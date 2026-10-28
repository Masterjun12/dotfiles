#!/usr/bin/env bash
# dotfiles uninstall — install.sh 가 적용한 것을 되돌려 설치 전 zsh 상태로 복원
#
# 사용법:
#   ./uninstall.sh            # 배치 파일 복원/제거 + statusLine·Codex status_line 키 복원 + Nerd Font 제거
#   ./uninstall.sh --purge    # 위에 더해 install.sh 가 새로 설치한 패키지/바이너리·클론한 확장 저장소까지 제거
#   ./uninstall.sh --keep-backup   # ~/.dotfiles-backup 을 남겨둠 (기본은 복원 후 삭제)
#
# 복원 기준은 install.sh 가 최초 실행 때 ~/.dotfiles-backup/ 에 남긴 기록:
#   <name>.orig  → 그 내용으로 복원 / <name>.absent → 파일 삭제 / 기록 없음 → .bak 이 있으면 .bak 으로, 없으면 삭제
# 멱등(idempotent): 재실행해도 안전하다. 실제 홈이 아닌 곳에 시험하려면 HOME=<임시 디렉터리> ./uninstall.sh

set -euo pipefail
cd "$(dirname "$0")"

OS="$(uname -s)"
PURGE=0; KEEP_BACKUP=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    --keep-backup) KEEP_BACKUP=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $arg"; exit 1 ;;
  esac
done

info() { printf '\033[1;33m[uninstall]\033[0m %s\n' "$*"; }
BACKUP_DIR="$HOME/.dotfiles-backup"

# ── 1. 배치 파일 복원/제거 ──────────────────────────────────
restore_file() {        # restore_file <대상 경로> <기록 이름>
  local dst="$1" name="$2"
  if [ -f "$BACKUP_DIR/$name.orig" ] || [ -L "$BACKUP_DIR/$name.orig" ]; then
    rm -f "$dst"
    cp -P "$BACKUP_DIR/$name.orig" "$dst"
    info "$dst ← 설치 전 원본 복원"
  elif [ -f "$BACKUP_DIR/$name.absent" ]; then
    rm -f "$dst"
    info "$dst 삭제 (설치 전에는 없던 파일)"
  elif [ -e "$dst.bak" ] || [ -L "$dst.bak" ]; then
    rm -f "$dst"
    cp -P "$dst.bak" "$dst"
    info "$dst ← .bak 복원 (원본 기록 없음 — 구버전 install.sh 로 설치된 경우)"
  elif [ -e "$dst" ] || [ -L "$dst" ]; then
    rm -f "$dst"
    info "$dst 삭제 (원본 기록·.bak 없음)"
  fi
  rm -f "$dst.bak"
}
# 새 기능은 설치 기록이 있는 파일만 되돌린다.
python3 scripts/agent-config.py restore
restore_managed_file() {
  local dst="$1" name="$2"
  if [ -e "$BACKUP_DIR/$name.orig" ] || [ -L "$BACKUP_DIR/$name.orig" ] || [ -e "$BACKUP_DIR/$name.absent" ]; then
    restore_file "$dst" "$name"
  fi
}
restore_managed_file "$HOME/.config/ai/hooks/session_handoff_guard.py" session-handoff-guard.py
restore_managed_file "$HOME/.local/share/codex-statusbar/statusbar.py" codex-statusbar.py
restore_managed_file "$HOME/.local/bin/codex-pretty" codex-pretty
restore_managed_file "$HOME/.local/bin/codex" codex-bin
restore_managed_file "$HOME/.local/bin/agent-hub" agent-hub-bin
for skill_dir in "$HOME/.claude/skills" "$HOME/.gemini/antigravity-cli/skills" "${CODEX_HOME:-$HOME/.codex}/skills" "$HOME/.config/ai/skills"; do
  skill_link_name="skills-link-$(basename "$(dirname "$skill_dir")")"
  restore_managed_file "$skill_dir" "$skill_link_name"
done
for setting in claude.json agy.json gemini-cli.json codex.toml; do
  restore_managed_file "$HOME/.config/ai/settings/$setting" "agent-setting-$setting"
done
for src in ai/agents/claude/*.md; do
  name="$(basename "$src")"
  restore_managed_file "$HOME/.claude/agents/$name" "agent-claude-$name"
done
for src in ai/agents/codex/*.toml; do
  name="$(basename "$src")"
  restore_managed_file "${CODEX_HOME:-$HOME/.codex}/agents/$name" "agent-codex-$name"
done
for src in ai/agents/agy/*.md; do
  name="$(basename "$src")"
  restore_managed_file "$HOME/.gemini/config/plugins/dotfiles-agent-adapters/agents/$name" "agent-agy-$name"
done
restore_managed_file "$HOME/.gemini/config/plugins/dotfiles-agent-adapters/plugin.json" agent-plugin.json
restore_file "$HOME/.config/starship.toml" starship.toml
restore_file "$HOME/.zshrc" zshrc
[ -f "$HOME/.zshrc.local" ] && info "$HOME/.zshrc.local 은 사용자 파일 — 유지 (install.sh 가 만든 것이 아님)"
restore_file "$HOME/.claude/statusline-command.sh" statusline-command.sh
restore_file "$HOME/.gemini/antigravity-cli/statusline-command.sh" agy-statusline-command.sh
restore_file "$HOME/.config/ai/AGENTS.md" ai-agents.md
# 기존 메모리와 설치 후 보완된 메모리는 사용자 데이터로 보존한다.
if [ -f "$BACKUP_DIR/ai-memory.md.absent" ] && [ -f "$HOME/.config/ai/MEMORY.md" ] && ! cmp -s ai/MEMORY.example.md "$HOME/.config/ai/MEMORY.md"; then
  info "보완된 MEMORY.md 유지"
else
  restore_managed_file "$HOME/.config/ai/MEMORY.md" ai-memory.md
fi
restore_file "$HOME/.claude/CLAUDE.md" claude-claude.md
restore_file "$HOME/.gemini/AGENTS.md" gemini-agents.md
restore_file "$HOME/.codex/AGENTS.md" codex-agents.md
if [ -n "${CODEX_HOME:-}" ] && [ "$CODEX_HOME" != "$HOME/.codex" ]; then
  restore_file "$CODEX_HOME/AGENTS.md" codex-home-agents.md
fi

# install.sh 7.2 — 터미널 파일 뷰어 설정과 piper 플러그인
restore_managed_file "$HOME/.local/bin/fview" fview
restore_managed_file "$HOME/.config/yazi/yazi.toml" yazi.toml
restore_managed_file "$HOME/.config/yazi/keymap.toml" yazi-keymap.toml
if [ -f "$BACKUP_DIR/yazi-piper.installed" ]; then
  rm -rf "$HOME/.config/yazi/plugins/piper.yazi"
  restore_managed_file "$HOME/.config/yazi/package.toml" yazi-package.toml
  rm -f "$BACKUP_DIR/yazi-piper.installed"
  info "yazi piper 플러그인 제거"
fi
rmdir "$HOME/.config/yazi/plugins" "$HOME/.config/yazi" 2>/dev/null || true

# install.sh 7.3 — Claude 외부 확장 링크 (클론한 저장소는 --purge 때만 삭제)
while read -r repo slug src link; do
  case "$repo" in ''|'#'*) continue ;; esac
  restore_managed_file "$HOME/.claude/$link" "claude-ext-$(printf '%s' "$link" | tr '/' '-')"
done < claude/extensions.txt
rmdir "$HOME/.claude/output-styles" "$HOME/.claude/commands" "$HOME/.claude/skills" 2>/dev/null || true

# ── 2. Claude settings.json 의 statusLine/ui.footer 복원 ──────
python3 - <<'PYEOF'
import json, os, sys, tempfile
home = os.path.expanduser("~")
p = os.path.join(home, ".claude", "settings.json")
backup = os.path.join(home, ".dotfiles-backup")
orig = os.path.join(backup, "settings.json.orig")
absent = os.path.join(backup, "settings.json.absent")

def atomic_write_json(path, obj):
    d = os.path.dirname(path)
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

def load_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except ValueError as e:
        print(f"[uninstall] 오류: {path} 이 올바른 JSON 이 아님 ({e}) — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    if not isinstance(d, dict):
        print(f"[uninstall] 오류: {path} 최상위가 객체가 아님 — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    return d

if not os.path.exists(p):
    print("[uninstall] settings.json 없음 — 건너뜀")
elif os.path.exists(absent):
    d = load_json(p)
    d.pop("statusLine", None)
    if "ui" in d and isinstance(d["ui"], dict):
        d["ui"].get("footer", {}).pop("hideContextPercentage", None)
        if d["ui"].get("footer") == {}:
            d["ui"].pop("footer")
        if d["ui"] == {}:
            d.pop("ui")
    if d:
        atomic_write_json(p, d)
        print("[uninstall] settings.json statusLine/ui.footer 키 제거 (다른 키는 유지)")
    else:
        os.remove(p)
        print("[uninstall] settings.json 삭제 (설치 전에는 없던 파일이고 남은 키 없음)")
else:
    d = load_json(p)
    orig_d = load_json(orig) if os.path.exists(orig) else {}
    if "statusLine" in orig_d:
        d["statusLine"] = orig_d["statusLine"]
    else:
        d.pop("statusLine", None)
    if "ui" in orig_d:
        d["ui"] = orig_d["ui"]
    elif "ui" in d and isinstance(d["ui"], dict):
        d["ui"].get("footer", {}).pop("hideContextPercentage", None)
        if d["ui"].get("footer") == {}:
            d["ui"].pop("footer")
        if d["ui"] == {}:
            d.pop("ui")
    atomic_write_json(p, d)
    print("[uninstall] settings.json statusLine/ui.footer 키를 설치 전 값으로 복원")
PYEOF

# ── 2.5. Antigravity settings.json 의 statusLine/ui.footer 복원 ─
python3 - <<'PYEOF'
import json, os, sys, tempfile
home = os.path.expanduser("~")
p = os.path.join(home, ".gemini", "antigravity-cli", "settings.json")
backup = os.path.join(home, ".dotfiles-backup")
orig = os.path.join(backup, "gemini-settings.json.orig")
absent = os.path.join(backup, "gemini-settings.json.absent")

def atomic_write_json(path, obj):
    d = os.path.dirname(path)
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

def load_json(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except ValueError as e:
        print(f"[uninstall] 오류: {path} 이 올바른 JSON 이 아님 ({e}) — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    if not isinstance(d, dict):
        print(f"[uninstall] 오류: {path} 최상위가 객체가 아님 — 원본을 건드리지 않고 중단", file=sys.stderr)
        sys.exit(1)
    return d

if not os.path.exists(orig) and not os.path.exists(absent):
    pass
elif not os.path.exists(p):
    print("[uninstall] agy settings.json 없음 — 건너뜀")
elif os.path.exists(absent):
    d = load_json(p)
    d.pop("statusLine", None)
    if "ui" in d and isinstance(d["ui"], dict):
        d["ui"].get("footer", {}).pop("hideContextPercentage", None)
        if d["ui"].get("footer") == {}:
            d["ui"].pop("footer")
        if d["ui"] == {}:
            d.pop("ui")
    if d:
        atomic_write_json(p, d)
        print("[uninstall] agy settings.json statusLine/ui.footer 키 제거 (다른 키는 유지)")
    else:
        os.remove(p)
        print("[uninstall] agy settings.json 삭제 (설치 전에는 없던 파일이고 남은 키 없음)")
else:
    d = load_json(p)
    orig_d = load_json(orig) if os.path.exists(orig) else {}
    if "statusLine" in orig_d:
        d["statusLine"] = orig_d["statusLine"]
    else:
        d.pop("statusLine", None)
    if "ui" in orig_d:
        d["ui"] = orig_d["ui"]
    elif "ui" in d and isinstance(d["ui"], dict):
        d["ui"].get("footer", {}).pop("hideContextPercentage", None)
        if d["ui"].get("footer") == {}:
            d["ui"].pop("footer")
        if d["ui"] == {}:
            d.pop("ui")
    atomic_write_json(p, d)
    print("[uninstall] agy settings.json statusLine/ui.footer 키를 설치 전 값으로 복원")
PYEOF

# ── 3. Codex config.toml 의 [tui] status_line 키만 복원 (다른 키 불변, 원자적 쓰기) ──
# install.sh 가 Codex 단계를 건너뛴 머신(기록 없음)에서는 아무것도 하지 않는다
python3 codex/status-line.py restore

# ── 4. Nerd Fonts 제거 (manifest 에 기록된 파일만) ───────────
if [ "$OS" = "Darwin" ]; then FONT_DIR="$HOME/Library/Fonts"; else FONT_DIR="$HOME/.local/share/fonts"; fi
for name in JetBrainsMono D2Coding; do
  manifest="$FONT_DIR/.nerd-font-${name}-files.txt"
  marker="$FONT_DIR/.nerd-font-${name}-installed"
  if [ -f "$manifest" ]; then
    n=0
    while IFS= read -r f; do
      case "$f" in
        */*|""|.|..) info "경고: 폰트 manifest 경로가 파일명 형식이 아니라 건너뜀"; continue ;;
        *.ttf|*.TTF|*.otf|*.OTF) ;;
        *) info "경고: 폰트 manifest 항목이 글꼴 확장자가 아니라 건너뜀: $f"; continue ;;
      esac
      rm -f -- "$FONT_DIR/$f" && n=$((n+1))
    done < "$manifest"
    rm -f "$manifest" "$marker"
    info "Nerd Font $name 제거 ($n 파일)"
  elif [ -f "$marker" ]; then
    rm -f "$marker"
    info "경고: Nerd Font $name 은 파일 목록(manifest) 없이 설치됨 — 마커만 제거, 폰트 파일은 $FONT_DIR 에서 수동 삭제"
  fi
done
if [ "$OS" != "Darwin" ] && command -v fc-cache >/dev/null; then fc-cache -f "$FONT_DIR" >/dev/null || true; fi

# ── 5. --purge: install.sh 가 새로 설치한 패키지/바이너리 제거 ─
if [ "$PURGE" = 1 ]; then
  if [ "$OS" = "Darwin" ] && [ -s "$BACKUP_DIR/brew-installed.txt" ]; then
    while IFS= read -r pkg; do
      case "$pkg" in
        [A-Za-z0-9]*)
          case "$pkg" in *[!A-Za-z0-9+_.@-]*) info "경고: 잘못된 Homebrew manifest 항목을 건너뜀"; continue ;; esac ;;
        *) info "경고: 잘못된 Homebrew manifest 항목을 건너뜀"; continue ;;
      esac
      brew list "$pkg" >/dev/null 2>&1 && { info "brew uninstall $pkg"; brew uninstall "$pkg"; }
    done < "$BACKUP_DIR/brew-installed.txt"
  fi
  if [ -s "$BACKUP_DIR/bin-installed.txt" ]; then
    local_bin_real="$(cd "$HOME/.local/bin" 2>/dev/null && pwd -P || true)"
    system_bin_real="$(cd /usr/local/bin 2>/dev/null && pwd -P || true)"
    while IFS= read -r bin; do
      [ -f "$bin" ] || [ -L "$bin" ] || continue
      bin_parent="$(cd "$(dirname "$bin")" 2>/dev/null && pwd -P || true)"
      bin_name="$(basename "$bin")"
      if [ -n "$local_bin_real" ] && [ "$bin_parent" = "$local_bin_real" ] \
        && [[ "$bin_name" == starship || "$bin_name" == yazi || "$bin_name" == ya \
          || "$bin_name" == glow || "$bin_name" == chafa || "$bin_name" == fview \
          || "$bin_name" == code-server ]]; then
        rm -f -- "$bin"
        info "삭제: $bin"
      elif [ "$bin" = /usr/local/bin/starship ] && [ "$bin_parent" = "$system_bin_real" ]; then
        if [ -w "$bin_parent" ]; then rm -f -- "$bin"
        elif command -v sudo >/dev/null 2>&1; then sudo rm -f -- "$bin"
        else info "경고: 관리자 권한이 없어 $bin 제거 건너뜀"; continue; fi
        info "삭제: $bin"
      else
        info "경고: 설치 허용 경로가 아닌 바이너리 manifest 항목을 건너뜀: $bin"
      fi
    done < "$BACKUP_DIR/bin-installed.txt"
  fi
  if [ -s "$BACKUP_DIR/code-server-installed.txt" ]; then
    code_server_lib="$HOME/.local/lib"
    code_server_lib_real="$(cd "$code_server_lib" 2>/dev/null && pwd -P || true)"
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      path_parent="$(cd "$(dirname "$path")" 2>/dev/null && pwd -P || true)"
      path_name="$(basename "$path")"
      if [ -n "$code_server_lib_real" ] && [ "$path_parent" = "$code_server_lib_real" ] \
        && [[ "$path_name" == code-server-* ]] && [ -d "$path" ] && [ ! -L "$path" ]; then
        rm -rf -- "$path"
        info "code-server 제거: $path"
      else
        info "경고: code-server 제거 경로가 허용된 사용자 영역과 일치하지 않아 건너뜀: $path"
      fi
    done < "$BACKUP_DIR/code-server-installed.txt"
  fi
  if [ "$OS" != "Darwin" ] && [ -s "$BACKUP_DIR/pkg-installed.txt" ]; then
    pkgs=()
    while IFS= read -r pkg; do
      case "$pkg" in
        ""|-*|[!A-Za-z0-9]*|*[!A-Za-z0-9+_.:@-]*) info "경고: 잘못된 패키지 manifest 항목을 건너뜀" ;;
        *) pkgs+=("$pkg") ;;
      esac
    done < "$BACKUP_DIR/pkg-installed.txt"
    if [ "${#pkgs[@]}" -eq 0 ]; then
      info "--purge: 제거할 수 있는 패키지 manifest 항목 없음"
    else
      info "설치 기록에 있는 패키지 제거: ${pkgs[*]}"
      if [ "$(id -u)" -eq 0 ]; then SUDO=()
      elif command -v sudo >/dev/null 2>&1; then SUDO=(sudo)
      else SUDO=(false); fi
      if command -v dnf >/dev/null; then "${SUDO[@]}" dnf remove -y "${pkgs[@]}" || info "경고: dnf remove 실패"
      elif command -v apt-get >/dev/null; then "${SUDO[@]}" apt-get remove -y "${pkgs[@]}" || info "경고: apt-get remove 실패"
      elif command -v pacman >/dev/null; then "${SUDO[@]}" pacman -Rns --noconfirm "${pkgs[@]}" || info "경고: pacman 제거 실패"
      elif command -v zypper >/dev/null; then "${SUDO[@]}" zypper --non-interactive remove "${pkgs[@]}" || info "경고: zypper 제거 실패"
      elif command -v apk >/dev/null; then "${SUDO[@]}" apk del "${pkgs[@]}" || info "경고: apk 제거 실패"
      else info "경고: 지원 패키지 관리자를 찾지 못해 패키지 제거 건너뜀"; fi
    fi
  fi
  if [ -s "$BACKUP_DIR/ext-cloned.txt" ]; then
    ext_root="${DOTFILES_EXT_DIR:-$HOME/.local/share/dotfiles-ext}"
    ext_root_real="$(cd "$ext_root" 2>/dev/null && pwd -P || true)"
    while IFS= read -r dir; do
      [ -n "$dir" ] || continue
      dir_parent="$(cd "$(dirname "$dir")" 2>/dev/null && pwd -P || true)"
      dir_name="$(basename "$dir")"
      allowed_repo=0
      while read -r repo slug src link; do
        case "$repo" in ''|'#'*) continue ;; esac
        [ "$dir_name" = "$repo" ] && allowed_repo=1 && break
      done < claude/extensions.txt
      if [ "$allowed_repo" = 1 ] && [ -n "$ext_root_real" ] \
        && [ "$dir_parent" = "$ext_root_real" ] && [ -d "$dir/.git" ] \
        && [ ! -L "$dir" ] && [ ! -L "$dir/.git" ]; then
        rm -rf -- "$dir"
        info "삭제: $dir"
      else
        info "경고: Claude 확장 manifest 경로가 허용된 저장소 위치와 일치하지 않아 건너뜀: $dir"
      fi
    done < "$BACKUP_DIR/ext-cloned.txt"
    rmdir "${DOTFILES_EXT_DIR:-$HOME/.local/share/dotfiles-ext}" 2>/dev/null || true
  fi
  [ -s "$BACKUP_DIR/brew-installed.txt" ] || [ -s "$BACKUP_DIR/bin-installed.txt" ] || [ -s "$BACKUP_DIR/pkg-installed.txt" ] || [ -s "$BACKUP_DIR/code-server-installed.txt" ] \
    || info "--purge: install.sh 가 새로 설치한 패키지 기록 없음 (이미 있던 도구는 건드리지 않음)"
else
  info "패키지(starship/eza/bat/zoxide/fzf/fd/플러그인)는 유지 — 제거하려면 --purge"
fi

# ── 6. 백업 디렉터리 정리 ──────────────────────────────────
if [ "$KEEP_BACKUP" = 1 ]; then
  info "$BACKUP_DIR 유지 (--keep-backup)"
else
  rm -rf "$BACKUP_DIR"
fi
rmdir "$HOME/.claude" 2>/dev/null || true   # 비어 있을 때만 제거
rmdir "$HOME/.gemini/antigravity-cli" 2>/dev/null || true
rmdir "$HOME/.gemini" 2>/dev/null || true
rmdir "$HOME/.codex" 2>/dev/null || true
rmdir "$HOME/.config/ai" 2>/dev/null || true
rmdir "$HOME/.config" 2>/dev/null || true
rmdir "$FONT_DIR" 2>/dev/null || true

info "완료. 새 셸을 열면 zsh 기본 상태로 동작한다. 기본 셸을 되돌리려면: chsh -s /bin/bash (또는 원래 셸)"
