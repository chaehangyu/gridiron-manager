# Football GM (ZenGM) 포팅 출처

- 저장소: https://github.com/zengm-games/zengm
- 기준 커밋: `73727b86720a331ee39c2db0fc1c6445339abdd2` (2026-09-26)
- 라이선스: 같은 폴더의 `LICENSE.md` 전문. 오픈소스가 아니며, 비공개 개인 사용만 허용된다. 이 저장소를 공개하거나 배포하지 않는다.

## 포팅한 파일

| 원본 | 포팅 위치 | 비고 |
|------|-----------|------|
| `src/worker/core/GameSim.football/index.ts` | `gridiron/engine/skeleton/game.py` | 결과 공식은 `gridiron/engine/outcome/fbgm.py`로 분리 |
| `src/worker/core/GameSim.football/Play.ts` | `gridiron/engine/skeleton/play.py` | |
| `src/worker/core/GameSim.football/getBestPenaltyResult.ts` | `gridiron/engine/skeleton/play.py` | |
| `src/worker/core/GameSim.football/penalties.ts` | `gridiron/engine/skeleton/penalties.py` | 한국어 반칙 이름 추가 |
| `src/worker/core/GameSim.football/formations.ts` | `gridiron/engine/skeleton/formations.py` | |
| `src/worker/core/GameSim.football/getCompositeFactor.ts` | `gridiron/engine/skeleton/composite.py` | |
| `src/worker/core/GameSim.football/LngTracker.ts` | `gridiron/engine/skeleton/lng_tracker.py` | |
| `src/worker/core/GameSim.football/PlayByPlayLogger.ts` | `gridiron/engine/skeleton/pbp.py` | 점수 기록 부분만 |
| `src/common/constants.football.ts` (COMPOSITE_WEIGHTS) | `gridiron/engine/adapter.py` | |
| `src/worker/core/player/ovr.football.ts` | `gridiron/engine/adapter.py` | |
| `src/worker/core/GameSim.basketball/getInjuryRate.ts` | `gridiron/engine/skeleton/game.py` | |
| `src/common/random.ts` (randInt, truncGauss, choice, shuffle) | `gridiron/engine/skeleton/rng.py` | 시드 고정 |

## 포팅한 테스트

| 원본 | 포팅 위치 |
|------|-----------|
| `Play.test.ts` (29개) | `tests/test_engine_play.py` |
| `index.test.ts` (10개) | `tests/test_engine_game.py` |
| `LngTracker.test.ts`, `penalties.test.ts` | `tests/test_lng_tracker.py`, `tests/test_penalties.py` |

## 원본과 다른 점

- 모든 난수는 시드 고정 `Rng`를 거친다.
- 리그 설정(`g.get`)을 `GameSettings`로 바꿨다. 기본값은 NFL 2025년 이후 규칙(정규시즌 연장 10분, 양 팀 공격권, 킥오프 터치백 35야드).
- 승부차기는 제외했다.
- 팀 최장 기록은 원본의 `"player"` 키 대신 `"team"` 키로 따로 추적한다.
