#!/usr/bin/env python3
"""
debug_deep_v6.py — 심층 진단 (Frame 메서드 오류 수정)
=======================================================
[핵심 추가]
  - Frame.click() 직접 사용 (scroll_into_view_if_needed / mouse 제거)
  - 모든 withhive.com 요청 캡처 (필터 없음)
  - sg 미선택일 경우(전체 게임)로도 테스트
  - 페이지 body 전체 텍스트 덤프
  - 로딩 대기: networkidle + 명시적 대기
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

START_DATE = "2026-04-03"
END_DATE   = "2026-04-10"


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


def parse_count(hf) -> tuple[int, str]:
    """(건수, 원문텍스트). 미확인이면 (-1, '')."""
    try:
        body = hf.inner_text("body")
        m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
        if m:
            c = int(m.group(1).replace(',', ''))
            ctx_m = re.search(r'.{0,20}검색.{0,100}', body)
            return c, (ctx_m.group(0).replace('\n', ' ').strip()[:100] if ctx_m else str(c))
    except Exception:
        pass
    return -1, ''


def dump_page(hf, label=""):
    """테이블 행수 + body 앞 2000자 + 검색건수 주변 출력."""
    try:
        body = hf.inner_text("body")
        print(f"\n  [{label}] body 길이={len(body)}자")
        # 검색건수 주변
        m = re.search(r'.{0,50}검색\s*건수.{0,300}', body, re.DOTALL)
        if m:
            print(f"  검색건수 컨텍스트:\n    {m.group(0)[:300].replace(chr(10),' ')}")
        else:
            print(f"  body 앞 500자:\n    {body[:500].replace(chr(10),' ')}")
    except Exception as e:
        print(f"  body 추출 실패: {e}")

    # 테이블 행수
    try:
        tbl = hf.evaluate("""
            () => {
                var tbls = document.querySelectorAll('table');
                return Array.from(tbls).map(function(t) {
                    return {id: t.id, rows: t.querySelectorAll('tbody tr').length};
                });
            }
        """)
        print(f"  테이블 행수: {tbl}")
    except Exception:
        pass


def main():
    hid, hpw = load_credentials()
    print("=" * 70)
    print(f"  심층 진단 v6  [{START_DATE} ~ {END_DATE}]")
    print("=" * 70)

    # 전역 요청 로그
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
        page.on("request", lambda r: req_log.append((r.method, r.url, r.post_data or "")) if "withhive" in r.url else None)

        # ── A. 로그인 ─────────────────────────────────────────────────
        print("\n[A] 로그인")
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        if "platform.withhive.com" in page.url:
            print("  세션 만료 → 재로그인")
            do_login(page, ctx, hid, hpw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)

        # 계정 이메일 추출
        account_email = "?"
        try:
            body = page.inner_text("body")
            m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w{2,}', body)
            if m: account_email = m.group(0)
        except Exception:
            pass
        print(f"  계정: {account_email}")
        print(f"  URL: {page.url}")

        # ── B. HIVEframe 진입 ─────────────────────────────────────────
        print("\n[B] HIVEframe 진입")
        hf = None
        for _ in range(10):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)
        if not hf:
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try:
                    page.click(sel, timeout=3_000); break
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
        print(f"  ✅ frame URL: {hf.url}")

        # ── C. 한국어 탭 + 초기 로드 ─────────────────────────────────
        print("\n[C] 한국어 탭 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)  # 초기 기본 검색 완료 대기

        c0, t0 = parse_count(hf)
        print(f"  초기 건수 (기본 날짜 범위): {c0}건  /  원문: {t0}")
        dump_page(hf, "초기 로드 후")

        # ── D. 게임 선택 (DKR=2474) ───────────────────────────────────
        print(f"\n[D] 게임 선택 DKR(2474)")
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
            sg_val = hf.evaluate("() => document.querySelector('select#search_game')?.value || '?'")
            print(f"  select 결과: {sg_val}  {'✅' if sg_val == DKR_GAME_ID else '❌'}")
        except Exception as e:
            print(f"  select_option 실패: {e}")
            # 대안: evaluate로 직접 value 설정
            hf.evaluate(f"""
                () => {{
                    var sel = document.querySelector('select[name="sg"], select#search_game');
                    if (sel) {{ sel.value = '{DKR_GAME_ID}'; sel.dispatchEvent(new Event('change', {{bubbles: true}})); }}
                }}
            """)
            sg_val = hf.evaluate("() => document.querySelector('select[name=\"sg\"]')?.value || '?'")
            print(f"  JS 직접 설정: {sg_val}")

        # ── E. 날짜 설정 ──────────────────────────────────────────────
        print(f"\n[E] 날짜 설정: {START_DATE} ~ {END_DATE}")
        hf.evaluate(f"""
            () => {{
                ['#search_date', 'input[name="sdf"]'].forEach(function(s) {{
                    var el = document.querySelector(s);
                    if (el) el.value = '{START_DATE} - {END_DATE}';
                }});
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sds) sds.value = '{START_DATE}';
                if (sde) sde.value = '{END_DATE}';
            }}
        """)
        time.sleep(0.3)
        dates = hf.evaluate("""
            () => ({
                sdf: document.querySelector('input[name="sdf"]')?.value || '',
                sds: document.querySelector('input[name="sds"]')?.value || '',
                sde: document.querySelector('input[name="sde"]')?.value || ''
            })
        """)
        print(f"  날짜 반영: {dates}")

        # ── F. 상태 체크박스 전체 선택 ────────────────────────────────
        print(f"\n[F] 상태 체크박스 전체 선택")
        hf.evaluate("""
            () => {
                document.querySelectorAll('input[name^="ss_"]').forEach(function(cb) {
                    cb.checked = true;
                });
                // jQuery trigger
                if (window.jQuery) {
                    jQuery('input[name^="ss_"]').prop('checked', true);
                }
            }
        """)
        cb_state = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                .map(function(c) { return c.name + '=' + c.checked; })
        """)
        print(f"  체크박스: {cb_state}")

        # ── G. 버튼 클릭 ──────────────────────────────────────────────
        print(f"\n[G] 검색 버튼 클릭")
        req_log.clear()  # 클릭 전 요청 초기화

        # btn_submit 존재 확인
        btn_exists = hf.evaluate("() => !!document.querySelector('button#btn_submit')")
        print(f"  btn#btn_submit 존재: {btn_exists}")

        clicked = False
        for method_name, fn in [
            ("Frame.click(force=True)",
             lambda: hf.click("button#btn_submit", timeout=5_000, force=True)),
            ("JS click()",
             lambda: hf.evaluate("() => document.querySelector('button#btn_submit')?.click()")),
            ("dispatchEvent",
             lambda: hf.evaluate("""
                 () => {
                     var b = document.querySelector('button#btn_submit');
                     if (b) b.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                 }
             """)),
            ("jQuery trigger submit",
             lambda: hf.evaluate("""
                 () => {
                     if (window.jQuery) {
                         jQuery('#search').submit();
                     }
                 }
             """)),
            ("form.submit()",
             lambda: hf.evaluate("() => document.querySelector('form#search')?.submit()")),
        ]:
            try:
                fn()
                time.sleep(0.5)
                clicked = True
                print(f"  클릭 방식: {method_name}")
                break
            except Exception as e:
                print(f"  실패({method_name}): {str(e)[:80]}")

        # 결과 대기 (30초)
        print(f"  결과 대기 중 (최대 30초)...")
        c1, t1 = -1, ''
        for i in range(30):
            time.sleep(1)
            c1, t1 = parse_count(hf)
            if c1 >= 0:
                print(f"  {i+1}초 후 {c1}건 확인")
                break
            if (i+1) % 5 == 0:
                print(f"  {i+1}초 경과... (아직 -1)")

        print(f"\n  ─ Phase 1 결과 ─")
        print(f"  건수: {c1}건")
        print(f"  원문: {t1}")
        dump_page(hf, "Phase 1 클릭 후")

        # 캡처된 요청 분석
        print(f"\n  [요청 캡처 — 클릭 후 withhive.com 전체]")
        for method, url, pd in req_log:
            print(f"  [{method}] {url[:200]}")
            if pd: print(f"    POST: {pd[:200]}")
        if not req_log:
            print(f"  ⚠ 캡처된 요청 없음 — 버튼이 실제로 눌리지 않았을 가능성")

        # ── H. Phase 2: URL 직접 goto ─────────────────────────────────
        print(f"\n[H] Phase 2: URL 직접 goto (ss_1~7 명시)")
        req_log.clear()

        DIRECT_URL = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342"
            "&lang=0014010001"
            f"&sg={DKR_GAME_ID}"
            "&sc=-1&sc2=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
            f"&sdf={START_DATE}+-+{END_DATE}"
            f"&sds={START_DATE}&sde={END_DATE}"
            "&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1&sd_date=st"
            "&spc=50&page=1"
        )
        print(f"  URL: {DIRECT_URL}")
        hf.goto(DIRECT_URL, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        c2, t2 = -1, ''
        for i in range(15):
            time.sleep(1)
            c2, t2 = parse_count(hf)
            if c2 >= 0:
                print(f"  {i+1}초 후 {c2}건 확인")
                break

        print(f"  건수: {c2}건")
        print(f"  원문: {t2}")
        dump_page(hf, "Phase 2 goto 후")

        # ── I. Phase 3: sg 없이 (전체 게임) 같은 날짜 ───────────────
        print(f"\n[I] Phase 3: sg=-1 (전체 게임) + 같은 날짜")
        req_log.clear()
        URL_NO_SG = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342"
            "&lang=0014010001"
            "&sg=-1"
            "&sc=-1&sc2=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
            f"&sdf={START_DATE}+-+{END_DATE}"
            f"&sds={START_DATE}&sde={END_DATE}"
            "&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1&sd_date=st"
            "&spc=50&page=1"
        )
        hf.goto(URL_NO_SG, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)
        c3, t3 = parse_count(hf)
        print(f"  건수(sg=-1): {c3}건  /  원문: {t3}")
        dump_page(hf, "Phase 3 전체게임")

        # ── J. Phase 4: 기본 날짜 범위 (서버 기본값) ─────────────────
        print(f"\n[J] Phase 4: 기본 날짜 (sds/sde 없이, sg=2474만)")
        URL_DEFAULT_DATE = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342"
            "&lang=0014010001"
            f"&sg={DKR_GAME_ID}"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&spc=50&page=1"
        )
        hf.goto(URL_DEFAULT_DATE, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)
        c4, t4 = parse_count(hf)
        print(f"  건수(기본날짜,DKR): {c4}건  /  원문: {t4}")
        dump_page(hf, "Phase 4 기본날짜")

        # ── K. Phase 5: 기본 날짜 + sg=-1 (모든 조건 최소화) ─────────
        print(f"\n[K] Phase 5: 기본 날짜 + sg=-1 (최소 조건)")
        URL_MIN = (
            "https://inquiry.withhive.com/inquiry?"
            "menu_cd=415&company_cd=342"
            "&lang=0014010001"
            "&sg=-1"
            "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
            "&spc=50&page=1"
        )
        hf.goto(URL_MIN, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)
        c5, t5 = parse_count(hf)
        print(f"  건수(최소조건): {c5}건  /  원문: {t5}")
        dump_page(hf, "Phase 5 최소조건")

        # ── L. JavaScript fetch로 직접 조회 ──────────────────────────
        print(f"\n[L] JavaScript fetch 직접 조회")
        fetch_res = hf.evaluate(f"""
            async () => {{
                try {{
                    var url = 'https://inquiry.withhive.com/inquiry?menu_cd=415&company_cd=342&lang=0014010001&sg={DKR_GAME_ID}&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on&sds={START_DATE}&sde={END_DATE}&sd_date=st&spc=50&page=1';
                    var res = await fetch(url, {{credentials: 'include', headers: {{'Accept': 'text/html'}}}});
                    var text = await res.text();
                    var m = text.match(/검색\\s*건수[\\s\\S]{{0,200}}/);
                    return {{
                        status: res.status,
                        final_url: res.url.slice(0, 200),
                        count_area: m ? m[0].replace(/\\n/g, ' ').slice(0, 200) : 'NOT FOUND',
                        body_start: text.slice(0, 300)
                    }};
                }} catch(e) {{ return {{error: e.toString()}}; }}
            }}
        """)
        print(f"  fetch 결과: {json.dumps(fetch_res, ensure_ascii=False, indent=2)[:600]}")

        # ── M. 최종 요약 ──────────────────────────────────────────────
        print(f"\n{'='*70}")
        print(f"[최종 요약]")
        print(f"  계정           : {account_email}")
        print(f"  Phase 1 (버튼클릭)  : {c1}건  원문: {t1[:60]}")
        print(f"  Phase 2 (직접URL/DKR): {c2}건  원문: {t2[:60]}")
        print(f"  Phase 3 (전체게임)  : {c3}건  원문: {t3[:60]}")
        print(f"  Phase 4 (기본날짜/DKR): {c4}건  원문: {t4[:60]}")
        print(f"  Phase 5 (최소조건)  : {c5}건  원문: {t5[:60]}")
        print(f"  판정: {'✅ 어떤 조합이 19건에 근접' if any(c > 10 for c in [c1,c2,c3,c4,c5]) else '❌ 전부 0건 — 근본 원인 추가 분석 필요'}")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
