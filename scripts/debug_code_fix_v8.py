#!/usr/bin/env python3
"""
debug_code_fix_v8.py — code= 파라미터 유지 전략
==================================================
[원인] hf.goto(KOREAN_TAB_URL) 시 초기 iframe URL의 code= 제거됨
       → console OAuth 인가 소실 → 답변완료/조회완료 데이터 접근 불가
[수정] code= 파라미터를 보존하면서 lang/sg/date 설정
[전략]
  A. code 유지 방식: 초기 URL에서 code 추출 → KOREAN_TAB_URL에 합성 후 goto
  B. 폼 JS 방식: goto 없이 초기 URL에서 form JS로만 필터 변경
  C. 초기 URL 유지 + 한국어탭 JS 전환 후 form submit
[검증 기준] 답변완료 13건 + 조회완료 6건 = 총 19건
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


def parse_status_bar(hf) -> dict:
    """검색 건수 요약바 파싱. 접수완료/처리중/답변완료/조회완료/삭제/관리자삭제 반환."""
    try:
        body = hf.inner_text("body")
        result = {"total": -1}
        patterns = {
            "total":    r'검색\s*건수\s*:?\s*([\d,]+)',
            "접수완료":  r'접수\s*완료\s*:?\s*([\d,]+)',
            "처리중":    r'처리\s*중\s*:?\s*([\d,]+)',
            "답변완료":  r'답변\s*완료\s*:?\s*([\d,]+)',
            "조회완료":  r'조회\s*완료\s*:?\s*([\d,]+)',
            "삭제":      r'(?<!\S)삭제\s*:?\s*([\d,]+)',
            "관리자삭제": r'관리자\s*삭제\s*:?\s*([\d,]+)',
        }
        for k, pat in patterns.items():
            m = re.search(pat, body)
            if m:
                result[k] = int(m.group(1).replace(',', ''))
        return result
    except Exception:
        return {"total": -1}


def wait_for_update(hf, timeout_sec=30) -> dict:
    """검색 결과 갱신 대기. 건수 딕셔너리 반환."""
    for i in range(timeout_sec):
        time.sleep(1)
        s = parse_status_bar(hf)
        if s.get("total", -1) >= 0:
            return s
    return {"total": -1}


def check_result(s: dict, label: str):
    total   = s.get("total", -1)
    ans     = s.get("답변완료", 0)
    viewed  = s.get("조회완료", 0)
    deleted = s.get("삭제", 0)
    print(f"\n  [{label}]")
    print(f"  검색건수: {total}건")
    print(f"  답변완료: {ans}  조회완료: {viewed}  삭제: {deleted}")
    ok = (total == EXPECTED and ans == 13 and viewed == 6)
    print(f"  판정: {'✅ 재현 성공!' if ok else '❌ 불일치 (기대: 19건, 답변완료:13, 조회완료:6)'}")
    return ok


def main():
    hid, hpw = load_credentials()
    print("=" * 70)
    print(f"  code= 파라미터 보존 검증 v8  [{START} ~ {END}]")
    print(f"  [기준값] 검색건수:19 / 답변완료:13 / 조회완료:6")
    print("=" * 70)

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

        # 계정 확인
        try:
            body = page.inner_text("body")
            m = re.search(r'[\w.+\-]+@[\w.\-]+\.\w{2,}', body)
            print(f"  계정: {m.group(0) if m else '?'}")
        except Exception:
            print("  계정: ?")

        # ── B. HIVEframe 진입 ─────────────────────────────────────────
        print("\n[B] HIVEframe 진입 (초기 code= 캡처)")
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

        # code= 추출
        initial_url = hf.url
        code_m = re.search(r'[?&]code=([^&]+)', initial_url)
        auth_code = code_m.group(1) if code_m else ""
        print(f"  ✅ 초기 URL: {initial_url}")
        print(f"  code= 파라미터: '{auth_code}'  {'✅ 발견' if auth_code else '❌ 없음'}")

        # 초기 상태 (code 유지, 기본 날짜/게임) 확인
        time.sleep(5)
        s_init = parse_status_bar(hf)
        print(f"  초기 상태: {s_init}")

        # ══════════════════════════════════════════════════════════════
        # 전략 1: code= 보존 + KOREAN_TAB_URL goto
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'─'*60}")
        print(f"[전략 1] code= 보존 goto (한국어탭 + code)")

        if auth_code:
            URL_WITH_CODE = (
                f"https://inquiry.withhive.com/inquiry?"
                f"menu_cd=415&page=1&lang=0014010001&company_cd=342&code={auth_code}"
            )
        else:
            URL_WITH_CODE = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"

        hf.goto(URL_WITH_CODE, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        s1_init = parse_status_bar(hf)
        print(f"  code 포함 탭 로드 결과: {s1_init}")

        # 게임 + 날짜 + 상태 설정
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        except Exception as e:
            print(f"  게임 선택 실패: {e}")

        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START} - {END}';
                if (sds) sds.value = '{START}';
                if (sde) sde.value = '{END}';
                document.querySelectorAll('input[name^="ss_"]').forEach(function(c){{c.checked=true;}});
            }}
        """)
        time.sleep(0.3)

        # 클릭
        hf.click("button#btn_submit", timeout=5_000, force=True)
        s1 = wait_for_update(hf, timeout_sec=20)
        check_result(s1, "전략1: code 보존 goto")

        # ══════════════════════════════════════════════════════════════
        # 전략 2: goto 하지 않고 초기 페이지에서 JS 전환
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'─'*60}")
        print(f"[전략 2] goto 없이 초기 페이지에서 JS로 한국어탭 전환 후 검색")

        # 초기 URL 재진입 (code 포함)
        if auth_code:
            INIT_URL = f"https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415&code={auth_code}"
        else:
            INIT_URL = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"

        hf.goto(INIT_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)

        # JS로 lang=한국어 설정 + 게임 + 날짜 + 상태 변경 후 submit
        result_js = hf.evaluate(f"""
            () => {{
                // 1) 언어 hidden input 한국어로 설정
                var langInp = document.querySelector('input[name="lang"]');
                if (langInp) {{
                    langInp.value = '0014010001';
                    langInp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}

                // 2) 게임 선택
                var sgSel = document.querySelector('select[name="sg"], select#search_game');
                if (sgSel) {{
                    sgSel.value = '{DKR_GAME_ID}';
                    sgSel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}

                // 3) 날짜 설정
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START} - {END}';
                if (sds) sds.value = '{START}';
                if (sde) sde.value = '{END}';

                // 4) 상태 전체 선택
                document.querySelectorAll('input[name^="ss_"]').forEach(function(c) {{ c.checked = true; }});

                // 5) sd_date=st 설정
                var sdInp = document.querySelector('input[name="sd_date"]');
                if (sdInp) sdInp.value = 'st';

                return {{
                    lang: langInp ? langInp.value : 'not found',
                    sg:   sgSel  ? sgSel.value   : 'not found',
                    sds:  sds    ? sds.value      : 'not found',
                    sde:  sde    ? sde.value      : 'not found'
                }};
            }}
        """)
        print(f"  JS 설정 결과: {result_js}")

        # 버튼 클릭
        hf.click("button#btn_submit", timeout=5_000, force=True)
        s2 = wait_for_update(hf, timeout_sec=20)
        check_result(s2, "전략2: goto 없이 JS 전환")

        # ══════════════════════════════════════════════════════════════
        # 전략 3: 한국어 탭 링크를 JS로 click (서버 측 탭 처리 유지)
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'─'*60}")
        print(f"[전략 3] 한국어 탭 링크 실제 클릭 → 게임/날짜 설정 → 검색")

        hf.goto(INIT_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # 한국어 탭 클릭 (실제 UI 탭)
        ko_tab_clicked = False
        for sel in [
            "a[href*='lang=0014010001']",
            "a:text('한국어')",
            "li.active a[href*='lang']",
            ".nav-tabs a:text('한국어')",
        ]:
            try:
                hf.click(sel, timeout=3_000, force=True)
                print(f"  한국어 탭 클릭: {sel}")
                ko_tab_clicked = True
                time.sleep(3)
                hf.wait_for_load_state("networkidle", timeout=10_000)
                time.sleep(2)
                break
            except Exception:
                pass

        if not ko_tab_clicked:
            print("  ⚠ 한국어 탭 클릭 실패 — 탭 링크 목록:")
            tabs = hf.evaluate("""
                () => Array.from(document.querySelectorAll('.nav-tabs a, .tab-nav a, [role="tab"]'))
                      .map(function(a) { return {text: a.innerText.trim(), href: a.href || a.getAttribute('href') || ''}; })
            """)
            for t in tabs[:10]:
                print(f"    {t}")

        # 탭 이동 후 lang 값 확인
        lang_val = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || 'not found'")
        print(f"  현재 lang: {lang_val}")

        # 게임 + 날짜 설정
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=3_000)
        except Exception:
            hf.evaluate(f"""
                () => {{
                    var s = document.querySelector('select[name="sg"]');
                    if(s) {{ s.value = '{DKR_GAME_ID}'; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}
                }}
            """)

        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START} - {END}';
                if (sds) sds.value = '{START}';
                if (sde) sde.value = '{END}';
                document.querySelectorAll('input[name^="ss_"]').forEach(function(c) {{ c.checked = true; }});
            }}
        """)

        hf.click("button#btn_submit", timeout=5_000, force=True)
        s3 = wait_for_update(hf, timeout_sec=20)
        check_result(s3, "전략3: 실제 탭 클릭 후 검색")

        # ══════════════════════════════════════════════════════════════
        # 전략 4: code= 포함 + lang 포함 직접 URL goto
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'─'*60}")
        print(f"[전략 4] code= + lang + sg + date 완전 직접 URL")

        if auth_code:
            DIRECT_FULL = (
                f"https://inquiry.withhive.com/inquiry?"
                f"menu_cd=415&company_cd=342&console_lang=ko"
                f"&lang=0014010001&code={auth_code}"
                f"&sg={DKR_GAME_ID}"
                f"&sc=-1&sc2=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
                f"&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
                f"&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
                f"&sdf={START}+-+{END}&sds={START}&sde={END}"
                f"&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1&sd_date=st"
                f"&spc=50&page=1"
            )
        else:
            DIRECT_FULL = (
                f"https://inquiry.withhive.com/inquiry?"
                f"menu_cd=415&company_cd=342"
                f"&lang=0014010001"
                f"&sg={DKR_GAME_ID}"
                f"&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
                f"&sds={START}&sde={END}&sd_date=st&spc=50&page=1"
            )

        hf.goto(DIRECT_FULL, timeout=20_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(5)
        s4 = wait_for_update(hf, timeout_sec=15)
        check_result(s4, "전략4: code + lang 완전 URL")

        # 성공한 전략이 있으면 첫 10 rows 덤프
        best = None
        for sx, label in [(s1,"전략1"), (s2,"전략2"), (s3,"전략3"), (s4,"전략4")]:
            if sx.get("total", -1) == EXPECTED:
                best = (sx, label)
                break

        if best:
            sx, label = best
            print(f"\n{'='*70}")
            print(f"  ✅ {label} 재현 성공! 첫 10 rows 덤프:")
            rows = hf.evaluate("""
                () => {
                    var result = [];
                    document.querySelectorAll('table#table_dataList tbody tr').forEach(function(row) {
                        var cells = Array.from(row.querySelectorAll('td')).map(function(c) {
                            return c.innerText.trim().replace(/\\s+/g,' ');
                        });
                        if (cells.length > 5) result.push(cells);
                    });
                    return result;
                }
            """)
            for i, row in enumerate(rows[:10]):
                print(f"  row[{i+1}]: 번호={row[1] if len(row)>1 else '?'}  상태={row[9] if len(row)>9 else '?'}  접수={row[7] if len(row)>7 else '?'}")

        # ── 최종 요약 ──────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print("[최종 요약]")
        print(f"  code= 파라미터: '{auth_code}'")
        for sx, label in [(s1,"전략1(code보존goto)"), (s2,"전략2(JS전환)"), (s3,"전략3(탭클릭)"), (s4,"전략4(full URL)")]:
            total   = sx.get("total", -1)
            ans     = sx.get("답변완료", 0)
            viewed  = sx.get("조회완료", 0)
            deleted = sx.get("삭제", 0)
            ok = "✅" if (total == EXPECTED and ans == 13) else "❌"
            print(f"  {ok} {label}: 총={total} 답변완료={ans} 조회완료={viewed} 삭제={deleted}")
        print(f"{'='*70}")

        browser.close()


if __name__ == "__main__":
    main()
