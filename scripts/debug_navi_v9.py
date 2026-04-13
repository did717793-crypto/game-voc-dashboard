#!/usr/bin/env python3
"""
debug_navi_v9.py — goto 없이 초기 프레임 세션 유지
=====================================================
[핵심 가설] code= 토큰은 최초 1회만 유효 → goto()로 재진입하면 소멸
[전략] console 진입 → iframe 자동 로드 대기 → goto() 절대 금지
       → JS로만 lang/game/date/status 변경 → 버튼 클릭 → 결과 읽기
[추가 체크]
  - 초기 frame URL의 lang/sg 기본값
  - 한국어 탭 링크 href 실제 값
  - 클릭 전후 요청 URL 전체 비교
"""

import json, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR    = Path(__file__).parent
CONFIG_FILE    = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE    = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
DKR_GAME_ID    = "2474"

START    = "2026-04-03"
END      = "2026-04-10"
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


def wait_result(hf, sec=25) -> dict:
    for _ in range(sec):
        time.sleep(1)
        s = parse_status(hf)
        if s.get("total", -1) >= 0:
            return s
    return {}


def show(s, label):
    t = s.get("total", -1)
    a = s.get("답변완료", 0); v = s.get("조회완료", 0); d = s.get("삭제", 0)
    ok = (t == EXPECTED and a == 13 and v == 6)
    print(f"\n  [{label}]  총={t}  답변완료={a}  조회완료={v}  삭제={d}")
    print(f"  판정: {'✅ 재현 성공!' if ok else '❌ 불일치'}")
    return ok


def main():
    hid, hpw = load_credentials()

    print("="*70)
    print(f"  goto 없이 세션 유지 v9  [{START} ~ {END}]")
    print(f"  [기준] 총19건 / 답변완료13 / 조회완료6")
    print("="*70)

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
        page.on("request", lambda r: req_log.append((r.method, r.url))
                if "inquiry.withhive.com/inquiry?" in r.url else None)

        # ── 로그인 ─────────────────────────────────────────────────────
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

        try:
            body = page.inner_text("body")
            m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w{2,}', body)
            print(f"  계정: {m.group(0) if m else '?'}")
        except Exception:
            print("  계정: ?")

        # ── HIVEframe 진입 (goto 없이) ────────────────────────────────
        print("\n[B] HIVEframe 자동 대기 (goto 금지)")
        hf = None
        for _ in range(20):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)
        if not hf:
            # 문의목록 메뉴 클릭 (frame은 console이 로드)
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try: page.click(sel, timeout=3_000); break
                except Exception: pass
            for _ in range(20):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break
        if not hf:
            print("  ❌ HIVEframe 없음"); browser.close(); return

        print(f"  ✅ frame URL: {hf.url}")
        code_m = re.search(r'[?&]code=([^&]+)', hf.url)
        print(f"  code= : '{code_m.group(1) if code_m else '없음'}'")

        # ── 초기 폼 상태 진단 ─────────────────────────────────────────
        time.sleep(5)  # 초기 로드 완료 대기
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        print(f"\n[C] 초기 폼 상태")
        init_form = hf.evaluate("""
            () => {
                var r = {};
                ['lang','sg','sds','sde','sdf','sd_date','spc','menu_cd','company_cd'].forEach(function(n) {
                    var el = document.querySelector('input[name="'+n+'"], select[name="'+n+'"]');
                    if (el) r[n] = el.value;
                });
                var ss = Array.from(document.querySelectorAll('input[name^="ss_"]'))
                              .map(function(c){return c.name+'='+c.checked;});
                r['ss_state'] = ss;
                r['frame_url'] = window.location.href;
                r['all_tabs'] = Array.from(document.querySelectorAll('.nav-tabs a, a[href*="lang="]'))
                                .map(function(a){ return {text: a.innerText.trim().slice(0,20), href: (a.href||'').slice(0,100)}; }).slice(0,10);
                return r;
            }
        """)
        for k, v in init_form.items():
            print(f"  {k}: {v}")

        s_init = parse_status(hf)
        print(f"  초기 건수: {s_init}")

        # ── 전략 A: 한국어 탭 실제 클릭 (goto 없이 탭 UI 클릭) ─────────
        print(f"\n{'─'*60}")
        print(f"[전략 A] 한국어 탭 클릭 (frame 내부) → 결과 대기 → 게임/날짜 설정 → 검색")
        req_log.clear()

        # 한국어 탭 찾기
        ko_tabs = hf.evaluate("""
            () => Array.from(document.querySelectorAll('a[href*="lang=0014010001"], a:contains("한국어")'))
                 .map(function(a){return {text: a.innerText.trim(), href: a.href||'', onclick: a.getAttribute('onclick')||''};})
        """)
        print(f"  한국어 탭 후보: {ko_tabs[:3]}")

        ko_clicked = False
        for sel in [
            "a[href*='lang=0014010001']",
            ".nav-tabs li a:first-child",
            "a:text('한국어')",
        ]:
            try:
                hf.click(sel, timeout=3_000, force=True)
                print(f"  탭 클릭: {sel}")
                ko_clicked = True
                hf.wait_for_load_state("networkidle", timeout=15_000)
                time.sleep(5)
                break
            except Exception as e:
                print(f"  실패({sel}): {str(e)[:60]}")

        if not ko_clicked:
            print("  ⚠ 한국어 탭 클릭 실패")

        # 탭 클릭 후 현재 lang 확인
        lang_now = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || 'not found'")
        print(f"  탭 클릭 후 lang: {lang_now}")
        s_after_tab = parse_status(hf)
        print(f"  탭 클릭 후 건수: {s_after_tab}")

        # 한국어 탭 건수 캡처된 요청 확인
        print(f"  탭 클릭으로 발생한 요청:")
        for m, u in req_log[:3]:
            print(f"    [{m}] {u}")

        # 게임 선택
        req_log.clear()
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        except Exception:
            hf.evaluate(f"""
                () => {{
                    var s = document.querySelector('select[name="sg"]');
                    if(s) {{ s.value='{DKR_GAME_ID}'; s.dispatchEvent(new Event('change',{{bubbles:true}})); }}
                }}
            """)
        time.sleep(0.5)

        # 날짜 설정
        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if(sdf) sdf.value = '{START} - {END}';
                if(sds) sds.value = '{START}';
                if(sde) sde.value = '{END}';
            }}
        """)

        # 상태 전체 선택
        hf.evaluate("() => document.querySelectorAll('input[name^=\"ss_\"]').forEach(function(c){c.checked=true;})")

        # 검색 직전 폼 확인
        pre_form = hf.evaluate("""
            () => ({
                lang: document.querySelector('input[name="lang"]')?.value||'',
                sg:   document.querySelector('select[name="sg"]')?.value||'',
                sds:  document.querySelector('input[name="sds"]')?.value||'',
                sde:  document.querySelector('input[name="sde"]')?.value||'',
                ss_checked: Array.from(document.querySelectorAll('input[name^="ss_"]:checked')).length
            })
        """)
        print(f"  검색 직전 폼: {pre_form}")

        # 버튼 클릭
        req_log.clear()
        hf.click("button#btn_submit", timeout=5_000, force=True)
        sA = wait_result(hf, sec=25)

        # 실제 요청 URL 전체 출력
        print(f"  버튼 클릭 후 요청:")
        for m, u in req_log[:3]:
            print(f"    [{m}] {u}")

        okA = show(sA, "전략A: 탭클릭 후 검색")

        # ── 전략 B: 초기 URL 그대로 + JS로 lang 강제 + submit() ──────
        print(f"\n{'─'*60}")
        print(f"[전략 B] 초기 URL 유지 + lang JS 강제 + form submit()")

        # 페이지 새로 고침 (console.withhive.com/main/ 재로드)
        # → iframe이 새 code로 다시 초기화됨
        page.reload()
        page.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(3)

        hf2 = None
        for _ in range(15):
            hf2 = find_inquiry_frame(page)
            if hf2: break
            time.sleep(1)
        if not hf2:
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try: page.click(sel, timeout=3_000); break
                except Exception: pass
            for _ in range(20):
                time.sleep(1)
                hf2 = find_inquiry_frame(page)
                if hf2: break

        if hf2:
            print(f"  frame URL: {hf2.url}")
            time.sleep(5)
            hf2.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)

            s_init2 = parse_status(hf2)
            print(f"  초기 건수: {s_init2}")

            # 모든 설정 한 번에
            setup_result = hf2.evaluate(f"""
                () => {{
                    // lang 한국어
                    var langInp = document.querySelector('input[name="lang"]');
                    if(langInp) langInp.value = '0014010001';

                    // game 선택
                    var sgSel = document.querySelector('select[name="sg"]');
                    if(sgSel) sgSel.value = '{DKR_GAME_ID}';

                    // 날짜
                    ['sdf','sds','sde'].forEach(function(n,i) {{
                        var el = document.querySelector('input[name="'+n+'"]');
                        var vals = ['{START} - {END}', '{START}', '{END}'];
                        if(el) el.value = vals[i];
                    }});

                    // 상태 전체
                    document.querySelectorAll('input[name^="ss_"]').forEach(function(c){{c.checked=true;}});
                    document.querySelectorAll('input[name^="sf_"]').forEach(function(c){{c.checked=true;}});

                    // sd_date
                    var sdInp = document.querySelector('input[name="sd_date"]');
                    if(sdInp) sdInp.value = 'st';

                    // 확인
                    return {{
                        lang: langInp ? langInp.value : 'none',
                        sg:   sgSel  ? sgSel.value   : 'none',
                        sds:  document.querySelector('input[name="sds"]')?.value||'',
                        sde:  document.querySelector('input[name="sde"]')?.value||''
                    }};
                }}
            """)
            print(f"  JS 설정: {setup_result}")

            req_log.clear()
            hf2.click("button#btn_submit", timeout=5_000, force=True)
            sB = wait_result(hf2, sec=25)

            print(f"  클릭 후 요청:")
            for m, u in req_log[:3]:
                print(f"    [{m}] {u}")

            okB = show(sB, "전략B: 리로드 후 lang JS 강제")

            # 성공이면 row 덤프
            if okB:
                rows = hf2.evaluate("""
                    () => {
                        var r = [];
                        document.querySelectorAll('#table_dataList tbody tr').forEach(function(row) {
                            var cells = Array.from(row.querySelectorAll('td')).map(function(c){return c.innerText.trim().replace(/\\s+/g,' ');});
                            if(cells.length > 5) r.push(cells);
                        });
                        return r;
                    }
                """)
                print(f"  rows: {len(rows)}개")
                for i, row in enumerate(rows[:10]):
                    print(f"  row[{i+1}]: no={row[1] if len(row)>1 else '?'}  status={row[9] if len(row)>9 else '?'}  date={row[7] if len(row)>7 else '?'}")
        else:
            sB = {}
            okB = False
            print("  ❌ frame2 없음")

        # ── 최종 요약 ──────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print("[최종 요약]")
        for s, label in [(sA,"전략A(탭클릭)"), (sB,"전략B(리로드+JS)")]:
            t = s.get("total",-1); a = s.get("답변완료",0); v = s.get("조회완료",0)
            ok = "✅" if (t == EXPECTED and a == 13) else "❌"
            print(f"  {ok} {label}: 총={t} 답변완료={a} 조회완료={v}")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
