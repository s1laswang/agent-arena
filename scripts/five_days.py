import os,sys,json
from lab import run as R
from agents import gemini
R.FACTORIES["procedure"]=(lambda day,trial:__import__("agents.procedure",fromlist=["x"]).make_procedure_team(day,trial),"scripted")
ids=[int(x) for x in sys.argv[1].split(",")]
for d in ids:
    row=[d]
    for team in ("reference","trust_all"):
        res,_=R.play_day(team,team,None,d,0)
        row.append((team,res["goal_kind"],res["strategy"],res["reward"],res["sleeper_caught"],len(res["harm"])))
    print(row,flush=True)
print(gemini._usage,gemini.usage()["cost"])
