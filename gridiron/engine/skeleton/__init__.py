"""Football GM(ZenGM) 경기 엔진 골격의 Python 포팅.

원본: https://github.com/zengm-games/zengm  src/worker/core/GameSim.football/
기준 커밋: 73727b86720a331ee39c2db0fc1c6445339abdd2 (2026-09-26)
라이선스: third_party/zengm/LICENSE.md (비공개 개인 사용 조건)

바뀐 점
- 모든 난수는 시드 고정 `Rng`를 거친다 (결정론적 재현, PRD F5-5a).
- 패스·런 결과 계산은 `gridiron.engine.outcome`의 결과 모델로 분리했다 (ENGINE_DESIGN §3).
- 리그 설정(`g.get`)은 `GameSettings`로 바꿨다.
- 승부차기(shootout)는 NFL에 없어서 제외했다.
"""
