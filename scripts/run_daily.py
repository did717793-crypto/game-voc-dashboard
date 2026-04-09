#!/usr/bin/env python3
"""
VOC 일일 자동 실행 스크립트
매일 09:00 KST에 스케줄러(Claude)가 호출하는 진입점.

실행 순서:
  1. DKR 커뮤니티 크롤링 (crawl_dkr.py)
  2. CS 데이터 처리 - raw JSON → analyzed.json (collect_cs_data.py)
     ※ raw JSON은 Claude가 브라우저 JS로 사전 수집해 scripts/raw/ 에 저장
  3. 대시보드 HTML 갱신 (generate_dashboard.py)
  4. GitHub Pages 자동 push

CS 데이터 수집 방식:
  - inquiry.withhive.com은 OAuth 인증 필요 → Python 직접 호출 불가
  - Claude가 브라우저로 접속 후 JS로 데이터 추출 → scripts/raw/cs_raw_YYYY-MM-DD.json 저장
  - 이 스크립트는 저장된 raw 파일을 처리하는 역할만 담당
"""
import subprocess
import sys
import os
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

KST     = timezone(timedelta(hours=9))
SCRIPTS = Path(__file__).parent
GIT_DIR = SCRIPTS.parent          # mnt/voc/ (스크립트 위치 기준 상위 경로, 세션 독립적)
RAW_DIR = SCRIPTS / "raw"

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


def collect_cs_data(today: str) -> bool:
    """CS raw JSON 파일 처리 → analyzed.json 업데이트"""
    raw_files = sorted(RAW_DIR.glob("cs_raw_*.json"), reverse=True) if RAW_DIR.exists() else []
    if not raw_files:
        print("[WARN] CS raw 파일 없음 → CS 데이터 업데이트 스킵")
        print("       Claude에게 '오늘 CS 데이터 브라우저로 수집해줘' 요청 필요")
        return False

    latest_raw = raw_files[0]
    print(f"\n{'='*50}\n▶ CS 데이터 처리: {latest_raw.name}\n{'='*50}")
    return run_script("collect_cs_data.py", [today, "--data", str(latest_raw)])


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
    today     = datetime.now(KST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'#'*50}")
    print(f"  DKR VOC 일일 수집  {today}  (데이터 기준: {yesterday})")
    print(f"{'#'*50}")

    # 1) 커뮤니티 크롤링
    crawl_ok = run_script("crawl_dkr.py")

    if crawl_ok:
        # 2) VOC 규칙 기반 분석 → analyzed.json 생성 (없을 때만)
        run_script("analyze_voc.py", [yesterday])

        # 3) CS 데이터 처리 (raw JSON → analyzed.json cs_week_trend 업데이트)
        collect_cs_data(yesterday)

        # 4) 대시보드 재생성
        run_script("generate_dashboard.py")

        # 5) GitHub push
        git_push()
    else:
        print("[WARN] 크롤링 실패 → 분석/CS/대시보드/push 건너뜀")

    print(f"\n[DONE] 일일 VOC 수집 완료 ({today})")
