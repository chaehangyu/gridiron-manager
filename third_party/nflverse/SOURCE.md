# nflverse 데이터·모델 출처

| 대상 | 출처 | 사용 방식 | 위치 |
|------|------|-----------|------|
| play-by-play, 참여, FTN 차팅 (2022–2025) | https://github.com/nflverse/nflverse-data (CC-BY 4.0, FTN CC-BY-SA 4.0) | 기준 분포 표 생성 | `gridiron/baseline/build.py` → `data/baseline/tables.json` |
| 2026 로스터·뎁스차트·일정·팀 | nflreadpy | 실제 리그 데이터 | `gridiron/data/nflverse_import.py` → `data/real/2026` |
| nflfastR EP·WP·xpass 모델 구조 | https://github.com/nflverse/nflfastR (MIT), https://opensourcefootball.com/posts/2020-09-28-nflfastr-ep-wp-and-cp-models/ | 구조 참고 후 경량 모델로 재학습 (EP는 nflverse `ep` 목표, WP·xpass는 실제 결과 목표) | `gridiron/baseline/train_models.py` → `data/baseline/models.json` |
| nfl4th 4th down 판단 | https://github.com/nflverse/nfl4th (MIT) | 판단 로직 구조 포팅 (선택지별 승률 비교). 전환율·펀트 거리·FG 성공률은 우리 실측 표 사용 | `gridiron/engine/ai/decisions.py` |
| nflseedR 타이브레이커 | https://github.com/nflverse/nflseedR (MIT) | M5에서 포팅 예정 | — |
