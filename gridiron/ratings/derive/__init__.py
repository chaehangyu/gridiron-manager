"""실측 능력치 산출 파이프라인 (PRD §7.2, M3).

nflverse 기록 → 선수별 지표 → 경험적 베이즈 수축 → 포지션 내 백분위 → F2-5 기준표의 1–20 값.

    python -m gridiron.ratings.derive --season 2026          # 2023–2025 기록으로 2026 능력치
    python -m gridiron.ratings.derive --season 2025          # 2022–2024 기록으로 2025 능력치 (재현 테스트용)

빌드할 때만 pandas·scikit-learn·scipy가 필요하다 (`pip install -e ".[data]"`). 게임은 결과 CSV만 읽는다.
"""
