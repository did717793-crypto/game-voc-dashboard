#!/usr/bin/env python3
"""
debug_fresh_session_v12.py — ci_session_inquiry 삭제 후 fresh 세션
===================================================================
[가설] 저장된 ci_session_inquiry의 access_token이 만료/다른 세션
       → 삭제 후 code= 파라미터로 새 세션 생성 시 답변완료/조회완료 접근 가능
[대조군] ci_session 보존 vs 삭제 후 재생성 비교
"""
import json, re, time, urllib.parse
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
EXPECTED = 19
SHOTS_DIR = SCRIPTS_DIR.parent / "data" / "screenshots"


def load_credentials():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return cfg["hive_id"], cfg["hive_pw"]


def load_cookies(ctx, exclude_names=None):
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text())
        if exclude_names:
            cookies = [c for c in cookies if c.get("name") not in exclude_names]
            print(f"  쿠키 로드 ({len(cookies)}개, 제외: {exclude_names})")
        else:
            print(f"  쿠키 로드 ({len(cookies)}개)")
        ctx.add_cookies(cookies)


def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2))
    print(f"  쿠키 저장 완료")


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


def run_search(hf, label, shots_dir=None, shot_name=None, page=None):
    """현재 hf 상태에서: 한국어 탭 → DKR 게임 → 날짜 설정 → 전체 상태 → 검색"""
    # 한국어 탭 클릭
    try:
        hf.evaluate("() => { var a = document.querySelector('a[href*=\"lang=0014010001\"]'); if(a) a.click(); }")
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(4)
    except Exception as e:
        print(f"  탭 클릭 실패: {e}")

    # 게임 선택
    try:
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=3_000)
    except Exception:
        hf.evaluate(f"() => {{ var s = document.querySelector('select[name=\"sg\"]'); if(s) {{ s.value='{DKR_GAME_ID}'; s.dispatchEvent(new Event('change',{{bubbles:true}})); }} }}")

    # 날짜 설정
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

    # 전체 상태 선택
    hf.evaluate("() => document.querySelectorAll('input[name^=\"ss_\"]').forEach(function(c){c.checked=true;})")
    time.sleep(0.3)

    # 스크린샷 (클릭 직전)
    if page and shots_dir and shot_name:
        try:
            page.screenshot(path=str(shots_dir / f"{shot_name}_before.png"))
        except Exception:
            pass

    # 클릭
    hf.click("button#btn_submit", timeout=5_000, force=True)
    time.sleep(8)
    try:
        hf.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    time.sleep(3)

    # 스크린샷 (클릭 후)
    if page and shots_dir and shot_name:
        try:
            page.screenshot(path=str(shots_dir / f"{shot_name}_after.png"))
        except Exception:
            pass

    s = parse_status(hf)
    total = s.get("total", -1)
    ans = s.get("답변완료", 0); viewed = s.get("조회완료", 0); deleted = s.get("삭제", 0)
    ok = (total == EXPECTED and ans == 13 and viewed == 6)
    print(f"\n  [{label}] 총={total}  답변완료={ans}  조회완료={viewed}  삭제={deleted}")
    print(f"  판정: {'✅ 재현 성공!' if ok else '❌ 불일치'}")

    # ci_session 현재 값
    return s, ok


def run_test(pw, hid, hpw, use_ci=True, label=""):
    """use_ci=True: ci_session 보존 / False: 삭제 후 fresh"""
    print(f"\n{'='*60}")
    print(f"  테스트: {label}  (ci_session 보존={use_ci})")
    print(f"{'='*60}")

    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="ko-KR",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if use_ci:
        load_cookies(ctx)
    else:
        load_cookies(ctx, exclude_names=["ci_session_inquiry"])

    page = ctx.new_page()

    # 로그인
    page.goto(CONSOLE_MAIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(2)
    if "platform.withhive.com" in page.url:
        print("  재로그인 중...")
        do_login(page, ctx, hid, hpw)
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

    # ci_session 현재 값 확인
    cookies = ctx.cookies()
    ci = next((c for c in cookies if c['name'] == 'ci_session_inquiry'), None)
    if ci:
        decoded = urllib.parse.unquote(ci['value'])
        at_m = re.search(r'"access_token";s:\d+:"([^"]+)"', decoded)
        print(f"  access_token: {at_m.group(1) if at_m else '없음'}")
    else:
        print("  ci_session_inquiry: 없음 (fresh 세션 예정)")

    # HIVEframe 진입
    hf = None
    for _ in range(15):
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
        print("  ❌ HIVEframe 없음")
        browser.close()
        return {}

    print(f"  iframe: {hf.url}")
    time.sleep(5)
    hf.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(3)

    # ci_session 업데이트 여부 확인
    ci_after = next((c for c in ctx.cookies() if c['name'] == 'ci_session_inquiry'), None)
    if ci_after:
        decoded_after = urllib.parse.unquote(ci_after['value'])
        at_after = re.search(r'"access_token";s:\d+:"([^"]+)"', decoded_after)
        if ci:
            same = ci['value'] == ci_after['value']
            print(f"  ci_session 변경: {'동일' if same else '✅ 변경됨!'}")
            if not same and at_after:
                print(f"  새 access_token: {at_after.group(1)}")
        else:
            print(f"  새 ci_session 생성!")
            if at_after:
                print(f"  access_token: {at_after.group(1)}")

    # 검색 실행
    s, ok = run_search(
        hf, label,
        shots_dir=SHOTS_DIR,
        shot_name=f"v12_{'ci' if use_ci else 'fresh'}",
        page=page
    )

    browser.close()
    return s


def main():
    hid, hpw = load_credentials()

    print("="*70)
    print("  ci_session 보존 vs Fresh 세션 비교 v12")
    print(f"  쿼리: DKR(2474) / {START}~{END} / ss_1~7 ALL")
    print(f"  기준: 총19건 / 답변완료13 / 조회완료6")
    print("="*70)

    with sync_playwright() as pw:
        # 테스트 1: ci_session 보존 (현재 방식)
        s1 = run_test(pw, hid, hpw, use_ci=True,  label="CI보존 (기존 방식)")

        # 테스트 2: ci_session 삭제 후 fresh
        s2 = run_test(pw, hid, hpw, use_ci=False, label="CI삭제 후 Fresh")

    print(f"\n{'='*70}")
    print("[최종 비교]")
    for s, label in [(s1, "CI보존"), (s2, "CI삭제fresh")]:
        t = s.get("total",-1); a = s.get("답변완료",0); v = s.get("조회완료",0)
        ok = "✅" if (t == EXPECTED and a == 13) else "❌"
        print(f"  {ok} {label}: 총={t} 답변완료={a} 조회완료={v}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
