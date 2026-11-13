import json,glob,os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
rows=[]
for f in sorted(glob.glob("days/*.json")):
    if f.endswith("index.json"):continue
    d=json.load(open(f));r=d["result"][0]
    rows.append(dict(id=d["id"],seed=d["day"]["seed"],team=r["agent"],reward=r["reward"],sleeper_seat=d["day"]["sleeper_seat"],goal=d["day"]["goal"]["kind"] if d["day"]["goal"] else None,seat_under_test=r["seat_under_test"]))
json.dump(rows,open("days/index.json","w"),indent=1)
print(len(rows))
