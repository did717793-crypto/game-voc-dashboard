#!/usr/bin/env python3
"""
run_daily.py — DKR VOC 백필 기반 자동 실행기 v2.0
──────────────────────────────────────────────────
실행 전략:
  "어제"까지의 모든 날짜를 스캔하여 누락된 처리만 수행합니다.

처리 흐름 (날짜별):
  1. raw.json 없으면   → crawl_dkr.py 실행
  2. analyzed.json 없으면 → analyze_voc.py 실행
  3. 날짜별 실패 시 → 로그 출력 후 다음 날짜 진행 (중단 없음)

완료 후 1회 실행:
  4. generate_dashboard.py → index.html 갱신
  5. git push → GitHub Pages 반영

설계 원칙:
  - dashboard.html → index.html 복사 로직 없음 (generate_dashboard.py가 직접 index.html 생성)
  - CS 브라우저 수집은 별도 수동 트리거 (collect_cs_data.py)
  - 스킵/실패 로그 명확히 구분
"""

import subprocess
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta, date as Date

KST     = timezone(timedelta(hours=9))
SCRIPTS = Path(__file__).parent
GIT_DIR = SCRIPTS.parent           # mnt/voc/
DATA_DIR = GIT_DIR / "data" / "DKR"
RAW_DIR  = SCRIPTS / "raw"

GITHUB_USER = "did717793-crypto"
GITHUB_REPO = "game-voc-dashboard"

# 서비스 시작일 (백필 하한선)
SERVICE_START = "2025-04-18"


# ════════════════════════════════════════════════════════════════════════════
#  유틸
# ════════════════════════════════════════════════════════════════════════════

def load_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        return token
    config_path = GIT_DIR / "config.local.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f).get("github_token", "")
    return ""


def run_script(script: str, args: list = None, *, label: str = None) -> bool:
    """scripts/ 하위 스크립트 실행. 반환: 성공 여부"""
    cmd = [sys.executable, str(SCRIPTS / script)] + (args or [])
    tag = label or script
    print(f"\n{'='*50}\n▶ [{tag}] {' '.join(cmd[1:])}\n{'='*50}")
    return subprocess.run(cmd).returncode == 0


def collect_cs_data(date_label: str) -> bool:
    """CS raw JSON → analyzed.json cs_week_trend 업데이트"""
    if not RAW_DIR.exists():
        print(f"[SKIP] CS raw 디렉토리 없음 ({RAW_DIR})")
        return False
    raw_files = sorted(RAW_DIR.glob("cs_raw_*.json"), reverse=True)
    if not raw_files:
        print("[SKIP] CS raw 파일 없음 → 브라우저 수동 수집 필요")
        return False
    latest = raw_files[0]
    print(f"\n{'='*50}\n▶ [CS] collect_cs_data.py {date_label}\n{'='*50}")
    return run_script("collect_cs_data.py", [date_label, "--data", str(latest)],
                      label="CS")


def git_push(message: str) -> bool:
    token = load_token()
    if not token:
        print("[WARN] GitHub 토큰 없음 → push 스킵")
        return False

    remote_url = f"https://{GITHUB_USER}:{token}@github.com/{GITHUB_USER}/{GITHUB_REPO}.git"

    steps = [
        (["git", "-C", str(GIT_DIR), "add", "-A"],                            "git add"),
        (["git", "-C", str(GIT_DIR), "commit", "-m", message],                "git commit"),
        (["git", "-C", str(GIT_DIR), "push", remote_url, "main"],             "git push"),
    ]

    for cmd, step_name in steps:
        log_cmd = [c.replace(token, "***") for c in cmd]
        print(f"  $ {' '.join(log_cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout + r.stderr
        if r.returncode != 0 and "nothing to commit" not in out:
            print(f"  [ERR] {step_name}: {out[:300]}")
            return False
        if r.stdout.strip():
            print(f"  {r.stdout.strip()[:120]}")

    print("[DONE] GitHub push 완료")
    return True


# ════════════════════════════════════════════════════════════════════════════
#  날짜 계산
# ════════════════════════════════════════════════════════════════════════════

def date_range(start: str, end: str) -> list[str]:
    """start~end 사이 날짜 리스트 (양 끝 포함)"""
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end,   "%Y-%m-%d").date()
    result = []
    cur = d0
    while cur <= d1:
        result.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return result


def has_raw(date_label: str) -> bool:
    return (DATA_DIR / f"{date_label}.json").exists()


def has_analyzed(date_label: str) -> bool:
    return (DATA_DIR / f"{date_label}.analyzed.json").exists()


# ════════════════════════════════════════════════════════════════════════════
#  메인
# ════════════════════════════════════════════════════════════════════════════

def main():
    now_kst   = datetime.now(KST)
    today     = now_kst.strftime("%Y-%m-%d")
    yesterday = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'#'*55}")
    print(f"  DKR VOC 백필 실행기  기준일: {yesterday}")
    print(f"{'#'*55}\n")

    # ── 처리 대상 날짜 계산 ────────────────────────────────────────────────
    all_dates   = date_range(SERVICE_START, yesterday)
    need_raw    = [d for d in all_dates if not has_raw(d)]
    need_analyze = [d for d in all_dates if has_raw(d) and not has_analyzed(d)]

    print(f"전체 날짜: {len(all_dates)}일  |  raw 없음: {len(need_raw)}일  |  analyzed 없음: {len(need_analyze)}일")

    crawl_ok   = []
    crawl_fail = []
    analyze_ok   = []
    analyze_fail = []

    # ── STEP 1: 크롤링 (raw 없는 날짜 중 어제만 수집 가능) ────────────────
    # crawl_dkr.py는 실행 시점의 "어제" 데이터를 수집하는 구조이므로
    # 어제 raw가 없을 때만 실행
    print(f"\n{'─'*55}")
    print("STEP 1: 크롤링 (raw 없는 날짜 처리)")
    print(f"{'─'*55}")

    if not has_raw(yesterday):
        print(f"  → {yesterday} raw 없음, crawl_dkr.py 실행")
        ok = run_script("crawl_dkr.py", label="CRAWL")
        if ok:
            crawl_ok.append(yesterday)
            # 크롤 성공 후 analyzed 대상 갱신
            if not has_analyzed(yesterday):
                need_analyze.append(yesterday)
        else:
            crawl_fail.append(yesterday)
            print(f"  [FAIL] {yesterday} 크롤링 실패")
    else:
        print(f"  → {yesterday} raw 이미 있음, 크롤링 스킵")

    if need_raw and yesterday not in need_raw:
        print(f"  ※ 과거 raw 누락 {len(need_raw)}건은 수동 복구 필요 (crawl_dkr.py는 어제만 수집)")
        for d in need_raw[:5]:
            print(f"     {d}")
        if len(need_raw) > 5:
            print(f"     ... 외 {len(need_raw)-5}건")

    # ── STEP 2: 분석 (analyzed 없는 날짜 처리) ───────────────────────────
    print(f"\n{'─'*55}")
    print(f"STEP 2: VOC 분석 ({len(need_analyze)}건 처리 예정)")
    print(f"{'─'*55}")

    need_analyze_sorted = sorted(set(need_analyze))

    if not need_analyze_sorted:
        print("  → 분석 대상 없음 (모두 처리 완료)")
    else:
        for d in need_analyze_sorted:
            if not has_raw(d):
                print(f"  [SKIP] {d} raw 없음")
                continue
            ok = run_script("analyze_voc.py", [d], label=f"ANALYZE {d}")
            if ok:
                analyze_ok.append(d)
            else:
                analyze_fail.append(d)
                print(f"  [FAIL] {d} 분석 실패 → 다음 날짜 진행")

    # ── STEP 3: CS 데이터 (어제 기준) ─────────────────────────────────────
    print(f"\n{'─'*55}")
    print("STEP 3: CS 데이터 업데이트")
    print(f"{'─'*55}")
    collect_cs_data(yesterday)

    # ── STEP 4: 대시보드 생성 ─────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print("STEP 4: 대시보드 생성")
    print(f"{'─'*55}")
    dash_ok = run_script("generate_dashboard.py", label="DASHBOARD")
    if not dash_ok:
        print("[WARN] 대시보드 생성 실패")

    # ── STEP 5: GitHub push ───────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print("STEP 5: GitHub push")
    print(f"{'─'*55}")
    push_msg = f"VOC 자동 업데이트: {today} KST"
    git_push(push_msg)

    # ── 최종 요약 ─────────────────────────────────────────────────────────
    print(f"\n{'#'*55}")
    print(f"  실행 결과 요약")
    print(f"{'#'*55}")
    print(f"  크롤링  성공: {len(crawl_ok)}건  실패: {len(crawl_fail)}건")
    print(f"  분석    성공: {len(analyze_ok)}건  실패: {len(analyze_fail)}건")
    if crawl_fail:
        print(f"  [크롤 실패] {crawl_fail}")
    if analyze_fail:
        print(f"  [분석 실패] {analyze_fail}")
    print(f"{'#'*55}\n")


if __name__ == "__main__":
    main()
