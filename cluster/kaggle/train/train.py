import glob, json, os, subprocess, sys, threading
code = glob.glob("/kaggle/input/**/train/sft.py", recursive=True)[0].rsplit("/train/", 1)[0]
data = os.path.dirname(glob.glob("/kaggle/input/**/*.jsonl", recursive=True)[0])
work = "/kaggle/working"
os.chdir(code)
cfgp = data + "/run.json"
cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else {}
models = cfg.get("models", ["Qwen/Qwen2.5-0.5B-Instruct"])
sft_args, eval_args, decide_args = cfg.get("sft", []), cfg.get("eval", []), cfg.get("decide", [])
train_file = data + "/" + cfg.get("data", "train.jsonl")
env0 = dict(os.environ, PYTHONPATH=code, HF_HUB_DISABLE_PROGRESS_BARS="1")
def run(env, *a):
    print("+", env.get("CUDA_VISIBLE_DEVICES"), *a, flush=True)
    subprocess.check_call([sys.executable, *a], env=env)
run(env0, "-m", "pip", "install", "-q", "-r", "requirements.txt")
run(env0, "-m", "pip", "uninstall", "-y", "-q", "torchao")
import torch
ngpu = max(1, torch.cuda.device_count())
has_decide = os.path.exists(code + "/train/decide.py")
oracle = work + "/oracle"
if has_decide:
    run(env0, "-m", "lab.run", "--team", "oracle", "--day-start", "1000", "--days", "40", "--trials", "1", "--out", oracle)
sft_extra = cfg.get("sft_extra", {})
def pipeline(model, i):
    tag = model.split("/")[-1]
    env = dict(env0, CUDA_VISIBLE_DEVICES=str(i % ngpu))
    ad, out = f"{work}/{tag}/adapter", f"{work}/{tag}"
    run(env, "-m", "train.sft", "--model", model, "--data", train_file, "--out", ad, *sft_args, *sft_extra.get(tag, []))
    for name, a in (("base", []), ("adapter", ["--adapter", ad])):
        if has_decide:
            run(env, "-m", "train.decide", "--model", model, *a, "--run", oracle, "--min-day", "1000", "--out", f"{out}/decide_{name}.json", *decide_args)
        run(env, "-m", "train.eval", "--model", model, *a, "--out", f"{out}/eval_{name}", *eval_args)
errs = []
def guard(m, i):
    try:
        pipeline(m, i)
    except Exception as e:
        errs.append((m, repr(e)))
if ngpu > 1:
    ts = [threading.Thread(target=guard, args=(m, i)) for i, m in enumerate(models)]
    [t.start() for t in ts]; [t.join() for t in ts]
else:
    for i, m in enumerate(models):
        guard(m, i)
rows = {}
for m in models:
    tag = m.split("/")[-1]
    for p in glob.glob(f"{work}/{tag}/*/metrics.json") + glob.glob(f"{work}/{tag}/*/*.json"):
        if p.endswith("metrics.json") or "decide" in p:
            rows[f"{tag}/{os.path.relpath(p, work + '/' + tag)}"] = json.load(open(p))
json.dump({"rows": rows, "errors": errs}, open(work + "/metrics.json", "w"), indent=1)
print(json.dumps({"rows": list(rows), "errors": errs}))
if errs:
    sys.exit(1)
