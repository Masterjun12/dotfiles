#!/bin/bash
# Antigravity CLI (agy) & Claude Code statusLine script
input=$(cat)
echo "$input" > /tmp/agy_statusline_payload.json 2>/dev/null

RESET="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
SEP="${DIM} │ ${RESET}"

FG_PATH="\033[38;5;110m"
FG_GIT_CLEAN="\033[38;5;108m"
FG_GIT_DIRTY="\033[38;5;179m"
FG_MODEL="\033[38;5;73m"
FG_OK="\033[38;5;108m"
FG_WARN="\033[38;5;179m"
FG_CRIT="\033[38;5;167m"
FG_COST="\033[38;5;144m"
FG_MUTE="\033[38;5;244m"

IFS=$'\x1f' read -r cwd model effort thinking fast_mode \
  used_pct in_tok out_tok win_size exceeds \
  cost dur_ms api_ms lines_add lines_del \
  cache_warm cache_hit five five_reset week week_reset \
  style version quota_summary <<EOF
$(printf '%s' "$input" | jq -r '
  def s: if . == null then "" else tostring end;
  def format_quota:
    if .quota != null then
      if (.quota | type) == "object" then
        if .quota["gemini-5h"] != null then
          "한도: 5h \((.quota["gemini-5h"].remaining_fraction * 100) | round)% · 주간 \((.quota["gemini-weekly"].remaining_fraction * 100) | round)%"
        elif .quota["3p-5h"] != null then
          "한도: 5h \((.quota["3p-5h"].remaining_fraction * 100) | round)% · 주간 \((.quota["3p-weekly"].remaining_fraction * 100) | round)%"
        else
          ([ .quota | to_entries[] |
            (if .value.remaining_fraction != null then
              "\(.key) 잔여 \((.value.remaining_fraction * 100) | round)%"
            elif .value.remaining_percentage != null then
              "\(.key) 잔여 \(.value.remaining_percentage | round)%"
            elif .value.used_percentage != null then
              "\(.key) 잔여 \(100 - (.value.used_percentage | round))%"
            else
              empty
            end)
          ] | join("  "))
        end
      else
        "한도: \(.quota)%"
      end
    elif .rate_limits != null then
      ([
        (if .rate_limits.five_hour.used_percentage != null then "5h 잔여 \(100 - (.rate_limits.five_hour.used_percentage | round))%" else empty end),
        (if .rate_limits.seven_day.used_percentage != null then "7d 잔여 \(100 - (.rate_limits.seven_day.used_percentage | round))%" else empty end)
      ] | join("  "))
    else
      ""
    end;
  [ ((.workspace.current_dir // .cwd) | s),
    ((.model.display_name // .model.id // .model) | s),
    (.effort.level | s),
    (if .thinking.enabled == true then "1" else "" end),
    (if .fast_mode == true then "1" else "" end),
    ((.context_window.used_percentage // .context.used_percentage) | s),
    ((.context_window.total_input_tokens // .context.total_input_tokens // .context.input_tokens) | s),
    ((.context_window.total_output_tokens // .context.total_output_tokens // .context.output_tokens) | s),
    ((.context_window.context_window_size // .context.context_window_size) | s),
    (if .exceeds_200k_tokens == true then "1" else "" end),
    (.cost.total_cost_usd | s),
    (.cost.total_duration_ms | s),
    (.cost.total_api_duration_ms | s),
    (.cost.total_lines_added | s),
    (.cost.total_lines_removed | s),
    (if .prompt_cache.warm == true then "1" else "" end),
    (.prompt_cache.hit_ratio | s),
    (.rate_limits.five_hour.used_percentage | s),
    (.rate_limits.five_hour.resets_at | s),
    (.rate_limits.seven_day.used_percentage | s),
    (.rate_limits.seven_day.resets_at | s),
    (.output_style.name | s),
    (.version | s),
    (format_quota | s) ] | join("\u001f")' 2>/dev/null)
EOF

int() { [ -n "$1" ] && printf "%.0f" "$1" 2>/dev/null; }
k() {
  local n
  [ -n "$1" ] || return
  n=$(int "$1")
  if [ "$n" -ge 1000000 ]; then printf "%dM" $(( n / 1000000 ))
  elif [ "$n" -ge 1000 ]; then printf "%dk" $(( n / 1000 ))
  else printf "%d" "$n"; fi
}
hhmm() {
  [ -n "$1" ] || return
  date -r "$1" +%H:%M 2>/dev/null || date -d "@$1" +%H:%M 2>/dev/null
}
dur() {
  local ms="${1:-}" s
  [ -n "$ms" ] || return
  s=$(( $(int "$ms") / 1000 ))
  if   [ "$s" -ge 3600 ]; then printf "%dh%02dm" $(( s / 3600 )) $(( s % 3600 / 60 ))
  elif [ "$s" -ge 60 ];   then printf "%dm" $(( s / 60 ))
  else printf "%ds" "$s"; fi
}

# 1행: 경로(남은 용량) │ 모델명 │ [바] 잔여 % (입력/한도)
dir_name=$(basename "$cwd" 2>/dev/null)
[ -z "$dir_name" ] && dir_name="?"
path_part="${FG_PATH}${BOLD}${dir_name}${RESET}"

disk_avail=""
target_dir="${cwd:-.}"
if [ -d "$target_dir" ]; then
  disk_avail=$(df -hP "$target_dir" 2>/dev/null | awk 'NR==2 {print $4}')
fi
if [ -n "$disk_avail" ]; then
  path_part="${path_part} ${FG_MUTE}(남은 ${disk_avail})${RESET}"
fi

model_part=""
if [ -n "$model" ]; then
  m_short=$(echo "$model" | sed -E 's/ \((Medium|High|Low)\)//g')
  model_part="${SEP}${FG_MODEL}${m_short}${RESET}"
fi

# 컨텍스트 창 기본 크기 및 잔여율 계산
[ -z "$in_tok" ] && in_tok="0"
if [ -z "$win_size" ] || [ "$(int "$win_size")" -le 0 ] 2>/dev/null; then
  case "$model" in
    *[Ff]lash*|*[Gg]emini*|*[Pp]ro*) win_size=1048576 ;;
    *[Cc]laude*|*[Ss]onnet*|*[Oo]pus*) win_size=200000 ;;
    *) win_size=1048576 ;;
  esac
fi

if [ -n "$used_pct" ]; then
  used_int=$(int "$used_pct")
else
  used_int=$(( $(int "$in_tok") * 100 / $(int "$win_size") ))
fi
[ "$used_int" -gt 100 ] && used_int=100
rem_int=$(( 100 - used_int ))
[ "$rem_int" -lt 0 ] && rem_int=0

if [ "$used_int" -ge 80 ] || [ -n "$exceeds" ]; then
  ctx_color="$FG_CRIT"
elif [ "$used_int" -ge 60 ]; then
  ctx_color="$FG_WARN"
else
  ctx_color="$FG_OK"
fi

bar_width=10
filled=$(( used_int * bar_width / 100 ))
empty=$(( bar_width - filled ))
bar=""
for ((i=0; i<filled; i++)); do bar="${bar}█"; done
for ((i=0; i<empty; i++)); do bar="${bar}░"; done

ctx_part="${SEP}${ctx_color}[${bar}] 잔여 ${rem_int}%${RESET} ${FG_MUTE}($(k "$in_tok")/$(k "$win_size"))${RESET}"
[ -n "$out_tok" ] && [ "$(int "$out_tok")" -gt 0 ] 2>/dev/null && ctx_part="${ctx_part}${FG_MUTE} ↑$(k "$out_tok")${RESET}"

# 2행: Git 브랜치 │ 한도 잔여 % │ 비용/소요시간 │ 캐시
git_part=""
if [ -n "$cwd" ] && git -C "$cwd" --no-optional-locks rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch=$(git -C "$cwd" --no-optional-locks symbolic-ref --short -q HEAD 2>/dev/null || git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null)
  if [ -n "$branch" ]; then
    if [ -n "$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null)" ]; then
      git_part="${FG_GIT_DIRTY} ${branch} ●${RESET}"
    else
      git_part="${FG_GIT_CLEAN} ${branch}${RESET}"
    fi
  fi
fi

rate_part=""
if [ -n "$quota_summary" ]; then
  rate_part="${FG_MUTE}${quota_summary}${RESET}"
elif [ -n "$five" ] || [ -n "$week" ]; then
  rl=""
  if [ -n "$five" ]; then
    rl="5h 잔여 $(( 100 - $(int "$five") ))%"
    r=$(hhmm "$five_reset"); [ -n "$r" ] && rl="${rl}⮺${r}"
  fi
  if [ -n "$week" ]; then
    w="7d 잔여 $(( 100 - $(int "$week") ))%"
    r=$(hhmm "$week_reset"); [ -n "$r" ] && w="${w}⮺${r}"
    [ -n "$rl" ] && rl="${rl}  ${w}" || rl="$w"
  fi
  rate_part="${FG_MUTE}${rl}${RESET}"
else
  rate_part="${FG_MUTE}한도 잔여: ${rem_int}%${RESET}"
fi

cost_part=""
if [ -n "$cost" ]; then
  cost_part="${FG_COST}\$$(printf "%.2f" "$cost")${RESET}"
  t=$(dur "$dur_ms")
  a=$(dur "$api_ms")
  [ -n "$t" ] && cost_part="${cost_part} ${FG_MUTE}${t}${RESET}"
  [ -n "$a" ] && cost_part="${cost_part}${FG_MUTE}(api ${a})${RESET}"
fi

diff_part=""
if [ -n "$lines_add" ] || [ -n "$lines_del" ]; then
  if [ "$(int "${lines_add:-0}")" -ne 0 ] || [ "$(int "${lines_del:-0}")" -ne 0 ]; then
    diff_part="${FG_OK}+${lines_add:-0}${RESET}${FG_MUTE}/${RESET}${FG_CRIT}-${lines_del:-0}${RESET}"
  fi
fi

cache_part=""
if [ -n "$cache_hit" ]; then
  hit=$(printf "%.0f" "$(echo "$cache_hit" | awk '{print $1*100}')" 2>/dev/null)
  if [ -n "$hit" ]; then
    [ -n "$cache_warm" ] && cache_color="$FG_OK" || cache_color="$FG_MUTE"
    cache_part="${FG_MUTE}cache ${RESET}${cache_color}${hit}%${RESET}"
  fi
fi

style_part=""
[ -n "$style" ] && style_part="${FG_MUTE}${style}${RESET}"
ver_part=""
[ -n "$version" ] && ver_part="${FG_MUTE}v${version}${RESET}"

line2=""
for seg in "$git_part" "$rate_part" "$cost_part" "$diff_part" "$cache_part" "$style_part" "$ver_part"; do
  [ -n "$seg" ] || continue
  [ -n "$line2" ] && line2="${line2}${SEP}${seg}" || line2="$seg"
done

printf "%b%b%b\n" "$path_part" "$model_part" "$ctx_part"
[ -n "$line2" ] && printf "%b\n" "$line2"
exit 0
