#!/usr/bin/env python3
"""
debug_auth_v10.py — localStorage/세션 인증 상태 확인
=====================================================
[신규 가설] 브라우저 세션에는 localStorage 기반 추가 인증 토큰 존재
            쿠키만 복사하면 답변완료/조회완료 데이터 접근 불가
[체크 항목]
  1. localStorage 전체 (inquiry.withhive.com)
  2. 한국어 탭 기본 상태 (ss 기본값 그대로 + 게임/날짜만 설정)
  3. 기본 ss (ss_1+ss_2 only) 검색 결과
  4. ss_3+ss_6 추가 후 결과 비교
  5. 동일 요청 fetch() 재시도 결과
"""

import json, re, time
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


def wait_result(hf, sec=20) -> dict:
    for _ in range(sec):
        time.sleep(1)
        s = parse_status(hf)
        if s.get("total", -1) >= 0:
            return s
    return {"total": -1}


def show(s, label):
    t = s.get("total", -1); a = s.get("답변완료", 0)
    v = s.get("조회완료", 0); d = s.get("삭제", 0)
    ok = (t == EXPECTED and a == 13 and v == 6)
    print(f"\n  [{label}]  총={t}  답변완료={a}  조회완료={v}  삭제={d}  관리자삭제={s.get('관리자삭제',0)}")
    print(f"  판정: {'✅ 재현 성공!' if ok else f'❌ 불일치 (기대: {EXPECTED}건, 답변완료:13, 조회완료:6)'}")
    return ok


def main():
    hid, hpw = load_credentials()
    req_log = []

    print("="*70)
    print(f"  인증 상태 확인 v10  [{START} ~ {END}]")
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
        page.on("request", lambda r: req_log.append((r.method, r.url))
                if "inquiry.withhive.com/inquiry?" in r.url else None)

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

        # 계정
        try:
            body = page.inner_text("body")
            m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w{2,}', body)
            print(f"  계정: {m.group(0) if m else '?'}")
        except Exception:
            print("  계정: ?")

        # console localStorage 확인
        console_ls = page.evaluate("""
            () => {
                try {
                    var r = {};
                    for(var i=0; i<localStorage.length; i++) {
                        var k = localStorage.key(i);
                        var v = localStorage.getItem(k);
                        r[k] = v && v.length > 200 ? v.slice(0,200)+'...(truncated)' : v;
                    }
                    return r;
                } catch(e) { return {error: e.toString()}; }
            }
        """)
        print(f"\n  console.withhive.com localStorage ({len(console_ls)}개 키):")
        for k, v in list(console_ls.items())[:10]:
            print(f"    {k}: {str(v)[:100]}")

        # ── HIVEframe 진입 ─────────────────────────────────────────────
        print("\n[B] HIVEframe 진입")
        hf = None
        for _ in range(20):
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
            print("  ❌"); browser.close(); return
        print(f"  ✅ {hf.url}")

        # frame 로드 대기
        time.sleep(5)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # inquiry.withhive.com localStorage 확인
        inq_ls = hf.evaluate("""
            () => {
                try {
                    var r = {};
                    for(var i=0; i<localStorage.length; i++) {
                        var k = localStorage.key(i);
                        var v = localStorage.getItem(k);
                        r[k] = v && v.length > 200 ? v.slice(0,200)+'...' : v;
                    }
                    return r;
                } catch(e) { return {error: e.toString()}; }
            }
        """)
        print(f"\n[C] inquiry.withhive.com localStorage ({len(inq_ls)}개 키):")
        for k, v in inq_ls.items():
            print(f"  {k}: {str(v)[:120]}")

        # sessionStorage 확인
        inq_ss = hf.evaluate("""
            () => {
                try {
                    var r = {};
                    for(var i=0; i<sessionStorage.length; i++) {
                        var k = sessionStorage.key(i);
                        r[k] = sessionStorage.getItem(k);
                    }
                    return r;
                } catch(e) { return {error: e.toString()}; }
            }
        """)
        print(f"\n  inquiry.withhive.com sessionStorage ({len(inq_ss)}개 키):")
        for k, v in list(inq_ss.items())[:10]:
            print(f"  {k}: {str(v)[:120]}")

        # 전체 쿠키 (inquiry 도메인)
        all_cookies = ctx.cookies()
        inq_cookies = [c for c in all_cookies if "withhive" in c.get("domain","")]
        print(f"\n  withhive.com 쿠키 ({len(inq_cookies)}개):")
        for c in inq_cookies:
            print(f"  {c['domain']} | {c['name']} = {str(c['value'])[:80]}")

        # ── 초기 상태 확인 ─────────────────────────────────────────────
        s_init = parse_status(hf)
        print(f"\n  초기 상태 (내 상담 탭): {s_init}")
        init_url = hf.url

        # ── 한국어 탭 클릭 (첫 번째 방식) ──────────────────────────────
        print(f"\n[D] 한국어 탭 클릭 → 초기 결과 확인")
        req_log.clear()
        try:
            # tab href를 JS로 navigate (frame 내 href click)
            hf.evaluate("""
                () => {
                    var a = document.querySelector('a[href*="lang=0014010001"]');
                    if(a) a.click();
                }
            """)
            hf.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(5)
        except Exception as e:
            print(f"  탭 클릭 실패: {e}")

        ko_init = parse_status(hf)
        print(f"  한국어 탭 초기 상태: {ko_init}")

        # 한국어 탭에서 요청 확인
        for m, u in req_log[:3]:
            print(f"  [{m}] {u}")

        # 현재 lang 값
        lang_now = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || '?'")
        ss_now = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                  .map(function(c){return {name:c.name, checked:c.checked};})
        """)
        print(f"  lang={lang_now}")
        print(f"  ss_* 기본값: {ss_now}")

        # ── 기본 ss_1+ss_2만으로 DKR 7일 검색 ─────────────────────────
        print(f"\n[E] 기본 ss(ss_1+ss_2 only) + DKR + {START}~{END}")
        req_log.clear()

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
                var sdf = document.querySelector('input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if(sdf) sdf.value = '{START} - {END}';
                if(sds) sds.value = '{START}';
                if(sde) sde.value = '{END}';
            }}
        """)

        hf.click("button#btn_submit", timeout=5_000, force=True)
        sE = wait_result(hf, sec=20)

        for m, u in req_log[:2]:
            print(f"  [{m}] {u}")
        show(sE, f"기본ss+DKR+{START}~{END}")

        # ── ss_3(답변완료) + ss_6(조회완료) 추가 ──────────────────────
        print(f"\n[F] ss_3+ss_6 추가 후 재검색 (답변완료/조회완료 포함)")
        req_log.clear()

        hf.evaluate("""
            () => {
                ['ss_3','ss_6'].forEach(function(n){
                    var el = document.querySelector('input[name="'+n+'"]');
                    if(el) el.checked = true;
                });
            }
        """)
        hf.click("button#btn_submit", timeout=5_000, force=True)
        sF = wait_result(hf, sec=20)
        for m, u in req_log[:2]:
            print(f"  [{m}] {u}")
        show(sF, "ss_1+ss_2+ss_3+ss_6 (답변완료/조회완료 추가)")

        # ── 전체 ss 선택 ──────────────────────────────────────────────
        print(f"\n[G] 전체 ss (ss_1~ss_7 ALL) 검색")
        req_log.clear()

        hf.evaluate("""
            () => document.querySelectorAll('input[name^="ss_"]').forEach(function(c){c.checked=true;})
        """)
        hf.click("button#btn_submit", timeout=5_000, force=True)
        sG = wait_result(hf, sec=20)
        for m, u in req_log[:2]:
            print(f"  [{m}] {u}")
        show(sG, "ss_1~7 ALL")

        # ── 날짜 범위 확장 테스트 ──────────────────────────────────────
        print(f"\n[H] 날짜 범위별 테스트 (lang=한국어, DKR, ss_1~7)")

        for s_date, e_date, label in [
            ("2026-04-03", "2026-04-10", "7일"),
            ("2026-03-11", "2026-04-10", "1개월(기본)"),
            ("2026-01-01", "2026-04-10", "3.5개월"),
        ]:
            req_log.clear()
            hf.evaluate(f"""
                () => {{
                    var sdf = document.querySelector('input[name="sdf"]');
                    var sds = document.querySelector('input[name="sds"]');
                    var sde = document.querySelector('input[name="sde"]');
                    if(sdf) sdf.value = '{s_date} - {e_date}';
                    if(sds) sds.value = '{s_date}';
                    if(sde) sde.value = '{e_date}';
                    document.querySelectorAll('input[name^="ss_"]').forEach(function(c){{c.checked=true;}});
                }}
            """)
            hf.click("button#btn_submit", timeout=5_000, force=True)
            sx = wait_result(hf, sec=20)
            show(sx, label)

        # ── 최종 요약 ──────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print("[핵심 확인 사항]")
        print(f"  inquiry localStorage 키: {list(inq_ls.keys())}")
        print(f"  inquiry sessionStorage 키: {list(inq_ss.keys())}")
        print(f"  withhive 쿠키 수: {len(inq_cookies)}")
        print(f"  답변완료/조회완료 최종 확인 필요: 브라우저 vs 자동화 불일치 지속 시")
        print(f"  → 브라우저에서 실제 검색 시 네트워크 탭의 요청 헤더 비교 필요")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
