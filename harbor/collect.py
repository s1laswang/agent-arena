import argparse
import json
import os
import sys
import urllib.request

from sleeper.secrets import take


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--secrets-file", default=None)
    a = ap.parse_args(argv)
    sf = a.secrets_file or os.environ.get("SLEEPER_SECRETS_FILE") or (
        "/app/secrets.json" if not os.environ.get("VERIFY_TOKEN") and os.path.isfile("/app/secrets.json") else None
    )
    sec = take("VERIFY_TOKEN", secrets_file=sf)
    token = (sec.get("VERIFY_TOKEN") or "").strip()
    if not token:
        sys.exit("VERIFY_TOKEN is required")
    port = int(os.environ.get("SIDECAR_REWARD_PORT", "8001"))
    req = urllib.request.Request(f"http://127.0.0.1:{port}/reward", headers={"X-Verify-Token": token})
    with urllib.request.urlopen(req, timeout=100) as resp:
        status = getattr(resp, "status", None) or resp.getcode()
        body = resp.read()
    if status != 200:
        sys.exit(f"unexpected reward status: {status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        sys.exit(f"invalid reward JSON: {exc}")
    if not isinstance(payload, dict):
        sys.exit("invalid reward payload")
    return payload


if __name__ == "__main__":
    main()
