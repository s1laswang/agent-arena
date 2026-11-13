import glob, os, shutil, subprocess, sys
code = glob.glob("/kaggle/input/**/train/sft.py", recursive=True)[0].rsplit("/train/", 1)[0]
data = os.path.dirname(glob.glob("/kaggle/input/**/*.jsonl", recursive=True)[0])
work = "/kaggle/working"
os.chdir(code)
env = dict(os.environ, PYTHONPATH=code, HF_HUB_DISABLE_PROGRESS_BARS="1")
def run(*a):
    print("+", *a, flush=True)
    subprocess.check_call([sys.executable, *a], env=env)
run("-m", "pip", "install", "-q", "-r", "requirements.txt")
model = os.environ.get("MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
run("-m", "train.sft", "--model", model, "--data", data + "/train.jsonl", "--out", work + "/adapter")
run("-m", "train.eval", "--model", model, "--out", work + "/eval_base")
run("-m", "train.eval", "--model", model, "--adapter", work + "/adapter", "--out", work + "/eval_adapter")
