"""엔진 리그 평균 통계 점검 (PRD §8.4 보정 목표와 비교).

사용법: python tools/check_engine_stats.py [경기 수=500] [모델=data|fbgm] [리그=sample|real:2026]
리그 경기를 돌려 득점·완성률·색 비율 등 리그 평균을 출력한다.
"""
from gridiron.engine.skeleton.settings import GameSettings
import sys, time
from collections import defaultdict
from gridiron.data.sample import generate_sample_league
from gridiron.engine.adapter import build_team
from gridiron.engine.skeleton.game import GameSim
N=int(sys.argv[1]) if len(sys.argv)>1 else 500
MODEL=sys.argv[2] if len(sys.argv)>2 else "data"
from gridiron.engine.outcome.data_model import DataOutcome
from gridiron.engine.outcome.fbgm import FbgmOutcome
def outcome():
    return DataOutcome.for_league(L) if MODEL=="data" else FbgmOutcome()
SRC=sys.argv[3] if len(sys.argv)>3 else "sample"
if SRC=="sample":
    L=generate_sample_league()
else:
    from gridiron.data.real_league import load_real_league
    L=load_real_league(int(SRC.split(":")[1]))
L.schedule=[g for g in L.schedule if g.game_type=="REG"]
from gridiron.engine.norms import compute_norms
NORMS=compute_norms(L)
tot=defaultdict(float); games=0; t0=time.time(); ties=0
for i in range(N):
    g=L.schedule[i%len(L.schedule)]
    res=GameSim([build_team(L,g.home,0,g.gameday),build_team(L,g.away,1,g.gameday)],settings=GameSettings.from_config(),outcome=outcome(),seed=i,norms=NORMS).run()
    games+=1
    a,b=res["team"]
    if a.stat["pts"]==b.stat["pts"]: ties+=1
    for tm in res["team"]:
        for k in ["pssTD","rusTD","tp","tpa","pts","pss","pssCmp","pssYds","rus","rusYds","pssSk","pssInt","fmbLost","pen","penYds","drives","fga0","fga20","fga30","fga40","fga50","fg0","fg20","fg30","fg40","fg50","xpa","xp","pnt","pntYds","kr","krYds","pr","prYds"]:
            tot[k]+=tm.stat[k]
tg=2*games
dropbacks=tot["pss"]+tot["pssSk"]
plays=tot["pss"]+tot["rus"]+tot["pssSk"]
fga=sum(tot[f"fga{x}"] for x in (0,20,30,40,50)); fg=sum(tot[f"fg{x}"] for x in (0,20,30,40,50))
print(f"games {games} in {time.time()-t0:.1f}s, ties {ties}")
print(f"pts/team {tot['pts']/tg:.1f}  plays/team {plays/tg:.1f}  cmp% {tot['pssCmp']/tot['pss']*100:.1f}  Y/A {tot['pssYds']/tot['pss']:.2f}  YPC {tot['rusYds']/tot['rus']:.2f}")
print(f"sack% {tot['pssSk']/dropbacks*100:.1f}  INT% {tot['pssInt']/tot['pss']*100:.2f}  TO/team {(tot['pssInt']+tot['fmbLost'])/tg:.2f}  FG% {fg/max(1,fga)*100:.1f} FGA/team {fga/tg:.2f}")
print(f"pass rate {dropbacks/plays*100:.1f}%  pen/team {tot['pen']/tg:.1f} penYds {tot['penYds']/tg:.1f}  drives/team {tot['drives']/tg:.1f} punts/team {tot['pnt']/tg:.1f} net? {tot['pntYds']/max(1,tot['pnt']):.1f}")
print(f"TD/team {(tot['pssTD']+tot['rusTD'])/tg:.2f} (pass {tot['pssTD']/tg:.2f})  2pt att/team {tot['tpa']/tg:.2f}  XP% {tot['xp']/max(1,tot['xpa'])*100:.1f}")
print(f"KR avg {tot['krYds']/max(1,tot['kr']):.1f} ({tot['kr']/tg:.1f}/team)  PR avg {tot['prYds']/max(1,tot['pr']):.1f}")
