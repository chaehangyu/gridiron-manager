# 진행 상황 · 인계 메모

새 세션은 `CLAUDE.md` → 이 파일 → 필요한 PRD 절 순서로 읽고 이어서 작업한다.

## 마일스톤
| 단계 | 상태 | 비고 |
|------|------|------|
| M0–M4 | ✅ (main) | 데이터·엔진·능력치·전술. M4 검증 T5·T6 미달은 M7 보정 과제 |
| M5 시즌 + 부상 + 운영 | ✅ (작업 브랜치) | 하위 단계는 아래 |
| M6 웹 UI (HTMX) | 다음 | S1–S16 |
| M7 폴리싱 | 대기 | 리포트·어워드·엔진 보정(T1·T5·T6) |

## M5 하위 단계
- [x] **M5a 시즌 구조** — `gridiron/season/standings.py`(공식 타이브레이커·시드·플레이오프 대진·드래프트 순서), `season/runner.py`(경기·주 마감·라운드 생성·시즌 종료), CLI `sim-season`, `standings`. 2021–2025 실제 와일드카드 대진 5시즌 모두 일치(`tests/test_season.py`).
- [x] **M5b 부상** — `tools/research/injury_rates.py` → `data/baseline/injuries.json`(2021–2025 실측: 포지션별 스냅당 위험, 부위 비중, 부위별 결장 분포, 리포트 밖 중상), `config/injuries.yaml`, `engine/injury.py`(경기 중 발생·진단·경기 중 복귀·긴급 투입), `season/injuries.py`(진단 범위, 주간 리포트·훈련 참여, 회복, 복귀전 감각 페널티, 재부상 기간, 뇌진탕 반복, IR 자동 등재·복귀 지정), CLI `injuries`. `tools/check_injuries.py 2`: 2.20건/팀경기(실측 2.21), 결장 0/1–3/4–7/8+ = .425/.443/.068/.065 (실측 .424/.457/.069/.050+중상). 세이브 스키마 v2(InjuryRow 확장, PlayerStateRow).
  - 남은 것: 부상 선수 훈련 효과 감소(F11-1d)는 선수 단위 숙련도(M5e)와 함께.
- [x] **M5c 로스터 운영** — `season/roster.py`: 경기 당일 48인(포지션 최소 인원 → PR), FA 영입(53인·PS 한도)·방출·승격·강등, 경기당 임시 승격 2명·선수당 3회, FA 풀 부족 시 대체 선수 생성(GEN-), 자동 관리(AI 팀 + `Team.auto_roster`인 사용자 팀: 성적 나쁜 팀부터 FA 선점, 필수 포지션 부족 시 잉여 방출 후 영입). 거래는 TransactionRow. CLI `roster`, `fa`. 엔진 명단은 `gameday_actives`.
- [x] **M5d 구단주** — `season/owner.py`: 엔진으로 정규시즌 2회 → 파워 레이팅(릿지, 잔차 SD) → 200시즌 몬테카를로(타이브레이커·플레이오프, 레이팅 불확실성 포함) → 등급·주 목표(달성 확률 ≥50%인 가장 높은 목표, 아니면 40% 분위 승수)·보조 목표 2개, 경기별 신뢰도(예상 승률 대비), 주간 진행, 경고 2회 후 해고, 시즌 말 A–F, 인박스. 세이브: `__owner__` 상태 + Owner*Row. CLI `owner`(`--firing off` 샌드박스), `new-game`에서 계산(약 1분, `--quick`이면 첫 경기 때). `tools/check_owner.py 3`: 예상 vs 실제 승수 상관 0.80, ±1SD 포함 0.69, 경기 승률 보정 3%p 이내, 주 목표 달성률 0.62–0.70. 테스트는 `GRIDIRON_OWNER=off`로 엔진 계산을 건너뛴다.
  - 엔진 경기 득실차 잔차 SD 10.8 (실제 NFL ≈13.5): 엔진 경기가 실제보다 덜 무작위 → M7 보정 후보.
- [x] **M5e 스카우팅·역할·문서** — `season/knowledge.py`(파악도 기본 20–40, 경기 +20, 스카우트 +25/포지션 +10, 매주 +1, 고정 오차 범위, 숨김 능력치 4주 후 코멘트), `ratings/roles.py` + `config/roles.yaml`(역할 평가), CLI `player`, `scout`. PRD 상태 표기 전면 갱신.

## M5에서 남긴 것 (M6·M7 또는 Post-MVP)
- F3-4 로테이션 설정, F3-5 퍼스넬 패키지별 배치, F11-1c 그룹별 강도, F11-1d 부상 선수 훈련 효과, F11-3d·선수 단위 숙련도, F8-2 코치 아키타입, F13-8 전술 변화 감지, F2-6b 실제 사용 패턴 기반 역할.
- 엔진: 경기 득실차 잔차 SD 10.8 (실제 ≈13.5) — M7 보정 때 T1·T5·T6과 함께 본다.

## M6 시작 메모
- UI는 CLI 명령이 하는 일을 그대로 화면으로: `cli.py`, `cli_tactics.py`, `cli_season.py`의 각 cmd_* 가 화면 하나에 대응 (S2 홈=owner 인박스+다음 경기, S3=roster/fa, S4=player, S5 뎁스차트, S6=tactics, S7=gameplan, S8 매치 센터=sim-game --pbp, S10=standings, S13=injuries, S15=owner, S16=scout).
- 진행 로직은 `season/runner.py`(play_game, sim_week, finish_week)를 그대로 호출하면 된다.

## 메모
- 시즌 진행 훅: 주 시작 `weekly.prepare_week`, 경기 후 `weekly.after_game`, 주 마감 `runner.finish_week`. M5b–d는 여기에 붙인다.
- 실제 리그 한 시즌(정규+플레이오프) CLI 진행 약 2분.
