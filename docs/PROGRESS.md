# 진행 상황 · 인계 메모

새 세션은 `CLAUDE.md` → 이 파일 → 필요한 PRD 절 순서로 읽고 이어서 작업한다.

## 마일스톤
| 단계 | 상태 | 비고 |
|------|------|------|
| M0–M4 | ✅ (main) | 데이터·엔진·능력치·전술. M4 검증 T5·T6 미달은 M7 보정 과제 |
| M5 시즌 + 부상 + 운영 | 진행 중 | 하위 단계는 아래 |
| M6 웹 UI (HTMX) | 대기 | S1–S16 |
| M7 폴리싱 | 대기 | 리포트·어워드·엔진 보정(T1·T5·T6) |

## M5 하위 단계
- [x] **M5a 시즌 구조** — `gridiron/season/standings.py`(공식 타이브레이커·시드·플레이오프 대진·드래프트 순서), `season/runner.py`(경기·주 마감·라운드 생성·시즌 종료), CLI `sim-season`, `standings`. 2021–2025 실제 와일드카드 대진 5시즌 모두 일치(`tests/test_season.py`).
- [x] **M5b 부상** — `tools/research/injury_rates.py` → `data/baseline/injuries.json`(2021–2025 실측: 포지션별 스냅당 위험, 부위 비중, 부위별 결장 분포, 리포트 밖 중상), `config/injuries.yaml`, `engine/injury.py`(경기 중 발생·진단·경기 중 복귀·긴급 투입), `season/injuries.py`(진단 범위, 주간 리포트·훈련 참여, 회복, 복귀전 감각 페널티, 재부상 기간, 뇌진탕 반복, IR 자동 등재·복귀 지정), CLI `injuries`. `tools/check_injuries.py 2`: 2.20건/팀경기(실측 2.21), 결장 0/1–3/4–7/8+ = .425/.443/.068/.065 (실측 .424/.457/.069/.050+중상). 세이브 스키마 v2(InjuryRow 확장, PlayerStateRow).
  - 남은 것: 부상 선수 훈련 효과 감소(F11-1d)는 선수 단위 숙련도(M5e)와 함께.
- [ ] **M5c 로스터 운영** — 53/PS16/경기일 48, FA 영입·방출·PS 승격(TransactionRow), AI 대체 영입.
- [ ] **M5d 구단주** — 사전 시즌 시뮬 → 기대 승수·목표, 경기별 신뢰도, 시즌 말 평가.
- [ ] **M5e 스카우팅 파악도·역할·문서** — ScoutKnowledgeRow, 범위 표시, 선수 역할(F2-6), PRD 상태 갱신.

## 메모
- 시즌 진행 훅: 주 시작 `weekly.prepare_week`, 경기 후 `weekly.after_game`, 주 마감 `runner.finish_week`. M5b–d는 여기에 붙인다.
- 실제 리그 한 시즌(정규+플레이오프) CLI 진행 약 2분.
