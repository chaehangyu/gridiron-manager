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
| M2 기준 분포 + 판단 모델 | 다음 | 실측 결과 분포, EP·WP·xpass, nfl4th |

현재 경기 결과는 **임시 결과 모델**(Football GM 공식)이고, 실제 선수 능력치는 **임시 값**(뎁스차트 순번·드래프트·경력 기반)입니다.
각각 M2와 M3에서 실측 기반으로 교체합니다.

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
python -m pytest                          # 테스트 (원본 Football GM 테스트 포팅 포함)
python tools/check_engine_stats.py 500    # 리그 평균 통계 점검 (PRD §8.4)
python tools/research/measure_effects.py  # 실측 효과 크기 (ENGINE_DESIGN §2)
```

## 폴더

```
gridiron/
  domain/      포지션, 능력치, 선수·팀·리그 모델, 뎁스차트
  ratings/     포지션 평가(PR), 임시 능력치 생성기
  data/        nflverse 수집·가공, 실제 리그 로더, 샘플 리그
  db/          세이브 스키마와 저장·불러오기
  engine/      skeleton(Football GM 포팅), outcome(결과 모델), adapter, api, commentary
config/        포지션 가중치, 리그 규칙·보정 계수
data/real/     가공된 실제 NFL 데이터 (커밋)
third_party/   포팅 출처·라이선스
tools/         점검·연구 스크립트
```

데이터 출처: [nflverse](https://github.com/nflverse) (CC-BY 4.0, FTN 데이터 CC-BY-SA 4.0)
