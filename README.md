# Gridiron Manager (가칭)

Football Manager 스타일의 NFL 미식축구 매니지먼트 시뮬레이션 게임입니다.
사용자는 단장 겸 감독으로 로스터·뎁스차트·전술·부상을 관리하고, 경기는 플레이 단위로 자동 시뮬레이션됩니다.

- 기획 문서: [docs/PRD.md](docs/PRD.md)
- 경기 엔진 설계: [docs/ENGINE_DESIGN.md](docs/ENGINE_DESIGN.md)
- 외부 소스: Football GM 엔진 골격 포팅(`third_party/zengm/SOURCE.md`), nflverse 데이터·모델, nflseedR, nfl4th
- 이 저장소는 포팅 코드의 라이선스 조건 때문에 **비공개로 유지**합니다.

## 진행 상황

| 단계 | 상태 | 내용 |
|------|------|------|
| M0 기반 + 데이터 | ✅ | 도메인 모델, 1–20 능력치, 세이브 스키마(다년 대비), 2026 실데이터(로스터·뎁스차트·일정), 가상 샘플 리그 |
| M1 엔진 골격 | ✅ | Football GM 경기 엔진 포팅 + 원본 테스트 포팅, 한국어 텍스트 중계, 명령줄 도구 |
| M2 기준 분포 + 판단 모델 | ✅ | 실측 결과 모델(압박→깊이→결과, 박스별 런, 특수팀), EP·WP·xpass 재학습, nfl4th 방식 4th down·2점 판단 |
| M3 능력치 + 보정 | ✅ | 실측 지표 50여 개 + 명단 기반 릿지 회귀 → 경험적 베이즈 수축 → 1–20 능력치, F2-5d 분포 자동 보정, β 적합, 2025 재현 테스트 통과 |
| M4 전술·역할·학습·훈련 | 다음 | 3계층 전술, 콜별 능력치 가중치, 숙련도, 주간 훈련, 예측 가능성 학습 |

경기 결과는 **실측 결과 모델**(nflverse 2022–2025 약 16만 플레이 기반)로 계산합니다. 1,000경기 리그 평균이 PRD 보정 목표를 모두 만족합니다 (ENGINE_DESIGN §13).
선수 능력치는 **직전 3시즌 실제 기록으로 산출**합니다 (`data/real/2026/ratings.csv`). 같은 방식으로 2022–2024 기록만 써서 2025 시즌을 재현하면
팀 득실차 순위 상관 ρ 0.46, 분산비 0.97, 경기 적중률 60.9%로, "직전 시즌 득실차" 기준선(ρ 0.35, 58.3%)보다 낫습니다 (ENGINE_DESIGN §14).

## 설치

```bash
pip install -e ".[dev]"          # 게임·테스트
pip install -e ".[data]"         # 실데이터 수집이 필요할 때 (nflreadpy)
```

## 사용법

```bash
gridiron fetch-data --season 2026                                  # 실데이터 갱신 (결과는 data/real/2026에 커밋되어 있음)
gridiron new-game --source real --team KC --save saves/career.sqlite
gridiron sim-game --save saves/career.sqlite --pbp                 # 우리 팀 이번 주 경기 + 텍스트 중계
gridiron sim-week --save saves/career.sqlite                       # 이번 주 나머지 경기
gridiron standings --save saves/career.sqlite
gridiron quick --home KC --away BUF --pbp                          # 저장 없이 한 경기
```

## 개발

```bash
python -m pytest                                  # 테스트 (원본 Football GM 테스트 포팅 포함)
python tools/check_engine_stats.py 1000           # 리그 평균 통계 점검 (PRD §8.4)
python tools/check_reproduction.py 300            # 실측 조건부 구조 재현 점검
python tools/calibrate_centers.py 400 real:2026    # 평균 매치업 중심 보정값 측정 (sample이면 샘플 리그용)
python tools/reproduce_season.py --season 2025     # 시즌 재현 테스트 + β 배율 적합 (M3)
python tools/research/measure_effects.py          # 실측 효과 크기 (ENGINE_DESIGN §2)

# 기준 분포·모델 재생성 (새 시즌 데이터가 나오면; pandas·scikit-learn 필요, 결과는 data/baseline에 커밋)
python -m gridiron.baseline.build --cache data/raw
python -m gridiron.baseline.train_models --cache data/raw

# 실측 능력치 산출 (결과는 data/real/<시즌>/ratings.csv에 커밋; 수동 보정은 ratings_overrides.csv)
python -m gridiron.ratings.derive --season 2026    # 2023–2025 기록 → 2026 능력치
python -m gridiron.ratings.derive --season 2025    # 2022–2024 기록 → 2025 능력치 (재현 테스트용)
```

## 폴더

```
gridiron/
  domain/      포지션, 능력치, 선수·팀·리그 모델, 뎁스차트
  ratings/     포지션 평가(PR), 임시 능력치 생성기, derive(실측 능력치 파이프라인: 지표·RAPM·수축·신체·의료)
  data/        nflverse 수집·가공, 실제 리그 로더, 샘플 리그
  db/          세이브 스키마와 저장·불러오기
  baseline/    실측 기준 분포 생성(build)·모델 학습(train_models)·런타임 조회(tables)
  engine/      skeleton(Football GM 포팅), outcome(fbgm 임시 / data 실측), ai(4th down·2점 판단),
               models_ml(EP·WP·xpass), norms·adjust(능력치 표준점수), calibration(중심값 측정), api, commentary
config/        포지션 가중치, 리그 규칙·보정 계수
data/real/     가공된 실제 NFL 데이터 (커밋)
data/baseline/ 실측 기준 분포 표·EP·WP·xpass 모델 (커밋)
third_party/   포팅 출처·라이선스
tools/         점검·연구 스크립트
```

데이터 출처: [nflverse](https://github.com/nflverse) (CC-BY 4.0, FTN 데이터 CC-BY-SA 4.0)
