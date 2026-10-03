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
| M4 전술·학습·훈련 | ✅ | 3계층 전술(철학·상황별·주간 게임플랜)·프리셋, 콜별 능력치 가중치(궁합), 전술 숙련도, 주간 훈련, 경기 중 상대 성향 학습(믿음·대응·읽힘), AI 팀 실측 성향 전술, 스카우팅 리포트. 검증 T1–T9 중 7개 통과, T5·T6 미달 (ENGINE_DESIGN §15) |
| M5 시즌 + 부상 + 운영 | 다음 | 타이브레이커·플레이오프, 부상 관리, 대체 영입, 구단주 목표, 스카우팅 파악도 |

경기 결과는 **실측 결과 모델**(nflverse 2022–2025 약 16만 플레이 기반)로 계산합니다. 1,000경기 리그 평균이 PRD 보정 목표를 모두 만족합니다 (ENGINE_DESIGN §13).
선수 능력치는 **직전 3시즌 실제 기록으로 산출**합니다 (`data/real/2026/ratings.csv`). 같은 방식으로 2022–2024 기록만 써서 2025 시즌을 재현하면
팀 득실차 순위 상관 ρ 0.46, 분산비 0.99로 "직전 시즌 득실차" 기준선(ρ 0.35)보다 낫습니다 (ENGINE_DESIGN §14, M4 엔진 기준 §15).
전술은 경기 결과를 바꿉니다: 선수에게 맞는 스킴(근력형 OL의 갭 런 +0.08 EPA), 숙련도(전환 직후 손해 → 3–4주 회복), 상대의 경기 중 학습(뻔한 팀은 후반 효율 하락).

## 설치

```bash
pip install -e ".[dev]"          # 게임·테스트
pip install -e ".[data]"         # 실데이터 수집이 필요할 때 (nflreadpy)
```

## 사용법

```bash
gridiron fetch-data --season 2026                                  # 실데이터 갱신 (결과는 data/real/2026에 커밋되어 있음)
gridiron new-game --source real --team KC --save saves/career.sqlite
gridiron tactics --save saves/career.sqlite                        # 전술·숙련도·궁합 보기
gridiron tactics --save saves/career.sqlite --preset wide_zone+quarters
gridiron tactics --save saves/career.sqlite --set offense.run_share=0.45 defense.blitz=1.3 predictability.lam=0.5
gridiron tactics --save saves/career.sqlite --situ "3l|opp" pass=0.15 blitz=1.5   # 상황별 성향
gridiron gameplan --save saves/career.sqlite                       # 다음 상대 스카우팅 리포트 (+ --set 이번 주 조정)
gridiron train --save saves/career.sqlite --main familiarity:cov_man --sub opponent --intensity hard
gridiron sim-game --save saves/career.sqlite --pbp                 # 우리 팀 이번 주 경기 + 텍스트 중계 + 전술 리포트
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
python tools/validate_tactics.py all               # 엔진 검증 T1–T9 (M4, 실제 리그, 약 15분)
python tools/calibrate_situations.py 4 1600        # 상황별 결과 보정값 적합 (M4)
python -m gridiron.baseline.tactics_data --season 2025   # 상성표·팀 성향 재생성
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
  tactics/     전술 3계층·프리셋, 숙련도, 주간 훈련, 스카우팅 기록, 전술 궁합
  season/      주간 진행 (훈련 적용 → 경기 → 숙련도·스카우팅·컨디션 갱신)
  data/        nflverse 수집·가공, 실제 리그 로더, 샘플 리그
  db/          세이브 스키마와 저장·불러오기
  baseline/    실측 기준 분포 생성(build)·모델 학습(train_models)·런타임 조회(tables)
  engine/      skeleton(Football GM 포팅), outcome(fbgm 임시 / data 실측), ai(4th down·2점 판단),
               models_ml(EP·WP·xpass), norms·adjust(능력치 표준점수·콜별 가중치), calibration(중심값 측정),
               ai/coordinator(경기 중 믿음·콜 선택·읽힘), outcome/context(경기 컨텍스트), api, commentary
config/        포지션 가중치, 콜별 능력치 가중치(scheme_weights), 리그 규칙·보정 계수
data/real/     가공된 실제 NFL 데이터 (커밋)
data/baseline/ 실측 기준 분포 표·EP·WP·xpass 모델·상성표(payoff)·M4 검증 결과 (커밋)
third_party/   포팅 출처·라이선스
tools/         점검·연구 스크립트
```

데이터 출처: [nflverse](https://github.com/nflverse) (CC-BY 4.0, FTN 데이터 CC-BY-SA 4.0)
