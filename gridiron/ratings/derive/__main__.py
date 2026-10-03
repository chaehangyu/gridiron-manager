from __future__ import annotations

import argparse
import json
from pathlib import Path

from ...config import DATA_DIR
from .build import build, write


def main() -> None:
    ap = argparse.ArgumentParser(description="실측 능력치 산출 (PRD §7.2)")
    ap.add_argument("--season", type=int, default=2026, help="능력치를 만들 시즌 (기록은 직전 3시즌)")
    ap.add_argument("--cache", type=Path, default=DATA_DIR / "raw")
    args = ap.parse_args()
    rat, report = build(args.season, args.cache, DATA_DIR)
    out = DATA_DIR / "real" / str(args.season)
    write(rat, report, out)
    v = report["validation"]
    print(f"저장: {out / 'ratings.csv'} ({len(rat)}명)")
    print("주전 PR 평균:", json.dumps(v["starter_pr_mean"], ensure_ascii=False))
    print("PR 17+ 인원:", json.dumps(v["elite_pr17"], ensure_ascii=False))
    print("19.5 이상 능력치:", json.dumps(v["twenty_counts"], ensure_ascii=False))
    print("F2-5d 분포 검증:", "통과" if v["pass"] else "실패")


if __name__ == "__main__":
    main()
