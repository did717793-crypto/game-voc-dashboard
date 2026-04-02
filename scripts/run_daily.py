#!/usr/bin/env python3
"""
VOC 일일 자동 실행 스크립트
매일 09:00 KST에 스케줄러가 호출하는 진입점.
1. DKR 크롤링 (crawl_dkr.py)
2. 대시보드 HTML 갱신 (generate_dashboard.py)
3. GitHub Pages 자동 push
"""
import subprocess
import sys
import os
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
SCRIPTS = Path(__file__).parent
GIT_DIR = Path("/sessions/peaceful-epic-darwin/voc-git")

GITHUB_USER = "did717793-crypto"
GITHUB_REPO = "game-voc-dashboard"


def load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    config_path = GIT_DIR / "config.local.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f).get("github_token", "")
    return ""


def run_script(script: str, args: list = None) -> bool:
    cmd = [sys.executable, str(SCRIPTS / script)] + (args or [])
    print(f"\n{'='*50}\n▶ {' '.join(cmd)}\n{'='*50}")
    return subprocess.run(cmd).returncode == 0


def git_push() -> bool:
    token = load_token()
    if not token:
        print("[WARN] GitHub 토큰 없음 → git push 스킵")
        return False

    remote_url = f"https://{GITHUB_USER}:{token}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    steps = [
        ["git", "-C", str(GIT_DIR), "add", "-A"],
        ["git", "-C", str(GIT_DIR), "commit", "-m", f"VOC 자동 업데이트: {now_str}"],
        ["git", "-C", str(GIT_DIR), "push", remote_url, "main"],
    ]

    for cmd in steps:
        log_cmd = [c.replace(token, "***") for c in cmd]
        print(f"  $ {' '.join(log_cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout + r.stderr
        if r.returncode != 0 and "nothing to commit" not in out:
            print(f"  [ERR] {out[:300]}")
            return False
        if r.stdout.strip():
            print(f"  {r.stdout.strip()[:100]}")

    print("[DONE] GitHub push 완료")
    return True


if __name__ == "__main__":
    ok = run_script("crawl_dkr.py")

    if ok:
        run_script("generate_dashboard.py")

        # dashboard.html → index.html 동기화
        src = GIT_DIR / "dashboard.html"
        dst = GIT_DIR / "index.html"
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print("[INFO] index.html 동기화 완료")

        git_push()
    else:
        print("[WARN] 크롤링 실패 → 업데이트/push 건너뜀")

    print("\n[DONE] 일일 VOC 수집 완료")
