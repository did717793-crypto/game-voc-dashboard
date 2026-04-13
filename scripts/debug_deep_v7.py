#!/usr/bin/env python3
"""
debug_deep_v7.py — 원인 규명 최종
====================================
[목적]
  1. Phase G GET URL 전체 출력 (truncation 없음)
  2. sd_date=co (완료일 기준) 테스트
  3. 광범위 날짜 범위로 데이터 존재 구간 탐색
  4. 최소 1건이라도 나오는 조건 찾기
"""

import json, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR    = Path(__file__).parent
CONFIG_FILE    = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE    = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"
DKR_GAME_ID    = "2474"

START = "2026-04-03"
END   = "2026-04-10"


def load_credentials():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return cfg["hive_id"], cfg["hive_pw"]


def load_cookies(ctx):
    if COOKIE_FILE.exists():
        ctx.add_cookies(json.loads(COOKIE_FILE.read_text()))
        return True
    return False


def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2))


def do_login(page, ctx, hid, hpw):
    page.goto(PLATFORM_LOGIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.fill("#userId", hid)
    page.fill("#passWd", hpw)
    page.click("button:text('로그인')")
    time.sleep(3)
    for sel in ["button:text('확인')", ".modal button:text('확인')"]:
        try:
            page.click(sel, timeout=2_000); time.sleep(1); break
        except Exception:
            pass
    page.wait_for_load_state("networkidle", timeout=30_000)
    time.sleep(2)
    save_cookies(ctx)


def find_inquiry_frame(page):
    for f in page.frames:
        url = f.url
        if ("inquiry.withhive.com" in url and "/inquiry" in url
                and "smarteditor" not in url.lower()
                and "inputarea" not in url
                and "Skin.html" not in url):
            return f
    return None


def quick_count(hf) -> tuple[int, str]:
    try:
        body = hf.inner_text("body")
        m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
        if m:
            c = int(m.group(1).replace(',', ''))
            ctx_m = re.search(r'검색 건수[^\n]{0,200}', body)
            return c, (ctx_m.group(0).replace('\n', ' ')[:120] if ctx_m else str(c))
    except Exception:
        pass
    return -1, ''


def goto_and_count(hf, url, label, wait_sec=6) -> tuple[int, str]:
    try:
        hf.goto(url, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(wait_sec)
    except Exception as e:
        print(f"  [{label}] goto 실패: {e}")
        return -1, ''
    c, t = quick_count(hf)
    print(f"  [{label}] {c}건  /  {t[:100]}")
    return c, t


def main():
    hid, hpw = load_credentials()
    print("=" * 70)
    print(f"  원인 규명 v7  [{START} ~ {END}]")
    print("=" * 70)

    req_log = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        load_cookies(ctx)
        page = ctx.new_page()
        page.on("request", lambda r: req_log.append((r.method, r.url)) if "inquiry.withhive.com/inquiry?" in r.url else None)

        # ── 로그인 ─────────────────────────────────────────────────────
        print("\n[A] 로그인")
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        if "platform.withhive.com" in page.url:
            do_login(page, ctx, hid, hpw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)

        # 계정 이메일
        try:
            body = page.inner_text("body")
            m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w{2,}', body)
            print(f"  계정: {m.group(0) if m else '?'}")
        except Exception:
            print("  계정: ?")

        # ── HIVEframe 진입 ─────────────────────────────────────────────
        print("\n[B] HIVEframe 진입")
        hf = None
        for _ in range(10):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)
        if not hf:
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try: page.click(sel, timeout=3_000); break
                except Exception: pass
            for _ in range(20):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break
        if not hf:
            INQUIRY_BASE = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
            page.evaluate(f"""() => {{
                var el = document.querySelector('#consoleContents, iframe[name="HIVEframe"]');
                if(el) el.src = '{INQUIRY_BASE}';
            }}""")
            for _ in range(15):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break
        if not hf:
            print("  ❌ HIVEframe 진입 실패"); browser.close(); return
        print(f"  ✅ {hf.url}")

        # ── 한국어 탭 로드 ─────────────────────────────────────────────
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # ── Phase G 재현 (버튼 클릭) + 전체 URL 출력 ──────────────────
        print(f"\n[C] 버튼 클릭 Phase 재현 — 전체 URL 캡처")
        req_log.clear()

        # 게임 선택
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        # 날짜 설정
        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START} - {END}';
                if (sds) sds.value = '{START}';
                if (sde) sde.value = '{END}';
            }}
        """)
        # 상태 전체 선택
        hf.evaluate("() => document.querySelectorAll('input[name^=\"ss_\"]').forEach(function(c){c.checked=true;})")
        time.sleep(0.3)

        # 버튼 클릭
        hf.click("button#btn_submit", timeout=5_000, force=True)
        time.sleep(3)
        hf.wait_for_load_state("networkidle", timeout=10_000)
        time.sleep(2)

        c_click, t_click = quick_count(hf)
        print(f"  클릭 결과: {c_click}건  원문: {t_click}")
        print(f"\n  [캡처된 전체 요청 URL(최대 3개)]:")
        for method, url in req_log[:3]:
            print(f"  [{method}] {url}")  # 전체 URL (no truncation)

        # URL 파라미터 파싱
        if req_log:
            full_url = req_log[0][1]
            params = {}
            for p in full_url.split("?", 1)[-1].split("&"):
                kv = p.split("=", 1)
                if len(kv) == 2:
                    params[kv[0]] = kv[1]
            ss_keys = [k for k in params if k.startswith("ss_")]
            print(f"\n  URL 파라미터 분석:")
            print(f"    sg  = {params.get('sg','없음')}")
            print(f"    sds = {params.get('sds','없음')}")
            print(f"    sde = {params.get('sde','없음')}")
            print(f"    sdf = {params.get('sdf','없음')}")
            print(f"    sd_date = {params.get('sd_date','없음')}")
            print(f"    ss_* = {ss_keys}  {'✅ 포함' if ss_keys else '❌ 없음 — ss_* 누락!!'}")

        # ── sd_date=co 테스트 ──────────────────────────────────────────
        print(f"\n[D] sd_date 변형 테스트")

        BASE = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342&lang=0014010001"
            f"&sg={DKR_GAME_ID}"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
            f"&sds={START}&sde={END}"
            "&spc=50&page=1"
        )

        print("  [sd_date=st (접수일 기준 — 기본)]")
        goto_and_count(hf, BASE + "&sd_date=st", "접수일기준")

        print("  [sd_date=co (완료일 기준)]")
        goto_and_count(hf, BASE + "&sd_date=co", "완료일기준")

        print("  [sd_date=mo (수정일 기준 — 가능하면)]")
        goto_and_count(hf, BASE + "&sd_date=mo", "수정일기준")

        # ── 날짜 범위 탐색 ─────────────────────────────────────────────
        print(f"\n[E] 날짜 범위 탐색 (데이터 존재 구간 찾기)")
        date_tests = [
            ("2026-04-03", "2026-04-10", "7일(스크린샷 범위)"),
            ("2026-03-03", "2026-04-10", "5주"),
            ("2026-01-01", "2026-04-10", "3.5개월"),
            ("2025-10-01", "2026-04-10", "6.5개월"),
            ("2025-04-18", "2026-04-10", "DKR 출시~현재(1년)"),
            ("2026-04-01", "2026-04-10", "4월 전체"),
            ("2026-03-01", "2026-04-10", "2개월"),
        ]
        BASE_SCAN = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342&lang=0014010001"
            f"&sg={DKR_GAME_ID}"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&sd_date=st&spc=50&page=1"
        )
        for s, e, label in date_tests:
            url = BASE_SCAN + f"&sds={s}&sde={e}"
            goto_and_count(hf, url, label, wait_sec=4)

        # sg=-1 (전체 게임)로도 스캔
        print(f"\n[F] sg=-1 (전체 게임) 날짜 탐색")
        BASE_ALL = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342&lang=0014010001"
            "&sg=-1"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&sd_date=st&spc=50&page=1"
        )
        all_game_tests = [
            ("2026-04-03", "2026-04-10", "7일"),
            ("2026-04-01", "2026-04-10", "4월"),
            ("2026-03-01", "2026-04-10", "2개월"),
            ("2025-04-18", "2026-04-10", "1년전체"),
        ]
        for s, e, label in all_game_tests:
            url = BASE_ALL + f"&sds={s}&sde={e}"
            goto_and_count(hf, url, label, wait_sec=4)

        # ── 첫 페이지 rows 상세 (날짜+상태 확인) ──────────────────────
        print(f"\n[G] 최다 건수 범위 첫 페이지 rows 상세 덤프")
        # DKR 1년 전체
        best_url = BASE_SCAN + "&sds=2025-04-18&sde=2026-04-10"
        hf.goto(best_url, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)
        c_best, t_best = quick_count(hf)
        print(f"  DKR 1년 건수: {c_best}건")
        rows = hf.evaluate("""
            () => {
                var result = [];
                document.querySelectorAll('table#table_dataList tbody tr').forEach(function(row) {
                    var cells = Array.from(row.querySelectorAll('td')).map(function(c) {
                        return c.innerText.trim().replace(/\\s+/g,' ');
                    });
                    result.push(cells);
                });
                return result;
            }
        """)
        print(f"  rows 수: {len(rows)}")
        for i, row in enumerate(rows[:10]):
            print(f"  row[{i}]: {row}")

        # ── 최종 요약 ──────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print("[결론]")
        print(f"  버튼 클릭 결과 : {c_click}건")
        if req_log:
            params_str = req_log[0][1].split("?",1)[-1]
            ss_found = bool(re.search(r'ss_\d+=on', params_str))
            sds_found = 'sds=' in params_str
            print(f"  GET URL ss_* 포함 : {'✅' if ss_found else '❌'}")
            print(f"  GET URL sds= 포함 : {'✅' if sds_found else '❌'}")
        print(f"  DKR+1년 전체 건수 : {c_best}건")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
