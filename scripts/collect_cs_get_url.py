#!/usr/bin/env python3
"""
collect_cs_get_url.py — DKR CS 수집 v1.0 (GET URL 직접 호출 방식)
============================================================
기존 UI 클릭/날짜버튼 방식 대체.
GET URL 파라미터(sds/sde)로 날짜 범위를 정확히 지정.

검증된 방식 (2026-04-28):
  GET https://inquiry.withhive.com/inquiry?...sds=2026-04-14&sde=2026-04-27&sg=2474 → 62건 확인

[필터 규칙]
  - sg=2474 (DKR) 파라미터 포함
  - ss_1~ss_6 포함, ss_7 제외
  - raw 저장 시 cells[3]='DK : REBORN' 인 것만 저장 (이중 필터)
  - ETC / 이메일 / 비회원 전부 제외

[사용법]
  python3 collect_cs_get_url.py 2026-04-14 2026-04-27
  python3 collect_cs_get_url.py 2026-04-21 2026-04-21   # 단일 날짜

[출력]
  scripts/raw/cs_raw_STARTDATE_to_ENDDATE.json
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright 미설치")
    sys.exit(1)

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).parent
RAW_DIR      = SCRIPTS_DIR / "raw"
COOKIE_FILE  = RAW_DIR / "hive_cookies.json"
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
KST          = timezone(timedelta(hours=9))
RAW_DIR.mkdir(exist_ok=True)

CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"

# DKR 게임명 (필터 기준)
DKR_GAME_NAME = "DK : REBORN"
DKR_GAME_ID   = "2474"

# GET URL 기본 파라미터 (검증된 구조 2026-04-28 기준)
GET_URL_BASE = (
    "https://inquiry.withhive.com/inquiry?"
    "menu_cd=415&company_cd=342&lang=0014010001"
    "&sg={game_id}"
    "&sc=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
    "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
    "&sdf={sdf}"
    "&sds={sds}&sde={sde}"
    "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on"
    "&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1"
    "&sd_date=st&spc=200&page={page}"
)


# ── 자격증명 로드 ─────────────────────────────────────────────────────────────
def load_credentials():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        hid = cfg.get("hive_id", "")
        hpw = cfg.get("hive_pw", "")
        if hid and hpw:
            return hid, hpw
    import os
    return os.environ.get("HIVE_ID", ""), os.environ.get("HIVE_PW", "")


# ── 로그인 ────────────────────────────────────────────────────────────────────
def do_login(page, ctx, hive_id, hive_pw):
    """collect_cs_browser.py와 동일한 검증된 로그인 방식"""
    print(f"[INFO] 로그인 → {PLATFORM_LOGIN}")
    try:
        page.goto(PLATFORM_LOGIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        page.fill("#userId", hive_id, timeout=5_000)
        page.fill("#passWd", hive_pw, timeout=5_000)
        print("  ID/PW 입력 완료")
        # 로그인 버튼: 텍스트 기반 + class 기반 둘 다 시도
        for sel in ["button:text('로그인')", "button.btn_confirm", "button:text('Log in')"]:
            try:
                page.click(sel, timeout=3_000)
                print(f"  로그인 버튼 클릭 ({sel})")
                break
            except Exception:
                pass
        # 동시접속 팝업
        time.sleep(3)
        for sel in ["button:text('확인')", ".modal button:text('확인')", "button.btn-primary"]:
            try:
                page.click(sel, timeout=2_000)
                print(f"  동시접속 팝업 확인")
                time.sleep(1)
                break
            except Exception:
                pass
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(3)
        if "platform.withhive.com" in page.url or "auth/login" in page.url:
            print(f"[ERROR] 로그인 실패: {page.url}")
            return False
        COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2))
        print(f"[OK] 로그인 성공 → {page.url}")
        return True
    except Exception as e:
        print(f"[ERROR] 로그인 예외: {e}")
        return False


# ── iframe 획득 ───────────────────────────────────────────────────────────────
def get_hive_frame(page, ctx, hive_id, hive_pw):
    page.goto(CONSOLE_MAIN, timeout=30_000)
    time.sleep(3)

    # 세션 만료 체크
    if "platform.withhive.com" in page.url or "auth" in page.url:
        print("[INFO] 세션 만료 → 재로그인")
        if not do_login(page, ctx, hive_id, hive_pw):
            return None
        page.goto(CONSOLE_MAIN, timeout=30_000)
        time.sleep(3)

    # iframe 검색
    def find_frame():
        for f in page.frames:
            if "inquiry.withhive.com" in (f.url or "") and "/inquiry" in (f.url or ""):
                return f
        return None

    hf = find_frame()
    if hf:
        return hf

    # 메뉴 클릭
    try:
        page.click("a[menu='415']", timeout=8_000)
        time.sleep(5)
    except Exception:
        pass

    hf = find_frame()
    if hf:
        return hf

    # JS로 iframe src 설정
    page.evaluate(f"""
        () => {{
            var f = document.querySelector('iframe#consoleContents, iframe[name="HIVEframe"]');
            if (f) f.src = '{KOREAN_TAB_URL}';
        }}
    """)
    time.sleep(6)
    return find_frame()


# ── 행 파싱 ──────────────────────────────────────────────────────────────────
def parse_row(cells: list) -> dict | None:
    """table row → record dict. cells[3]=게임명 기준으로 DKR 검증."""
    if len(cells) < 10:
        return None
    received = cells[7][:10].strip() if cells[7] else ""
    if not re.match(r"\d{4}-\d{2}-\d{2}", received):
        return None
    completed_raw = cells[8].strip() if cells[8] else ""
    completed = completed_raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", completed_raw) else None

    return {
        "title":    cells[5].strip(),
        "category": cells[4].strip(),
        "game":     cells[3].strip(),          # DK : REBORN 또는 ETC 등
        "path":     cells[2].strip(),
        "uid":      cells[6].strip().split("\n")[0],
        "received": received,
        "completed": completed,
        "status":   cells[9].strip(),
    }


# ── 페이지 수집 ───────────────────────────────────────────────────────────────
def collect_pages(hf, start_date: str, end_date: str) -> tuple[list, list]:
    """
    GET URL로 특정 날짜 범위 전체 수집.
    반환: (전체 records, DKR 필터링된 records)
    """
    sdf = f"{start_date} - {end_date}"
    page_no = 1
    all_records = []

    # 총 건수 파악 (첫 페이지)
    url = GET_URL_BASE.format(
        game_id=DKR_GAME_ID, sdf=sdf.replace(" ", "+"),
        sds=start_date, sde=end_date, page=1
    )
    print(f"  [GET] {url[:120]}...")
    hf.goto(url, timeout=15_000)
    time.sleep(4)

    body = hf.inner_text("body")
    m = re.search(r"검색\s*건수\s*:?\s*([\d,]+)", body)
    total = int(m.group(1).replace(",", "")) if m else 0

    # 실제 적용된 날짜 확인
    actual_dates = hf.evaluate("""() => ({
        sds: document.querySelector('input[name="sds"]')?.value || '',
        sde: document.querySelector('input[name="sde"]')?.value || ''
    })""")
    print(f"  서버 적용 날짜: {actual_dates['sds']} ~ {actual_dates['sde']}")
    print(f"  총 건수: {total}건")

    if total == 0:
        return [], []

    # 페이지별 수집
    while True:
        rows = hf.evaluate("""
            () => Array.from(document.querySelectorAll('table tbody tr')).map(row => {
                return Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
            }).filter(c => c.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && c.length >= 10)
        """)

        page_records = [r for r in (parse_row(row) for row in rows) if r]
        all_records.extend(page_records)
        print(f"  [PAGE {page_no}] {len(page_records)}건 (누적: {len(all_records)}/{total})")

        if len(all_records) >= total:
            break

        # 다음 페이지 GET URL
        page_no += 1
        url_next = GET_URL_BASE.format(
            game_id=DKR_GAME_ID, sdf=sdf.replace(" ", "+"),
            sds=start_date, sde=end_date, page=page_no
        )
        hf.goto(url_next, timeout=15_000)
        time.sleep(3)

    # DK : REBORN 필터링
    dkr_records = [r for r in all_records if r["game"] == DKR_GAME_NAME]
    other_records = [r for r in all_records if r["game"] != DKR_GAME_NAME]

    print(f"\n  [필터 결과]")
    print(f"  total_raw    = {len(all_records)}건")
    print(f"  filtered_raw = {len(dkr_records)}건 (DK : REBORN)")
    if other_records:
        from collections import Counter
        others = Counter(r["game"] for r in other_records)
        print(f"  제외된 데이터: {dict(others)}")

    return all_records, dkr_records


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DKR CS GET URL 수집")
    parser.add_argument("start", help="수집 시작일 (YYYY-MM-DD)")
    parser.add_argument("end",   help="수집 종료일 (YYYY-MM-DD)")
    parser.add_argument("--no-analyze", action="store_true", help="raw 저장만 (analyzed 갱신 생략)")
    args = parser.parse_args()

    start_date = args.start
    end_date   = args.end

    print(f"\n{'='*60}")
    print(f" DKR CS 수집 (GET URL 방식)")
    print(f" 기간: {start_date} ~ {end_date}")
    print(f"{'='*60}")

    hive_id, hive_pw = load_credentials()
    if not hive_id:
        print("[ERROR] 자격증명 없음"); sys.exit(1)
    print(f"[INFO] 자격증명 로드: {hive_id}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()

        if COOKIE_FILE.exists():
            try:
                ctx.add_cookies(json.loads(COOKIE_FILE.read_text()))
                print(f"[INFO] 쿠키 로드")
            except Exception:
                pass

        page = ctx.new_page()
        hf = get_hive_frame(page, ctx, hive_id, hive_pw)

        if not hf:
            print("[ERROR] HIVEframe 획득 실패")
            browser.close()
            sys.exit(1)

        # 수집
        all_records, dkr_records = collect_pages(hf, start_date, end_date)
        browser.close()

    if not all_records:
        print("[WARN] 수집된 데이터 없음")
        sys.exit(0)

    # raw 파일 저장
    raw_fname = f"cs_raw_{start_date}_to_{end_date}.json"
    raw_path  = RAW_DIR / raw_fname
    payload = {
        "collected_at": datetime.now(KST).isoformat(),
        "start_date":   start_date,
        "end_date":     end_date,
        "total_raw":    len(all_records),
        "filtered_raw": len(dkr_records),
        "filter":       f"game == '{DKR_GAME_NAME}'",
        "records":      dkr_records,
    }
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] raw 파일 저장: {raw_fname} ({len(dkr_records)}건)")

    # 날짜별 분포 출력
    from collections import Counter
    date_cnt = Counter(r["received"] for r in dkr_records)
    print(f"\n[날짜별 건수]:")
    for d in sorted(date_cnt.keys()):
        print(f"  {d}: {date_cnt[d]}건")

    # collect_cs_data.py 실행 (날짜별 analyzed 갱신)
    if not args.no_analyze:
        gen = SCRIPTS_DIR / "collect_cs_data.py"
        if not gen.exists():
            print("[WARN] collect_cs_data.py 없음")
        else:
            from datetime import datetime as dt, timedelta
            sd = dt.strptime(start_date, "%Y-%m-%d")
            ed = dt.strptime(end_date,   "%Y-%m-%d")
            # target_date = report_date + 1일
            target = sd + timedelta(days=1)
            end_target = ed + timedelta(days=1)
            print(f"\n[INFO] collect_cs_data.py 실행 (target_date: {target.strftime('%Y-%m-%d')} ~ {end_target.strftime('%Y-%m-%d')})")
            while target <= end_target:
                td_str = target.strftime("%Y-%m-%d")
                result = subprocess.run(
                    [sys.executable, str(gen), td_str, "--data", str(raw_path)],
                    capture_output=True, text=True
                )
                out_lines = [l for l in result.stdout.splitlines()
                             if any(k in l for k in ["OK]", "ERROR]", "cs_daily", "인입=", "처리=", "DONE"])]
                for l in out_lines:
                    print(f"  {l}")
                target += timedelta(days=1)

    print("\n[DONE] 완료!")


if __name__ == "__main__":
    main()
