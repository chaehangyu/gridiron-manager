"""지구력 + 의료 숨김 능력치 원천 지표 (PRD §7.2 "신체·지구력", "의료").

- stamina_pct: 출전한 경기에서의 평균 스냅 점유율 (공격·수비 중 큰 쪽)
- missed_rate: 부상 리포트에 Out/Doubtful로 오른 시즌의 결장 경기 비율 (내구성, 낮을수록 좋음)
- q_played: Questionable로 등록된 주에 실제로 뛴 비율 (통증 내성)
- out_streak: 결장 연속 주 수 ÷ 같은 부상 부위 평균 (회복력, 낮을수록 좋음)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import acc


def _snaps(cache: Path, last_season: int) -> pd.DataFrame:
    sc = pd.read_parquet(cache / "snap_counts.parquet")
    sc = sc[(sc.game_type == "REG") & (sc.season <= last_season)]
    ids = pd.read_parquet(cache / "players.parquet", columns=["gsis_id", "pfr_id"]).dropna().drop_duplicates("pfr_id")
    sc = sc.merge(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    sc["pct"] = np.maximum(sc.offense_pct.fillna(0), sc.defense_pct.fillna(0))
    sc["any"] = (sc.offense_snaps.fillna(0) + sc.defense_snaps.fillna(0) + sc.st_snaps.fillna(0)) > 0
    return sc


def health_metrics(cache: Path, seasons: dict[int, float]) -> pd.DataFrame:
    last = max(seasons)
    sc = _snaps(cache, last)
    out = []
    # 지구력: 기록 창 시즌만, 수비·공격 스냅이 있는 경기
    s = sc[sc.season.isin(seasons) & (sc.pct > 0)]
    out.append(acc(s.gsis_id, s.pct, s.season.map(seasons), "stamina_pct"))

    inj = pd.read_parquet(cache / "injuries.parquet")
    inj = inj[(inj.game_type == "REG") & (inj.season <= last)]
    # 오래된 시즌도 의료 지표에는 쓴다 (가중치는 기록 창 밖이면 0.3)
    w_of = lambda y: seasons.get(y, 0.3)  # noqa: E731
    out_status = inj.report_status.isin(["Out", "Doubtful"])

    # 내구성: 시즌별 결장 경기 수 (그 시즌에 부상 결장 기록이 있을 때만 스냅 없는 경기를 결장으로 센다)
    played = sc[sc["any"]].groupby(["gsis_id", "season"]).size().rename("games")
    had_out = inj[out_status].groupby(["gsis_id", "season"]).size().rename("outs")
    per = pd.concat([played, had_out], axis=1).fillna(0).reset_index()
    per = per[per.games + per.outs > 0]
    per["missed"] = np.where(per.outs > 0, np.clip(17 - per.games, per.outs, 17), 0) / 17
    out.append(acc(per.gsis_id, per.missed, per.season.map(w_of), "missed_rate"))

    # 통증 내성: Questionable 주에 출전했는가
    q = inj[inj.report_status == "Questionable"][["gsis_id", "season", "week"]].drop_duplicates()
    pl = sc[["gsis_id", "season", "week", "any"]]
    q = q.merge(pl, on=["gsis_id", "season", "week"], how="left")
    q["played"] = q["any"].fillna(False).astype(float)
    out.append(acc(q.gsis_id, q.played, q.season.map(w_of), "q_played"))

    # 회복력: 연속 결장 길이 ÷ 부상 부위 평균
    o = inj[out_status][["gsis_id", "season", "week", "report_primary_injury"]].sort_values(["gsis_id", "season", "week"])
    o["new"] = (o.groupby(["gsis_id", "season"]).week.diff() != 1)
    o["streak_id"] = o.new.cumsum()
    st = o.groupby("streak_id").agg(gsis_id=("gsis_id", "first"), season=("season", "first"), length=("week", "size"),
                                    injury=("report_primary_injury", "first"))
    st["injury"] = st.injury.fillna("Unknown").str.split().str[0].str.lower()
    st["ratio"] = st.length / st.groupby("injury").length.transform("mean")
    out.append(acc(st.gsis_id, st.ratio.clip(0, 4), st.season.map(w_of), "out_streak"))
    return pd.concat(out, ignore_index=True)
