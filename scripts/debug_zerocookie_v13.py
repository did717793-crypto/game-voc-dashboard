#!/usr/bin/env python3
"""
debug_zerocookie_v13.py — 완전 fresh (저장 쿠키 없이 처음부터)
===============================================================
[전략] hive_cookies.json 전혀 사용하지 않음
       platform 로그인 → console 이동 → iframe 자동 로드 대기 →
       한국어 탭 → DKR/날짜/상태 설정 → 검색
       → 브라우저가 실제로 하는 정확한 흐름 재현
"""
import json, re, time, urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR    = Path(__file__).parent
CONFIG_FILE    = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE    = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
DKR_GAME_ID    = "2474"
START = "2026-04-03"
END   = "2026-04-10"
EXPECTED = 19
SHOTS_DIR = SCRIPTS_DIR.parent / "data" / "screenshots"


def load_credentials():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return cfg["hive_id"], cfg["hive_pw"]


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
            ("답변완료",  r'답변\s*완료\s*:?\s*([\d,]+)'),
            ("조회완료",  r'조회\s*완료\s*:?\s*([\d,]+)'),
            ("삭제",      r'(?<![ㄱ-ㅎ가-힣])삭제\s*:?\s*([\d,]+)'),
            ("관리자삭제", r'관리자\s*삭제\s*:?\s*([\d,]+)'),
            ("접수완료",  r'접수\s*완료\s*:?\s*([\d,]+)'),
            ("처리중",    r'처리\s*중\s*:?\s*([\d,]+)'),
        ]:
            m = re.search(pat, body)
            if m:
                result[k] = int(m.group(1).replace(',', ''))
        return result
    except Exception:
        return {}


def wait_result(hf, sec=20) -> dict:
    for _ in range(sec):
        time.sleep(1)
        s = parse_status(hf)
        if s.get("total", -1) >= 0:
            return s
    return {"total": -1}


def main():
    hid, hpw = load_credentials()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    req_log = []

    print("="*70)
    print("  완전 Fresh 세션 v13 (저장 쿠키 없음)")
    print(f"  계정: {hid}")
    print(f"  쿼리: DKR(2474) / {START}~{END} / ss_1~7 ALL")
    print(f"  기준: 총19건 / 답변완료13 / 조회완료6")
    print("="*70)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        # 완전 비어있는 컨텍스트 (저장 쿠키 없음)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        page.on("request", lambda r: req_log.append((r.method, r.url))
                if "inquiry.withhive.com/inquiry?" in r.url else None)

        # ── 1. platform.withhive.com 로그인 ───────────────────────────
        print("\n[1] 로그인 (쿠키 없는 상태에서 처음부터)")
        page.goto(PLATFORM_LOGIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        page.fill("#userId", hid)
        page.fill("#passWd", hpw)
        page.click("button:text('로그인')")
        time.sleep(3)
        for sel in ["button:text('확인')", ".modal button:text('확인')"]:
            try: page.click(sel, timeout=2_000); time.sleep(1); break
            except Exception: pass
        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(3)
        print(f"  로그인 후 URL: {page.url}")

        # ── 2. console.withhive.com 이동 ──────────────────────────────
        print("\n[2] console.withhive.com 이동")
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(5)
        print(f"  console URL: {page.url}")

        shot = SHOTS_DIR / "v13_01_console.png"
        page.screenshot(path=str(shot))
        print(f"  스크린샷: {shot}")

        # 계정 확인
        try:
            html = page.content()
            m = re.search(r'cs6a2@[\w.]+', html, re.IGNORECASE)
            print(f"  계정 확인: {m.group(0) if m else '?'}")
        except Exception:
            pass

        # ci_session_inquiry 현재 상태
        all_cookies = ctx.cookies()
        ci = next((c for c in all_cookies if c['name'] == 'ci_session_inquiry'), None)
        if ci:
            decoded = urllib.parse.unquote(ci['value'])
            at_m = re.search(r'"access_token";s:\d+:"([^"]+)"', decoded)
            print(f"  ci_session access_token: {at_m.group(1) if at_m else '없음'}")
        else:
            print("  ci_session_inquiry: 아직 없음")

        # ── 3. HIVEframe 진입 ─────────────────────────────────────────
        print("\n[3] HIVEframe 자동 대기")
        hf = None
        for i in range(30):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)
            if (i+1) % 5 == 0:
                print(f"  {i+1}초 대기 중... (frames: {len(page.frames)})")

        if not hf:
            print("  메뉴 클릭 시도")
            for sel in ["a[menu='415']", "a:text('문의 목록')", "[href*='menu_cd=415']"]:
                try: page.click(sel, timeout=3_000); break
                except Exception: pass
            for i in range(30):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break
                if (i+1) % 5 == 0: print(f"  {i+1}초...")

        if not hf:
            print("  ❌ HIVEframe 없음")
            # 모든 frames 목록
            print("  현재 프레임 목록:")
            for f in page.frames:
                print(f"    {f.url}")
            browser.close()
            return

        print(f"  ✅ iframe: {hf.url}")
        hf.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(5)

        # iframe 로드 후 ci_session 확인
        ci_after = next((c for c in ctx.cookies() if c['name'] == 'ci_session_inquiry'), None)
        if ci_after:
            decoded_a = urllib.parse.unquote(ci_after['value'])
            at_a = re.search(r'"access_token";s:\d+:"([^"]+)"', decoded_a)
            print(f"  iframe 후 access_token: {at_a.group(1) if at_a else '없음'}")
            if ci:
                changed = ci['value'] != ci_after['value']
                print(f"  ci_session 변경: {'✅ 새 세션 생성!' if changed else '동일'}")
        else:
            print("  ❌ iframe 후에도 ci_session_inquiry 없음!")

        # ── 4. 초기 상태 확인 ─────────────────────────────────────────
        print("\n[4] 초기 상태 확인")
        s_init = parse_status(hf)
        print(f"  초기(내 상담 탭): {s_init}")

        # ── 5. 한국어 탭 클릭 ──────────────────────────────────────────
        print("\n[5] 한국어 탭 클릭")
        req_log.clear()
        hf.evaluate("() => { var a = document.querySelector('a[href*=\"lang=0014010001\"]'); if(a) a.click(); }")
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        s_ko = parse_status(hf)
        print(f"  한국어 탭 초기: {s_ko}")
        print(f"  요청: {[u for m,u in req_log[:2]]}")

        shot2 = SHOTS_DIR / "v13_02_korean_init.png"
        page.screenshot(path=str(shot2))

        # ── 6. DKR + 날짜 + 전체 상태 + 검색 ─────────────────────────
        print(f"\n[6] DKR(2474) + {START}~{END} + ss_ALL + 검색")

        # 게임 선택
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        except Exception as e:
            print(f"  select 실패: {e}")
            hf.evaluate(f"() => {{ var s=document.querySelector('select[name=\"sg\"]'); if(s){{s.value='{DKR_GAME_ID}';s.dispatchEvent(new Event('change',{{bubbles:true}}));}} }}")

        sg_val = hf.evaluate("() => document.querySelector('select[name=\"sg\"]')?.value || '?'")
        print(f"  sg 값: {sg_val}")

        # 날짜
        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if(sdf) sdf.value = '{START} - {END}';
                if(sds) sds.value = '{START}';
                if(sde) sde.value = '{END}';
            }}
        """)

        # 상태 전체
        hf.evaluate("() => document.querySelectorAll('input[name^=\"ss_\"]').forEach(function(c){c.checked=true;})")

        # 검색 직전 폼 확인
        pre = hf.evaluate("""
            () => ({
                sg:   document.querySelector('select[name="sg"]')?.value || '?',
                lang: document.querySelector('input[name="lang"]')?.value || '?',
                sds:  document.querySelector('input[name="sds"]')?.value || '?',
                sde:  document.querySelector('input[name="sde"]')?.value || '?',
                ss_checked: Array.from(document.querySelectorAll('input[name^="ss_"]:checked')).map(function(c){return c.name;})
            })
        """)
        print(f"  직전 폼: {pre}")

        shot3 = SHOTS_DIR / "v13_03_before_click.png"
        page.screenshot(path=str(shot3))

        # 클릭
        req_log.clear()
        hf.click("button#btn_submit", timeout=5_000, force=True)
        print("  버튼 클릭 완료. 결과 대기...")
        time.sleep(10)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        # 스크린샷 및 결과
        shot4 = SHOTS_DIR / "v13_04_result.png"
        page.screenshot(path=str(shot4))

        s_result = parse_status(hf)
        total = s_result.get("total", -1)
        ans = s_result.get("답변완료", 0)
        viewed = s_result.get("조회완료", 0)
        deleted = s_result.get("삭제", 0)
        ok = (total == EXPECTED and ans == 13 and viewed == 6)

        print(f"\n  실제 요청 URL:")
        for m, u in req_log[:3]:
            print(f"  [{m}] {u}")

        print(f"\n  결과: 총={total}  답변완료={ans}  조회완료={viewed}  삭제={deleted}")
        print(f"  판정: {'✅ 재현 성공!' if ok else '❌ 불일치'}")

        # 현재 쿠키 저장 (fresh 세션으로 갱신)
        if total > 0 or True:  # 항상 저장
            print(f"\n  새 쿠키 저장 중...")
            COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2))
            new_ci = next((c for c in ctx.cookies() if c['name'] == 'ci_session_inquiry'), None)
            if new_ci:
                nd = urllib.parse.unquote(new_ci['value'])
                nm = re.search(r'"access_token";s:\d+:"([^"]+)"', nd)
                print(f"  저장된 access_token: {nm.group(1) if nm else '없음'}")

        print(f"\n  스크린샷:")
        for s in [shot3, shot4]:
            print(f"  - {s}")

        print(f"\n{'='*70}")
        print(f"[최종] Fresh 세션 결과: 총={total} / 답변완료={ans} / 조회완료={viewed}")
        if not ok:
            print(f"  → 추가 분석: 브라우저의 실제 ci_session_inquiry 값 확인 필요")
            print(f"  → 사용자 브라우저에서: DevTools → Application → Cookies → inquiry.withhive.com")
            print(f"  → ci_session_inquiry 값을 hive_cookies.json에 반영 필요")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
