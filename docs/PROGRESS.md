# 진행 상황 · 인계 메모

새 세션은 `CLAUDE.md` → 이 파일 → 필요한 PRD 절 순서로 읽고 이어서 작업한다.

## 마일스톤
| 단계 | 상태 | 비고 |
|------|------|------|
| M0–M4 | ✅ (main) | 데이터·엔진·능력치·전술. M4 검증 T5·T6 미달은 M7 보정 과제 |
| M5 시즌 + 부상 + 운영 | ✅ (main, ead9b31) | 하위 단계는 아래 |
| M6 웹 UI (HTMX) | ✅ (작업 브랜치) | S1–S16, 브라우저로 시즌 완주 확인 |
| M7 폴리싱 | ✅ (작업 브랜치) | 리포트·평점·어워드·프리셋·엔진 보정 → **MVP 완료** |

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

## M6 웹 UI 계획 (완료)
스택(PRD §8.1, D12): FastAPI + Jinja2 + HTMX + Alpine.js, 드래그 앤 드롭 SortableJS, 차트 Chart.js (CDN, 빌드 도구 없음). 의존성은 `pyproject.toml`의 `web` extra(설치됨).
완료 기준(PRD M6): 사용자가 브라우저에서 시즌 1회 완주. 화면 목록은 PRD §6 (S1–S16).

원칙
- 게임 로직은 새로 쓰지 않는다. 화면은 CLI와 같은 함수를 부른다: 진행 `season/runner.py`(play_game·sim_week·finish_week·ensure_owner), 순위 `season/standings.py`, 부상 `season/injuries.py`(report_rows·place_ir·can_activate·activate), 로스터 `season/roster.py`, 구단주 `season/owner.py`, 스카우팅 `season/knowledge.py`, 전술 `tactics/*`(cli_tactics.py 참고), 선수 프로필 로직 `cli_season.cmd_player`.
- CLI 함수 안의 계산(출력 전 데이터 만들기)은 필요하면 `gridiron/web/views.py` 같은 곳으로 뽑아 CLI와 웹이 함께 쓴다.
- 세이브 슬롯: `saves/*.sqlite` (gitignore). 요청마다 `load_league` → 처리 → 저장 함수. 한 사람용 로컬 앱이라 동시성은 신경 쓰지 않는다.
- 실행: `uvicorn gridiron.web.app:app --reload` 또는 CLI `gridiron serve` 추가. 테스트는 FastAPI TestClient(httpx)로 화면별 200·핵심 문구 확인. 화면 확인은 Playwright(크로미움 설치됨)로 스크린샷.
- 엔진 경기 1회 약 0.1초, 한 주 16경기 약 2초, 새 게임 구단주 투영 약 1분 → 긴 작업은 HTMX 진행 표시(폴링 또는 단계별 요청).

하위 단계 (각각 커밋·푸시·이 파일 갱신)
- [x] **M6a 기반** — `gridiron/web/`: `app.py`(앱·필터·`render`·`need_ctx`), `state.py`(슬롯=saves/*.sqlite, 쿠키 `slot`, 수정 시각 캐시, `LOCK`), `jobs.py`(백그라운드 작업 + HTMX 폴링 `/jobs/{id}`), `views.py`(화면용 데이터), `routes/core.py`(S1 `/new`, S2 `/home`, 진행 `/play/{game|week|regular|end}`, S12 `/settings`). 프런트 라이브러리는 `static/vendor/`에 포함(htmx 2.0.4, Alpine 3.14.8, Sortable 1.15.6, Chart.js 4.4.7 — 컨테이너에서 CDN 차단, npm pack으로 받음). 인박스는 새 `NewsRow`(runner가 경기 결과·부상·로스터·구단주 알림 기록). `gridiron serve`. 테스트 `tests/test_web.py`.
  - 스크린샷: `python -m pip install playwright` 후 크로미움 `/opt/pw-browsers/chromium-*/chrome-linux64/chrome`로 확인.
- [x] **M6b 선수단** — `routes/squad.py`: S3 `/roster`(53/PS/IR/FA 탭, 포지션·정렬, 다른 팀 로스터는 파악도 범위, 영입·PS 영입·방출·승격·강등·임시 승격·경기 당일 비활성), S4 `/player/{id}`(`views.player_profile`: 능력치 등급 색상·범위, 포지션별 PR, 역할, 숨김 코멘트, 부상 이력, 시즌 기록), S5 `/depth`(SortableJS 드래그·후보 끌어오기·빼기, JSON 저장 `POST /depth`, `domain.depth.validate_depth` 경고 F3-7, 유닛별 자동 편성 F3-6), S13 `/injuries`(출전 결정·IR 등재·복귀 지정, 리그 부상 리포트). `store.save_depth_chart`.
- [x] **M6c 전술·주간** — `routes/tactics.py`: S6 `/tactics`(프리셋, 공격·수비·예측 가능성·경기 운영 슬라이더, 상황별 성향 8×5 격자, HTMX 실시간 미리보기 `POST /tactics/preview` = 궁합·노출도 추정·경고, 엔진 비교 `POST /tactics/simulate` = 다음 상대와 같은 시드 16경기씩 현재 vs 새 전술 득실), S7 `/gameplan`(스카우팅 리포트·상대 부상·체크한 항목만 덮어쓰는 이번 주 조정), S14 `/training`, S16 `/scout`. `tactics/preview.py`(노출도 추정은 리그 평균 대비 치우침 기반 — 경기 중 실제 노출도와 같은 원리의 근사).
- [x] **M6d 경기·리그** — `routes/league.py` + `web/match.py`: S8·S9 `/match/{id}`(중계 탭: Alpine 재생 — 전체/하이라이트/즉시·속도·일시정지, 스코어보드·필드 바·1st down 선·승률 그래프; 박스스코어 탭(팀·개인, 3rd down); 드라이브 탭; 전술 리포트 탭), `/match/{id}/timeline.json`, S10 `/standings`(디비전·컨퍼런스 시드·플레이오프 대진·주차별 일정·우리 팀 일정), S11 `/stats`(리더보드·팀 순위), S15 `/owner`(목표 달성 여부, 신뢰도 그래프, 메시지, 경기별 변화). 우리 팀 경기는 clock 이벤트(다운·볼 위치·점수 `pts`·승률)까지 PlayRow에 저장하고, 끝에 `wpSeries`·`tacticsReport` 이벤트를 붙인다.
  - 브라우저 완주 확인 (Playwright, 실제 리그 BUF): 새 게임+구단주 투영 55초 → 우리 경기 중계 → "시즌 끝까지" 134초 → 슈퍼볼까지, 페이지 오류 0.
  - 고친 것: 진행 작업 중에도 화면 읽기는 막히지 않게(캐시 잠금 분리, 작업 중엔 직전 리그 표시), 작업 중 POST는 진행 화면으로(미들웨어), 새 게임 생성 중 빈 세이브 읽기 방지.
  - 구단주 조정: 신뢰도 K 12→8, 주간 진행률 ±1→±0.5, 평가 = 주 목표 40 + 보조 각 15 + 신뢰도×0.3, 경고는 3주 간격, 승률 5할 이상이면 시즌 중 해고 없음 (11–6 디비전 우승팀이 해고되던 문제).

## M7 하위 단계
- [x] **M7a 경기 리포트** — `season/game_report.py`: 플레이별 EPA(clock 이벤트 EP 차이, TD 7·FG 3·세이프티 2), 팀별 공격 패밀리·상대 커버리지별 시도·성공률·EPA, 쿼터별 효율(F6-5); 선수 평점 10점 만점(6.0 평균, 9+ 약 2%, F6-6); `derive`(태클·FG 합계 — 박스 원본은 defTckSolo/Ast, fg30… 로 나뉨, 리그 통계 태클·FG 리더보드 수정). 매치 센터 "선수 평점" 탭·경기 MVP·전술 리포트 탭 확장(쿼터 그래프).
- [x] **M7b 시즌 어워드·올프로** — `season/awards.py`: 경기별 평점의 Σ(평점−6) (10경기 이상), MVP는 팀 승수×0.8 + QB ×1.6, OPOY·DPOY·신인상(경력 0년), 올프로 1·2팀. 시즌 종료 때 인박스, 웹 `/awards`(시즌 중엔 현재 레이스), CLI `awards`.
  - 발견: 실제 리그 시즌에서 리시버·RB 기록이 비현실적 (TE 158리셉션, WR 2,209야드, RB 1,894야드) → M7c에서 타깃·볼 캐리 분배 보정.
- [x] **M7c 엔진 보정** (ENGINE_DESIGN §16) — 그날 경기력 `game_form`(잔차 SD 11.5→13.4, 일관성 능력치 반영), 사용량 `usage`(타깃 능력 지수 0.4, RB2 20%·RB3 3% 로테이션: 1번 타깃 0.24, RB1 캐리 0.56), 패스 수준 `pass_level` 0.03·`int_factor` 0.88(실측 2023–2025 Y/A 7.0·INT 2.2%에 맞춤). 검증 T1–T9 중 8개 통과(T6 새로 통과, T5 평평 — §16.4), 2025 재현 ρ 0.45·분산비 0.93, 구단주 ±1SD 0.73(불확실성 ×0.6). 도구 `tools/check_variance.py`, `tools/check_usage.py`. `reproduction.json`·`m7_validation.json` 갱신.
- [x] **M7d 마무리** — 사용자 전술 프리셋(F4-7c: 웹 `/tactics/user-preset`, CLI `tactics --save-preset`·`--preset my:이름`), CLI 경기 결과에 패밀리별 EPA·평점, 능력치 파이프라인 테스트는 scipy 없으면 건너뜀, 문서·PRD 상태 갱신, 릴리즈 노트(`docs/RELEASE_NOTES.md`).

## MVP 이후 (남은 것 · Post-MVP)
- MVP에서 남긴 것: 패스 TD가 실측보다 ≈15% 많음(팀당 1.66 vs 1.45 — 시즌 리더 TD 45+, 레드존 패스 보정 `pass_fz.red` 재검토), T5 런 비율 곡선이 평평(ENGINE_DESIGN §16.4), xpass 구간별 드롭백 EPA 0.02–0.04 낮음, 난이도(F9-3·F9-4), 슬롯 역할 지정(F2-6c), 로테이션(F3-4)·퍼스넬 배치(F3-5), 코치 아키타입(F8-2), 전술 변화 감지(F13-8), 선수 단위 숙련도(F11-3d)·부상 선수 훈련 효과(F11-1d), 사용자 시즌 다년 진행.
- Post-MVP 로드맵(PRD): 오프시즌(성장·노화·드래프트·FA·캡·계약), 경기 중 직접 플레이 콜, 플레이북 에디터, 코칭·의료 스태프, 2D 필드 애니메이션, 사기·미디어, 트레이드·웨이버.

## 웹 실행
```bash
gridiron serve                 # http://127.0.0.1:8000 (세이브는 saves/, --saves로 변경)
```
화면 확인: `python -m pip install playwright` 후 크로미움 `/opt/pw-browsers/chromium-*/chrome-linux64/chrome`.

## 새 세션 시작 문구 (복사해서 사용)
> CLAUDE.md와 docs/PROGRESS.md를 읽고 M6(웹 UI)를 진행해줘. PROGRESS.md의 M6a → M6b → M6c → M6d 순서로, 하위 단계마다 테스트·커밋·푸시하고 PROGRESS.md를 갱신해줘. 컨텍스트가 부족해지면 현재 단계까지 정리해서 커밋하고 다음 세션용 메모를 남겨줘.

## 메모
- 시즌 진행 훅: 주 시작 `weekly.prepare_week`, 경기 후 `weekly.after_game`, 주 마감 `runner.finish_week`. M5b–d는 여기에 붙인다.
- 실제 리그 한 시즌(정규+플레이오프) CLI 진행 약 2분.
