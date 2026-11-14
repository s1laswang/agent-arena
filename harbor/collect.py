import os, urllib.request

urllib.request.urlopen(urllib.request.Request("http://localhost:8001/reward", headers={"X-Verify-Token": os.environ["VERIFY_TOKEN"]}), timeout=100).read()
