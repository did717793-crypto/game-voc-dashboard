#!/usr/bin/env python3
"""
debug_screenshot_v11.py — 화면 스크린샷 + ci_session 쿠키 상세 + 계정 확인
"""
import json, re, time, base64
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR  = Path(__file__).parent
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE  = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
DKR_GAME_ID  = "2474"
START = "2026-04-03"
END   = "2026-04-10"
SHOTS_DIR = SCRIPTS_DIR.parent / "data" / "screenshots"


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
        try: page.click(sel, timeout=2_000); time.sleep(1); break
        except Exception: pass
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


def parse_status(hf) -> dict:
    try:
        body = hf.inner_text("body")
        result = {}
        for k, pat in [
            ("total",    r'검색\s*건수\s*:?\s*([\d,]+)'),
            ("접수완료",  r'접수\s*완료\s*:?\s*([\d,]+)'),
            ("처리중",    r'처리\s*중\s*:?\s*([\d,]+)'),
            ("답변완료",  r'답변\s*완료\s*:?\s*([\d,]+)'),
            ("조회완료",  r'조회\s*완료\s*:?\s*([\d,]+)'),
            ("삭제",      r'(?<![ㄱ-ㅎ가-힣])삭제\s*:?\s*([\d,]+)'),
            ("관리자삭제", r'관리자\s*삭제\s*:?\s*([\d,]+)'),
        ]:
            m = re.search(pat, body)
            if m:
                result[k] = int(m.group(1).replace(',', ''))
        return result
    except Exception:
        return {}


def main():
    hid, hpw = load_credentials()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("  스크린샷 + 계정 확인 v11")
    print("="*70)

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

        # ── 로그인 ──────────────────────────────────────────────────
        print("\n[A] 로그인")
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        if "platform.withhive.com" in page.url:
            print("  재로그인")
            do_login(page, ctx, hid, hpw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)

        # console 페이지 스크린샷
        shot1 = SHOTS_DIR / "01_console_main.png"
        page.screenshot(path=str(shot1), full_page=False)
        print(f"  console 스크린샷: {shot1}")

        # 계정 이메일 - 더 적극적으로 탐색
        account = "?"
        # 방법1: 여러 CSS 선택자
        for sel in [
            ".user-info", ".user-name", ".user-email", ".top-nav .user",
            "#userInfo", ".header-user", "[class*='user']", "[class*='account']",
            ".nav-user", ".topbar .user"
        ]:
            try:
                txt = page.locator(sel).first.inner_text(timeout=2_000).strip()
                if "@" in txt:
                    account = txt
                    break
                elif txt:
                    print(f"  후보({sel}): '{txt[:50]}'")
            except Exception:
                pass

        # 방법2: 전체 HTML에서 ntrance 패턴 탐색
        if account == "?":
            try:
                html = page.content()
                m = re.search(r'cs6a2@\w+\.\w+', html, re.IGNORECASE)
                if m:
                    account = m.group(0)
                else:
                    m = re.search(r'[\w.]+@ntran[cs]e?\.\w+', html, re.IGNORECASE)
                    if m:
                        account = m.group(0)
            except Exception:
                pass

        # 방법3: JS로 특정 DOM 탐색
        if account == "?":
            try:
                account = page.evaluate("""
                    () => {
                        var els = document.querySelectorAll('*');
                        for(var i=0; i<els.length; i++) {
                            var t = els[i].innerText || '';
                            if(t.includes('@') && t.includes('ntrance') && t.length < 100)
                                return t.trim();
                        }
                        return '?';
                    }
                """)
            except Exception:
                pass

        print(f"  ✅ 계정: {account}")

        # ci_session_inquiry 쿠키 전체 값 확인
        all_cookies = ctx.cookies()
        ci_cookie = next((c for c in all_cookies if c['name'] == 'ci_session_inquiry'), None)
        if ci_cookie:
            import urllib.parse
            decoded = urllib.parse.unquote(ci_cookie['value'])
            print(f"\n  ci_session_inquiry (URL decoded):")
            print(f"  {decoded[:400]}")

        # ── HIVEframe 진입 ──────────────────────────────────────────
        print("\n[B] HIVEframe 진입")
        hf = None
        for _ in range(20):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)
        if not hf:
            for sel in ["a[menu='415']"]:
                try: page.click(sel, timeout=3_000); break
                except Exception: pass
            for _ in range(20):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break

        if not hf:
            print("  ❌"); browser.close(); return
        print(f"  ✅ {hf.url}")

        # iframe 로드 완료 대기
        hf.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(5)

        # iframe 내 ci_session_inquiry 확인
        ci_after = next((c for c in ctx.cookies() if c['name'] == 'ci_session_inquiry'), None)
        if ci_after:
            import urllib.parse
            decoded_after = urllib.parse.unquote(ci_after['value'])
            print(f"\n  ci_session 이후 (iframe 로드 후):")
            print(f"  {decoded_after[:400]}")
            same = (ci_cookie['value'] if ci_cookie else '') == ci_after['value']
            print(f"  쿠키 변경 여부: {'동일 (변경 없음)' if same else '✅ 변경됨!'}")

        # 한국어 탭 클릭
        print("\n[C] 한국어 탭 클릭")
        hf.evaluate("() => { var a = document.querySelector('a[href*=\"lang=0014010001\"]'); if(a) a.click(); }")
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        # 스크린샷 (한국어 탭 초기)
        shot2 = SHOTS_DIR / "02_korean_tab_init.png"
        page.screenshot(path=str(shot2), full_page=False)
        print(f"  한국어 탭 스크린샷: {shot2}")

        s_ko_init = parse_status(hf)
        print(f"  한국어 탭 초기: {s_ko_init}")

        # DKR 게임 선택 + 날짜 설정 + 전체 상태 선택
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=3_000)
        except Exception:
            hf.evaluate(f"""
                () => {{
                    var s = document.querySelector('select[name="sg"]');
                    if(s) {{ s.value='{DKR_GAME_ID}'; s.dispatchEvent(new Event('change',{{bubbles:true}})); }}
                }}
            """)

        hf.evaluate(f"""
            () => {{
                document.querySelector('input[name="sdf"]') && (document.querySelector('input[name="sdf"]').value = '{START} - {END}');
                document.querySelector('input[name="sds"]') && (document.querySelector('input[name="sds"]').value = '{START}');
                document.querySelector('input[name="sde"]') && (document.querySelector('input[name="sde"]').value = '{END}');
                document.querySelectorAll('input[name^="ss_"]').forEach(function(c){{c.checked=true;}});
            }}
        """)

        # 스크린샷 (클릭 직전)
        shot3 = SHOTS_DIR / "03_before_click.png"
        page.screenshot(path=str(shot3), full_page=False)
        print(f"  클릭 직전 스크린샷: {shot3}")

        # 클릭
        hf.click("button#btn_submit", timeout=5_000, force=True)
        time.sleep(8)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # 스크린샷 (검색 후)
        shot4 = SHOTS_DIR / "04_after_search.png"
        page.screenshot(path=str(shot4), full_page=False)
        print(f"  검색 후 스크린샷: {shot4}")

        s_result = parse_status(hf)
        print(f"\n  검색 결과: {s_result}")

        # 검색 결과 body 전체 텍스트
        try:
            body = hf.inner_text("body")
            m = re.search(r'검색 건수.{0,500}', body, re.DOTALL)
            print(f"\n  결과 영역 텍스트:\n  {(m.group(0) if m else body[:500]).replace(chr(10),' ')[:300]}")
        except Exception:
            pass

        print(f"\n  스크린샷 저장 위치: {SHOTS_DIR}")
        print(f"  1. {shot1.name} — console 메인")
        print(f"  2. {shot2.name} — 한국어 탭 초기")
        print(f"  3. {shot3.name} — 검색 직전")
        print(f"  4. {shot4.name} — 검색 후")

        browser.close()


if __name__ == "__main__":
    main()
