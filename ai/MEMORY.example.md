# Global Shared Agent Memory Template (AGY, Claude, Codex)

모든 코딩 에이전트(Google Antigravity, Claude Code, OpenAI Codex)가 공통으로 참조하는 전역 시스템 사실 및 환경 기억 템플릿입니다.

## 1. 서버 인프라 및 주요 접속 정보
- **호스트 이름**: `<hostname>`
- **VPN / 사설 IP**: `<private-ip>`
- **공용 PostgreSQL**: `localhost:5432`
- **공용 Redis**: `localhost:6379`

## 2. 에이전트 환경 및 도구 설정 배치
- **공용 하네스 및 규칙 원본 (SSOT)**:
  - `~/.config/ai/AGENTS.md`가 AGY(`~/.gemini/AGENTS.md`), Claude(`~/.claude/CLAUDE.md`), Codex(`~/.codex/AGENTS.md`)의 단일 원본임.
- **공용 스킬 디렉터리**:
  - `~/.agents/skills`
