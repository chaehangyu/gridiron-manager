# Gridiron Manager — 작업 안내 (새 세션은 이 파일부터)

Football Manager 스타일 NFL 매니지먼트 시뮬레이션. 사용자는 단장 겸 감독. 개인 비상업 용도(저작권 신경 쓰지 않음, 외부 소스 자유 사용).
사용자와는 **한국어**로 대화한다. 문서·주석·CLI 출력도 한국어.

## 문서
- `docs/PRD.md` — 요구사항(F1–F13), 화면(S1–S16), 마일스톤 M0–M7(§ 마일스톤 표). 상태 표기: ✅ 완료, 🟡 일부, ⏳ 대기.
- `docs/ENGINE_DESIGN.md` — 엔진 설계·보정 근거·검증 결과(§13 리그 통계, §14 재현, §15 M4 검증).
- `docs/PROGRESS.md` — **진행 상황·다음 할 일·인계 메모** (마일스톤마다 갱신).

## 규칙
- 작업 브랜치 `claude/football-sim-game-prd-qmn9sw`. 마일스톤 완료 후 사용자가 요청하면 `main`에 fast-forward 병합. PR은 요청 없으면 만들지 않는다.
- 커밋 메시지에 모델 이름을 넣지 않는다.
- 단계마다 `python -m pytest -q` 통과 확인 후 커밋·푸시. 큰 마일스톤은 하위 단계(M5a, M5b …)로 나눠 커밋한다.
- 보정값은 코드에 박지 말고 `config/*.yaml`; 실측 기반 데이터는 `data/baseline`·`data/real`에 커밋. `data/raw`(nflverse 캐시)는 gitignore.
- 엔진 결과를 바꾸는 변경 후에는 `python tools/check_engine_stats.py 300`으로 리그 평균(팀당 득점 ~21–23, Y/A ~7, 완성률 ~65%)을 확인.

## 구조 요약
```
gridiron/domain    Player/Team/League/ScheduledGame, 포지션·능력치(1–20), 뎁스차트
gridiron/engine    api.simulate(league, game, seed, user_team) → GameOutcome
                   skeleton(FBGM 포팅 경기 골격), outcome/data_model(실측 결과 모델), ai/coordinator(경기 중 학습)
gridiron/tactics   전술 3계층·프리셋, 숙련도, 훈련, 스카우팅, 궁합
gridiron/season    weekly(주간 진행), M5부터 시즌 구조(타이브레이커·플레이오프)·부상·로스터·구단주
gridiron/db        SQLite 세이브(schema.py는 다년 대비 테이블이 이미 정의됨: Injury, Transaction, Owner*, Scout*)
gridiron/cli*.py   명령줄 (M6 웹 UI 전까지 유일한 UI)
tools/             보정·검증 스크립트
```

## 자주 쓰는 명령
```bash
pip install -e ".[dev]"
python -m pytest -q
gridiron new-game --source real --team KC --save saves/career.sqlite
gridiron sim-week --save saves/career.sqlite
```
