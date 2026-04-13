#!/usr/bin/env python3
"""
debug_deep_v5.py — 심층 진단
==============================
[목적] 0건 원인 규명: 폼 POST/GET 구조 / 실제 계정 / 쿠키 도메인 / 전체 HTML 덤프
[신규 체크]
  1. 로그인된 실제 계정 이메일
  2. 폼 method 확인 (GET vs POST)
  3. 프레임 레벨 request 캡처 (page 레벨 한계 극복)
  4. 응답 body까지 읽어서 실제 데이터 존재 여부 확인
  5. 전체 tbody 행수 (날짜 필터 없이)
  6. POST 방식으로 직접 검색 시도
"""

import json, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR    = Path(__file__).parent
CONFIG_FILE    = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE    = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"
DKR_GAME_ID    = "2474"
KST            = timezone(timedelta(hours=9))

DEBUG_MODE  = True
START_DATE  = "2026-04-03"
END_DATE    = "2026-04-10"


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


def parse_count(hf) -> int:
    try:
        body = hf.inner_text("body")
        m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
        return int(m.group(1).replace(',', '')) if m else -1
    except Exception:
        return -1


def main():
    hid, hpw = load_credentials()

    print("=" * 70)
    print(f"  심층 진단 v5  [{START_DATE} ~ {END_DATE}]")
    print("=" * 70)

    all_requests = []   # (url, method, post_data)
    all_responses = []  # (url, status, content_type)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        load_cookies(ctx)

        # ── 모든 요청 캡처 (CDPSession 수준) ─────────────────────────────
        def on_request(req):
            if "withhive.com" in req.url:
                try:
                    pd = req.post_data or ""
                except Exception:
                    pd = ""
                all_requests.append((req.url, req.method, pd[:300]))

        def on_response(res):
            if "inquiry.withhive.com" in res.url:
                ct = res.headers.get("content-type", "")
                all_responses.append((res.url, res.status, ct))

        page = ctx.new_page()
        page.on("request",  on_request)
        page.on("response", on_response)

        # ─── [A] 로그인 확인 ───────────────────────────────────────────
        print("\n[A] 로그인 확인")
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
        account_email = ""
        for sel in [".user-email", ".account-email", "span.email", "[class*='email']",
                    "[class*='user']", ".userInfo", "#userInfo", ".header-user"]:
            try:
                txt = page.locator(sel).first.inner_text(timeout=2_000).strip()
                if "@" in txt:
                    account_email = txt
                    break
            except Exception:
                pass
        if not account_email:
            try:
                body_txt = page.inner_text("body")
                m = re.search(r'[\w.\-]+@[\w.\-]+\.\w+', body_txt)
                account_email = m.group(0) if m else "추출 실패"
            except Exception:
                account_email = "추출 실패"

        print(f"  ✅ 로그인 계정: {account_email}")
        print(f"  URL: {page.url}")

        # 쿠키 도메인 확인
        cookies = ctx.cookies()
        domains = set(c["domain"] for c in cookies)
        print(f"  쿠키 도메인: {sorted(domains)}")
        inquiry_cookies = [c for c in cookies if "inquiry" in c.get("domain","")]
        console_cookies = [c for c in cookies if "console" in c.get("domain","")]
        print(f"  inquiry 쿠키 {len(inquiry_cookies)}개 / console 쿠키 {len(console_cookies)}개")

        # ─── [B] HIVEframe 진입 ────────────────────────────────────────
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
            page.evaluate(f"() => {{ var el = document.querySelector('#consoleContents, iframe[name=\"HIVEframe\"]'); if(el) el.src = '{INQUIRY_BASE}'; }}")
            for _ in range(15):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break

        if not hf:
            print("  ❌ HIVEframe 진입 실패")
            browser.close(); return
        print(f"  ✅ frame URL: {hf.url}")

        # ─── [C] 한국어 탭 로드 ───────────────────────────────────────
        print("\n[C] 한국어 탭 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # ─── [D] 폼 구조 분석 ─────────────────────────────────────────
        print("\n[D] 폼 구조 분석 (매우 중요)")
        form_info = hf.evaluate("""
            () => {
                var forms = document.querySelectorAll('form');
                var result = [];
                forms.forEach(function(f) {
                    var inputs = Array.from(f.querySelectorAll('input, select')).map(function(el) {
                        return {name: el.name, type: el.type, value: el.value, tagName: el.tagName};
                    });
                    result.push({
                        id: f.id,
                        method: f.method,
                        action: f.action,
                        inputCount: inputs.length,
                        inputs: inputs.slice(0, 30)
                    });
                });
                return result;
            }
        """)
        for fi in form_info:
            print(f"  form#{fi.get('id','')} method={fi.get('method','?').upper()} action={fi.get('action','?')[:80]}")
            print(f"    input/select 수: {fi.get('inputCount',0)}")
            for inp in fi.get('inputs', []):
                n = inp.get('name',''); v = inp.get('value',''); t = inp.get('type',''); tag = inp.get('tagName','')
                if n:
                    print(f"    [{tag}] name={n:20s} type={t:10s} value={str(v)[:40]}")

        # ─── [E] 게임 선택 + 날짜 설정 ────────────────────────────────
        print(f"\n[E] DKR(2474) 선택 + 날짜 {START_DATE}~{END_DATE}")
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        except Exception as e:
            print(f"  게임 선택 예외: {e}")

        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START_DATE} - {END_DATE}';
                if (sds) sds.value = '{START_DATE}';
                if (sde) sde.value = '{END_DATE}';
            }}
        """)
        time.sleep(0.5)

        # 상태 체크박스 전체 선택 시도 (jQuery trigger 포함)
        hf.evaluate("""
            () => {
                var checkboxes = document.querySelectorAll('input[name^="ss_"]');
                checkboxes.forEach(function(cb) {
                    cb.checked = true;
                    cb.setAttribute('checked', 'checked');
                    // jQuery trigger
                    if (window.jQuery) {
                        jQuery(cb).prop('checked', true).trigger('change');
                    }
                });
                console.log('상태 체크박스 강제 체크 완료:', checkboxes.length);
            }
        """)

        # 체크 상태 확인
        cb_state = hf.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('input[name^="ss_"]')).map(function(cb) {
                    return {name: cb.name, checked: cb.checked, value: cb.value};
                });
            }
        """)
        print(f"  ss_* 체크박스 상태: {cb_state}")

        # 폼 전체 input 현재 값
        form_vals = hf.evaluate("""
            () => {
                var r = {};
                document.querySelectorAll('input, select').forEach(function(el) {
                    if (el.name) {
                        if (el.type === 'checkbox') {
                            if (!r[el.name]) r[el.name] = [];
                            if (el.checked) r[el.name].push(el.value || 'on');
                        } else {
                            r[el.name] = el.value;
                        }
                    }
                });
                return r;
            }
        """)
        print(f"\n  검색 직전 폼 값:")
        for k, v in sorted(form_vals.items()):
            print(f"    {k:25s} = {str(v)[:60]}")

        # ─── [F] 검색 실행 (버튼 클릭) ────────────────────────────────
        print(f"\n[F] 검색 버튼 클릭")
        all_requests.clear()
        all_responses.clear()

        # 클릭 직전 건수
        count_before = parse_count(hf)
        print(f"  클릭 전 건수: {count_before}건")

        # 버튼 확인
        btn_info = hf.evaluate("""
            () => {
                var btns = document.querySelectorAll('button, input[type="button"], input[type="submit"]');
                return Array.from(btns).map(function(b) {
                    var r = b.getBoundingClientRect();
                    return {
                        tag: b.tagName, id: b.id, cls: b.className,
                        text: b.innerText || b.value || '',
                        x: r.left + r.width/2, y: r.top + r.height/2,
                        w: r.width, h: r.height,
                        visible: r.width > 0 && r.height > 0
                    };
                });
            }
        """)
        print(f"  버튼 목록:")
        for b in btn_info:
            print(f"    [{b['tag']}#{b.get('id','')}] '{b.get('text','')[:20]}' x={b['x']:.0f} y={b['y']:.0f} w={b['w']:.0f} h={b['h']:.0f} visible={b['visible']}")

        # 클릭 시도 - btn_submit
        clicked = False
        for selector in ["button#btn_submit", "button[id*='submit']", "button:text('검색')", "input[type='submit']"]:
            try:
                hf.scroll_into_view_if_needed(selector, timeout=3_000)
                hf.click(selector, timeout=5_000, force=True)
                print(f"  클릭 성공: {selector}")
                clicked = True
                break
            except Exception as e:
                print(f"  클릭 실패 ({selector}): {str(e)[:60]}")

        if not clicked:
            # bounding box 클릭
            for b in btn_info:
                if b.get('visible') and ('submit' in b.get('id','').lower() or '검색' in b.get('text','')):
                    hf.mouse.click(b['x'], b['y'])
                    print(f"  bounding box 클릭: {b}")
                    clicked = True
                    break

        # 결과 대기 (최대 30초)
        print(f"  결과 대기 중 (최대 30초)...")
        count_after = -1
        count_text  = ""
        for i in range(30):
            time.sleep(1)
            c = parse_count(hf)
            if c >= 0:
                count_after = c
                try:
                    count_text = hf.evaluate("""
                        () => {
                            var m = document.body.innerText.match(/검색 건수.{0,200}/);
                            return m ? m[0].replace(/\\n/g,' ').trim() : '';
                        }
                    """)
                except Exception:
                    count_text = f"검색 건수 : {c}"
                if i >= 2:
                    break
            if (i+1) % 5 == 0:
                print(f"  {i+1}초... 현재: {c}건")

        print(f"\n  검색 후 건수: {count_after}건")
        print(f"  건수 원문: {count_text[:200]}")

        # ─── [G] 캡처된 실제 요청 분석 ─────────────────────────────────
        print(f"\n[G] 캡처된 withhive.com 요청 ({len(all_requests)}개)")
        for url, method, pd in all_requests[-10:]:
            if "inquiry" in url or "platform" in url or "console" in url:
                print(f"  [{method}] {url[:150]}")
                if pd:
                    print(f"    POST data: {pd[:200]}")

        print(f"\n  inquiry 응답 ({len(all_responses)}개):")
        for url, status, ct in all_responses[-10:]:
            print(f"  [{status}] {ct[:40]} {url[:120]}")

        # ─── [H] 테이블 전체 덤프 ─────────────────────────────────────
        print(f"\n[H] 테이블 전체 분석")
        table_info = hf.evaluate("""
            () => {
                var tables = document.querySelectorAll('table');
                var result = [];
                tables.forEach(function(t, ti) {
                    var rows = t.querySelectorAll('tbody tr');
                    var sample = [];
                    rows.forEach(function(r, ri) {
                        if (ri < 3) {
                            sample.push(Array.from(r.querySelectorAll('td')).map(function(c) {
                                return c.innerText.trim().replace(/\\s+/g,' ');
                            }));
                        }
                    });
                    result.push({
                        tableIndex: ti,
                        id: t.id,
                        className: t.className,
                        rowCount: rows.length,
                        headerText: (t.querySelector('thead') || {innerText: ''}).innerText.replace(/\\n/g,' ').trim().slice(0,80),
                        sample: sample
                    });
                });
                return result;
            }
        """)
        for ti in table_info:
            print(f"\n  table[{ti['tableIndex']}] #{ti.get('id','')} .{ti.get('className','')[:30]}")
            print(f"    tbody 행수: {ti.get('rowCount',0)}")
            print(f"    헤더: {ti.get('headerText','')[:60]}")
            for ri, row in enumerate(ti.get('sample',[])):
                print(f"    row[{ri}]: {row[:6]}")

        # ─── [I] 전체 페이지 주요 텍스트 ─────────────────────────────
        print(f"\n[I] 페이지 주요 텍스트 (1000자)")
        try:
            body_text = hf.inner_text("body")
            # 검색 건수 주변 500자
            m = re.search(r'.{0,100}검색 건수.{0,400}', body_text, re.DOTALL)
            if m:
                print(f"  [검색건수 주변]\n  {m.group(0)[:500].replace(chr(10),' ')}")
            else:
                print(f"  [body 앞 1000자]\n  {body_text[:1000].replace(chr(10),' ')}")
        except Exception as e:
            print(f"  추출 실패: {e}")

        # ─── [J] Phase 2: URL 직접 goto + 추가 대기 ───────────────────
        print(f"\n[J] Phase 2: URL 직접 구성 (ss_1~ss_7, 10초 대기)")

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

        all_requests.clear()
        all_responses.clear()

        hf.goto(DIRECT_URL, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        print(f"  goto 완료: {hf.url[:120]}")
        time.sleep(5)

        p2_count = parse_count(hf)
        for i in range(10):
            time.sleep(1)
            c = parse_count(hf)
            if c >= 0:
                p2_count = c
                break

        p2_text = ""
        try:
            p2_text = hf.evaluate("""
                () => {
                    var m = document.body.innerText.match(/검색 건수.{0,300}/);
                    return m ? m[0].replace(/\\n/g,' ').trim() : document.body.innerText.slice(0, 500);
                }
            """)
        except Exception:
            pass

        print(f"\n  Phase 2 결과: {p2_count}건")
        print(f"  건수 원문: {p2_text[:300]}")

        # Phase 2 테이블
        p2_table = hf.evaluate("""
            () => {
                var rows = document.querySelectorAll('table tbody tr');
                var all = [];
                rows.forEach(function(r) {
                    var cells = Array.from(r.querySelectorAll('td')).map(function(c) {
                        return c.innerText.trim().replace(/\\s+/g,' ');
                    });
                    all.push(cells);
                });
                return {count: rows.length, rows: all.slice(0,5)};
            }
        """)
        print(f"  tbody 행수: {p2_table.get('count',0)}")
        for ri, row in enumerate(p2_table.get('rows',[])):
            print(f"  row[{ri}]: {row[:8]}")

        # Phase 2 요청 캡처
        print(f"\n  캡처된 inquiry 요청:")
        for url, method, pd in all_requests:
            if "inquiry.withhive.com" in url:
                print(f"  [{method}] {url[:200]}")
                if pd:
                    print(f"    POST: {pd[:200]}")

        # ─── [K] POST 방식 시도 ────────────────────────────────────────
        print(f"\n[K] POST 방식 직접 시도 (JavaScript fetch)")
        post_result = hf.evaluate(f"""
            async () => {{
                try {{
                    var params = new URLSearchParams({{
                        menu_cd: '415', company_cd: '342',
                        lang: '0014010001',
                        sg: '{DKR_GAME_ID}',
                        sc: '-1', sc2: '-1', sc3: '-1', qs: '', si: '-1',
                        sa: '-1', detail_sc: '-1', gsi: '-1',
                        ss_1: 'on', ss_2: 'on', ss_3: 'on', ss_4: 'on',
                        ss_5: 'on', ss_6: 'on', ss_7: 'on',
                        sf_1: 'on', sf_2: 'on', sf_3: 'on', sf_4: 'on',
                        sf_5: 'on', sf_6: 'on', sf_7: 'on', sf_8: 'on', sf_9: 'on',
                        sdf: '{START_DATE} - {END_DATE}',
                        sds: '{START_DATE}', sde: '{END_DATE}',
                        sst: '-1', stx: '',
                        agent: '-1', modiCompany: '-1', modiLanguage: '-1',
                        sd_date: 'st', spc: '50', page: '1'
                    }});
                    var res = await fetch('https://inquiry.withhive.com/inquiry?' + params.toString(), {{
                        method: 'GET',
                        credentials: 'include',
                        headers: {{'Accept': 'text/html,application/xhtml+xml'}}
                    }});
                    var text = await res.text();
                    var m = text.match(/검색 건수.{{0,100}}/);
                    return {{
                        status: res.status,
                        url: res.url,
                        count_match: m ? m[0] : '없음',
                        body_snippet: text.slice(0, 500)
                    }};
                }} catch(e) {{
                    return {{error: e.toString()}};
                }}
            }}
        """)
        print(f"  fetch 결과: {json.dumps(post_result, ensure_ascii=False, indent=2)[:500]}")

        # ─── [L] 최종 요약 ────────────────────────────────────────────
        print(f"\n{'='*70}")
        print(f"[최종 요약]")
        print(f"  로그인 계정    : {account_email}")
        print(f"  Phase 1 (버튼) : {count_after}건  원문: {count_text[:80]}")
        print(f"  Phase 2 (URL)  : {p2_count}건  원문: {p2_text[:80]}")
        print(f"  판정           : {'✅ 재현 성공' if (count_after > 0 or p2_count > 0) else '❌ 재현 실패 — 추가 분석 필요'}")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
