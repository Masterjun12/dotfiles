# 3사 설정의 공개 가능한 기준값

현재 사용 중인 값 중 다른 머신에서 재사용 가능한 설정만 분리했다.
인증, 서버별 MCP, 신뢰 경로, 권한 allow 목록, 훅 trusted_hash, 대화·메모리는 포함하지 않는다.

기존 설치는 statusLine과 이 저장소의 훅만 병합한다. 나머지 설정은 템플릿으로 제공한다.
`agy.json`의 `toolPermission: always-proceed`는 현재 선택값을 기록한 것으로 자동 적용하지 않는다.
Codex 설정은 `config.toml`의 원하는 키만 복사하고 기존 키와 중복되지 않도록 확인한다.
Claude에는 별도 모델 고정값이 없어 기본 모델 선택을 유지한다.
Gemini CLI의 사설 MCP와 인증은 이 저장소에서 배포하지 않는다.
