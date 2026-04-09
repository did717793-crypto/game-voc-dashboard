#!/usr/bin/env python3
"""
run_daily.py — DKR VOC 백필 기반 자동 실행기 v3.0
──────────────────────────────────────────────────
변경 (v2.0 → v3.0):
  [FIX] STEP 1 크롤링: 어제 1건만 처리 → need_raw 전체 순회
        - 각 누락 날짜에 crawl_dkr.py --date YYYY-MM-DD 실행
        - RETROACTIVE_WINDOW_DAYS(30일) 이내만 소급 크롤
        - 30일 초과 누락은 API 데이터 없음으로 간주 스킵

실행 전략:
  "어제"까지의 모든 날짜를 스캔하여 누락된 처리만 수행합니다.

처리 흐름 (날짜별):
  1. raw.json 없는 날짜 전체 → crawl_dkr.py --date [해당날짜]
  2. analyzed.json 없는 날짜 전체 → analyze_voc.analyze()
  3. 날짜별 실패 시 → 로그 후 다음 날짜 진행 (중단 없음)

완료 후 1회 실행:
  4. generate_dashboard.py → index.html 갱신
  5. git push → GitHub Pages 반영

설계 원칙:
  - crawl_dkr.py --date: 지정 날짜의 00:00~23:59 KST 윈도우로 수집
  - dashboard.html → index.html 복사 로직 없음
  - CS 브라우저 수집은 별도 수동 트리거 (collect_cs_data.py)
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

# 소급 크롤 최대 기간 (일): 이 기간 내 누락만 crawl 시도
# Naver Lounge API는 오래된 데이터를 반환하지 않으므로 30일이 적절
RETROACTIVE_WINDOW_DAYS = 30


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

    # ── STEP 1: 크롤링 (raw 없는 날짜 전체 순회) ─────────────────────────
    # crawl_dkr.py --date YYYY-MM-DD: 해당 날짜 00:00~23:59 KST 윈도우로 수집
    # RETROACTIVE_WINDOW_DAYS 이내 누락만 시도 (오래된 날짜는 API 데이터 없음)
    print(f"\n{'─'*55}")
    print(f"STEP 1: 크롤링 (raw 없는 날짜 {len(need_raw)}건 처리)")
    print(f"{'─'*55}")

    def _days_diff(d: str) -> int:
        """d 기준 yesterday로부터 며칠 전인지"""
        return (datetime.strptime(yesterday, "%Y-%m-%d")
                - datetime.strptime(d, "%Y-%m-%d")).days

    recent_need_raw = sorted(d for d in need_raw if _days_diff(d) <= RETROACTIVE_WINDOW_DAYS)
    old_need_raw    = sorted(d for d in need_raw if _days_diff(d) >  RETROACTIVE_WINDOW_DAYS)

    if not need_raw:
        print(f"  → raw 누락 없음 (모두 수집 완료)")

    for d in recent_need_raw:
        diff = _days_diff(d)
        print(f"  → [{d}] raw 없음 ({diff}일 전), crawl --date {d}")
        ok = run_script("crawl_dkr.py", ["--date", d], label=f"CRAWL {d}")
        if ok and has_raw(d):               # 실제 파일 생성 확인
            crawl_ok.append(d)
            print(f"  [OK]   {d} 크롤링 성공")
            if not has_analyzed(d):
                need_analyze.append(d)
        else:
            crawl_fail.append(d)
            print(f"  [FAIL] {d} 크롤링 실패 (raw 파일 미생성)")

    if old_need_raw:
        print(f"\n  ※ {RETROACTIVE_WINDOW_DAYS}일 초과 누락 {len(old_need_raw)}건 — Naver API 소급 불가, 스킵")
        for d in old_need_raw[-3:]:         # 최근 3건만 표시 (오래된 것)
            print(f"     {d}")
        if len(old_need_raw) > 3:
            print(f"     (+ 구 누락 {len(old_need_raw)-3}건 생략)")

    # ── STEP 2: 분석 (analyzed 없는 날짜 처리) ───────────────────────────
    print(f"\n{'─'*55}")
    print(f"STEP 2: VOC 분석 ({len(need_analyze)}건 처리 예정)")
    print(f"{'─'*55}")

    # analyze_voc.analyze() 직접 호출 → 정확한 상태 추적
    sys.path.insert(0, str(SCRIPTS))
    try:
        from analyze_voc import analyze as _analyze
    except ImportError as e:
        print(f"[ERR] analyze_voc 임포트 실패: {e}")
        _analyze = None

    # 전체 날짜 상태 추적 테이블 {date: "SUCCESS"|"SKIP"|"FAIL:<reason>"}
    date_status: dict[str, str] = {}

    # 이미 완료된 날짜 (need_analyze에 없는 analyzed-complete 날짜)
    for d in all_dates:
        if has_analyzed(d) and d not in need_analyze:
            date_status[d] = "SKIP"

    need_analyze_sorted = sorted(set(need_analyze))

    if not need_analyze_sorted:
        print("  → 분석 대상 없음 (모두 처리 완료)")
    elif _analyze is None:
        print("  [ERR] analyze_voc 로드 실패 → subprocess fallback")
        for d in need_analyze_sorted:
            ok = run_script("analyze_voc.py", [d], label=f"ANALYZE {d}")
            status = "SUCCESS" if ok else "FAIL:subprocess"
            date_status[d] = status
            print(f"  {status}: {d}")
            if ok:
                analyze_ok.append(d)
            else:
                analyze_fail.append(d)
    else:
        for d in need_analyze_sorted:
            if not has_raw(d):
                date_status[d] = "FAIL:no_raw"
                print(f"  FAIL:no_raw : {d}")
                analyze_fail.append(d)
                continue
            try:
                result = _analyze(d)          # "ok" | "skip" | "fail_*"
                if result == "ok":
                    date_status[d] = "SUCCESS"
                    analyze_ok.append(d)
                    print(f"  SUCCESS     : {d}")
                elif result == "skip":
                    date_status[d] = "SKIP"
                    print(f"  SKIP        : {d}  (analyzed.json 존재)")
                else:
                    date_status[d] = f"FAIL:{result}"
                    analyze_fail.append(d)
                    print(f"  FAIL:{result:<10}: {d}")
            except Exception as exc:
                date_status[d] = f"FAIL:exception"
                analyze_fail.append(d)
                print(f"  FAIL:exception : {d}  ({exc})")

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
    push_ok = git_push(push_msg)

    # ── 최종 요약 ─────────────────────────────────────────────────────────
    total_ok   = len(analyze_ok)
    total_skip = sum(1 for s in date_status.values() if s == "SKIP")
    total_fail = len(analyze_fail)

    print(f"\n{'#'*55}")
    print(f"  ▶ 실행 결과 요약  ({today} KST)")
    print(f"{'#'*55}")
    print(f"  크롤링  : SUCCESS={len(crawl_ok)}  FAIL={len(crawl_fail)}")
    print(f"  분석    : SUCCESS={total_ok}  SKIP={total_skip}  FAIL={total_fail}")
    print(f"  대시보드: {'SUCCESS' if dash_ok else 'FAIL'}")
    print(f"  Push    : {'SUCCESS' if push_ok else 'FAIL/SKIP'}")
    print(f"{'─'*55}")
    # 날짜별 상세 (SUCCESS/FAIL만 출력, SKIP은 생략)
    for d in sorted(date_status):
        st = date_status[d]
        if st != "SKIP":
            print(f"  {st:<20} {d}")
    if analyze_fail:
        print(f"\n  ※ 분석 실패 날짜: {analyze_fail}")
    print(f"{'#'*55}\n")


if __name__ == "__main__":
    main()
