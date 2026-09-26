# Gridiron Manager (가칭)

Football Manager 스타일의 NFL 미식축구 매니지먼트 시뮬레이션 게임입니다.
사용자는 단장 겸 감독으로 로스터·뎁스차트·전술·부상을 관리하고, 경기는 플레이 단위로 자동 시뮬레이션됩니다.

- 기획 문서: [docs/PRD.md](docs/PRD.md)
- 경기 엔진 설계: [docs/ENGINE_DESIGN.md](docs/ENGINE_DESIGN.md) (전술 궁합·예측 가능성, 실측 근거)
- 실측 스크립트: `tools/research/` (nflverse 2023–2025 효과 크기 측정, 예측 가능성 모형)
- 상태: PRD v0.4 · 엔진 설계서 v0.1 확정, 구현 착수 전 (다음 단계: M0 스키마 + 실데이터 수집)
- 스택(예정): Python 3.12 · FastAPI · SQLite · HTMX · nflreadpy
- 외부 소스: Football GM 엔진 골격 포팅, nflverse 데이터·모델, nflseedR, nfl4th (docs/PRD.md §13)
- 이 저장소는 포팅 코드의 라이선스 조건 때문에 비공개로 유지합니다.
