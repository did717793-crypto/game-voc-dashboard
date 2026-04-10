#!/usr/bin/env python3
"""
collect_cs_browser.py — DKR CS 브라우저 자동 수집기 v1.0
============================================================
Hive inquiry.withhive.com 에 Playwright 로 접속하여 CS 문의 목록을 수집하고
cs_raw_YYYY-MM-DD.json 으로 저장한 뒤 collect_cs_data.py 를 연속 실행한다.

【사용법】
  # 기본 (오늘 기준, 헤드리스 모드)
  python3 collect_cs_browser.py

  # 특정 날짜 지정
  python3 collect_cs_browser.py --date 2026-04-09

  # 브라우저 창 표시 (디버깅)
  python3 collect_cs_browser.py --headed

  # 원시 수집만 (analyze 미실행)
  python3 collect_cs_browser.py --no-analyze

【설정 우선순위】
  1. 환경변수: HIVE_ID, HIVE_PW
  2. config.local.json: {"hive_id": "...", "hive_pw": "..."}
  3. 세션 쿠키 재사용: scripts/raw/hive_cookies.json (이전 세션 자동 저장)
  4. 대화형 입력 (fallback)

【의존성】
  pip install playwright --break-system-packages
  python3 -m playwright install chromium
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Playwright 임포트 ─────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("[ERROR] playwright 미설치 → pip install playwright --break-system-packages")
    sys.exit(1)

# ── 경로 ─────────────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).parent
RAW_DIR      = SCRIPTS_DIR / "raw"
COOKIE_FILE  = RAW_DIR / "hive_cookies.json"
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
KST          = timezone(timedelta(hours=9))

RAW_DIR.mkdir(exist_ok=True)

# ── Hive URL 상수 ─────────────────────────────────────────────────────────────
HIVE_LOGIN_URL   = "https://hive.com/ko/signin"
HIVE_INQUIRY_URL = "https://inquiry.withhive.com/ko/inquiry"
HIVE_SESSION_CHECK = "https://inquiry.withhive.com"

# ── BROWSER_JS (collect_cs_data.py 와 동일) ───────────────────────────────────
BROWSER_JS = r"""
(function() {
  var rows = document.querySelectorAll('table tbody tr');
  var data = [];
  rows.forEach(function(row) {
    var cells = row.querySelectorAll('td');
    if (cells.length < 10) return;
    var title   = cells[1] ? cells[1].textContent.trim() : '';
    var type    = cells[3] ? cells[3].textContent.trim() : '';
    var subtype = cells[4] ? cells[4].textContent.trim() : '';
    var recv    = cells[7].textContent.trim().substring(0, 10);
    var comp    = cells[8].textContent.trim().substring(0, 10);
    var status  = cells[9].textContent.trim();
    if (recv && recv !== '-') {
      data.push({
        title:    title,
        type:     type,
        subtype:  subtype,
        received: recv,
        completed: comp !== '-' ? comp : null,
        status:   status
      });
    }
  });
  return JSON.stringify({
    collected_at: new Date().toISOString(),
    total:        data.length,
    records:      data
  });
})();
"""

# ── 자격증명 로드 ─────────────────────────────────────────────────────────────

def load_credentials() -> tuple[str, str]:
    """우선순위: 환경변수 → config.local.json → 대화형 입력"""
    hive_id = os.environ.get("HIVE_ID", "")
    hive_pw = os.environ.get("HIVE_PW", "")

    if hive_id and hive_pw:
        print("[INFO] 환경변수에서 자격증명 로드")
        return hive_id, hive_pw

    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            hive_id = cfg.get("hive_id", "")
            hive_pw = cfg.get("hive_pw", "")
            if hive_id and hive_pw:
                print("[INFO] config.local.json에서 자격증명 로드")
                return hive_id, hive_pw
        except Exception:
            pass

    # 대화형 입력
    import getpass
    print("\n[입력] Hive 계정 정보를 입력하세요 (inquiry.withhive.com)")
    hive_id = input("  Hive ID: ").strip()
    hive_pw = getpass.getpass("  Hive PW: ")
    return hive_id, hive_pw


def save_credentials_hint(hive_id: str):
    """config.local.json에 hive_id 힌트만 기록 (PW 저장 안 함)"""
    if not CONFIG_FILE.exists():
        return
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if "hive_id" not in cfg:
            cfg["hive_id"] = hive_id
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[INFO] config.local.json에 hive_id 저장 완료")
    except Exception:
        pass


# ── 쿠키 저장/로드 ─────────────────────────────────────────────────────────────

def save_cookies(context):
    cookies = context.cookies()
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 쿠키 저장 → {COOKIE_FILE.name}")


def load_cookies(context) -> bool:
    if not COOKIE_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        print(f"[INFO] 쿠키 로드 ({len(cookies)}개) → {COOKIE_FILE.name}")
        return True
    except Exception as e:
        print(f"[WARN] 쿠키 로드 실패: {e}")
        return False


# ── 세션 체크 / 로그인 ────────────────────────────────────────────────────────

def is_logged_in(page) -> bool:
    """현재 페이지가 로그인 상태인지 확인"""
    try:
        page.goto(HIVE_SESSION_CHECK, timeout=15_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        url = page.url
        # 로그인 페이지로 리다이렉트되면 미로그인
        return "signin" not in url and "login" not in url
    except Exception:
        return False


def login(page, hive_id: str, hive_pw: str) -> bool:
    """Hive 로그인 시도. 반환: 성공 여부"""
    print(f"[INFO] 로그인 시도 → {HIVE_LOGIN_URL}")
    try:
        page.goto(HIVE_LOGIN_URL, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=20_000)

        # ID/PW 입력 셀렉터 (Hive 실제 셀렉터 — 변경 시 수정 필요)
        selectors_id = ["input[type='email']", "input[name='email']",
                        "input[placeholder*='이메일']", "input[placeholder*='ID']",
                        "#email", "#id"]
        selectors_pw = ["input[type='password']", "input[name='password']",
                        "#password", "#pw"]

        id_filled = False
        for sel in selectors_id:
            try:
                page.fill(sel, hive_id, timeout=3_000)
                id_filled = True
                print(f"  ID 입력 ({sel})")
                break
            except Exception:
                continue

        pw_filled = False
        for sel in selectors_pw:
            try:
                page.fill(sel, hive_pw, timeout=3_000)
                pw_filled = True
                print(f"  PW 입력 ({sel})")
                break
            except Exception:
                continue

        if not id_filled or not pw_filled:
            print("[WARN] 로그인 폼 셀렉터를 찾지 못함 — 헤드 모드로 재시도 권장")
            return False

        # 로그인 버튼 클릭
        btn_selectors = ["button[type='submit']", "button:has-text('로그인')",
                         "button:has-text('Login')", ".login-btn", "#loginBtn"]
        for sel in btn_selectors:
            try:
                page.click(sel, timeout=3_000)
                print(f"  로그인 버튼 클릭 ({sel})")
                break
            except Exception:
                continue

        page.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(2)

        url = page.url
        if "signin" in url or "login" in url:
            print("[ERROR] 로그인 실패 — 잘못된 자격증명이거나 CAPTCHA 발생")
            return False

        print("[OK] 로그인 성공")
        return True

    except Exception as e:
        print(f"[ERROR] 로그인 예외: {e}")
        return False


# ── 페이지 수집 ───────────────────────────────────────────────────────────────

def collect_all_pages(page, max_pages: int = 50) -> list[dict]:
    """문의 목록 전체 페이지 순회하여 records 수집"""
    all_records: list[dict] = []
    collected_at_ts = datetime.now(KST).isoformat()

    for page_no in range(1, max_pages + 1):
        url = f"{HIVE_INQUIRY_URL}?page={page_no}"
        print(f"  [PAGE {page_no}] {url}")
        try:
            page.goto(url, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)

            # 세션 만료 체크
            if "signin" in page.url or "login" in page.url:
                print(f"  [WARN] 세션 만료 감지 (page {page_no}) → 중단")
                break

            raw_json = page.evaluate(BROWSER_JS)
            if not raw_json:
                print(f"  [WARN] JS 실행 결과 없음 (page {page_no})")
                break

            result = json.loads(raw_json)
            records = result.get("records", [])
            if not records:
                print(f"  → 데이터 없음 → 수집 완료 (총 {len(all_records)}건)")
                break

            all_records.extend(records)
            print(f"  → {len(records)}건 수집 (누적: {len(all_records)}건)")

            # 마지막 페이지 감지: records < 20 이면 종료 (Hive 기본 페이지 사이즈=20)
            if len(records) < 20:
                print(f"  → 마지막 페이지 감지 (records={len(records)}<20)")
                break

            time.sleep(0.5)   # 과부하 방지

        except PWTimeout:
            print(f"  [WARN] Timeout (page {page_no}) → 재시도 스킵")
            break
        except Exception as e:
            print(f"  [ERROR] page {page_no}: {e}")
            break

    return all_records


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DKR CS 브라우저 자동 수집")
    parser.add_argument("--date", "-d",
                        default=datetime.now(KST).strftime("%Y-%m-%d"),
                        help="대상 날짜 (기본: 오늘 KST)")
    parser.add_argument("--headed", action="store_true",
                        help="브라우저 창 표시 (헤드모드, 디버깅용)")
    parser.add_argument("--no-analyze", action="store_true",
                        help="raw 저장만 하고 collect_cs_data.py 실행 안 함")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="최대 페이지 수 (기본: 50)")
    args = parser.parse_args()

    target_date = args.date
    out_file    = RAW_DIR / f"cs_raw_{target_date}.json"

    print(f"\n{'='*55}")
    print(f"  DKR CS 브라우저 수집  대상: {target_date}")
    print(f"{'='*55}\n")

    # 자격증명 로드
    hive_id, hive_pw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = context.new_page()

        # ── 1) 저장된 쿠키로 세션 복원 시도 ──
        has_cookies = load_cookies(context)
        logged_in = False

        if has_cookies:
            print("[INFO] 쿠키 세션 검증 중...")
            logged_in = is_logged_in(page)
            if logged_in:
                print("[OK] 세션 복원 성공")
            else:
                print("[INFO] 세션 만료 → 재로그인")

        # ── 2) 쿠키 없거나 만료 시 로그인 ──
        if not logged_in:
            if not hive_id or not hive_pw:
                print("[ERROR] 자격증명 없음 → 종료")
                browser.close()
                sys.exit(1)

            logged_in = login(page, hive_id, hive_pw)
            if not logged_in:
                print("[ERROR] 로그인 실패 → --headed 옵션으로 직접 확인 필요")
                browser.close()
                sys.exit(1)

            save_cookies(context)
            save_credentials_hint(hive_id)

        # ── 3) 문의 목록 수집 ──
        print(f"\n[INFO] 문의 목록 수집 시작 (최대 {args.max_pages}페이지)")
        records = collect_all_pages(page, max_pages=args.max_pages)

        browser.close()

    if not records:
        print("[WARN] 수집된 records 없음 → 파일 미저장")
        sys.exit(1)

    # ── 4) 저장 ──
    payload = {
        "collected_at": datetime.now(KST).isoformat(),
        "target_date":  target_date,
        "total":        len(records),
        "records":      records,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 저장 완료 → {out_file.name}  ({len(records)}건)")

    # ── 5) collect_cs_data.py 실행 ──
    if not args.no_analyze:
        print(f"\n[INFO] collect_cs_data.py 실행 → {target_date}")
        result = subprocess.run(
            [sys.executable,
             str(SCRIPTS_DIR / "collect_cs_data.py"),
             target_date,
             "--data", str(out_file)],
            capture_output=False,
        )
        if result.returncode == 0:
            print("[OK] collect_cs_data.py 완료")
        else:
            print("[WARN] collect_cs_data.py 실패 → 수동 실행 필요")
            print(f"  python3 collect_cs_data.py {target_date} --data {out_file}")
    else:
        print(f"\n[INFO] --no-analyze 지정 → collect_cs_data.py 스킵")
        print(f"  수동 실행: python3 collect_cs_data.py {target_date} --data {out_file}")

    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
