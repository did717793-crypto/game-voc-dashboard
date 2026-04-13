#!/usr/bin/env python3
"""
debug_final.py — frame.goto()로 한국어 탭 직접 로드 + 검색 검증
============================================================
핵심 발견:
  - "한국어" 탭 a-tag 클릭 → AJAX 방식, frame URL 미변경
  - ss_* 파라미터 누락 → 상태 필터 미반영
  - 해결: hf.goto(korean_tab_url) → 올바른 form 로드
"""
import json, sys, time, re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(1)

SCRIPTS_DIR  = Path(__file__).parent
RAW_DIR      = SCRIPTS_DIR / "raw"
COOKIE_FILE  = RAW_DIR / "hive_cookies.json"
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
CONSOLE_MAIN = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
DKR_GAME_ID  = "2474"
KOREAN_TAB   = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"


def load_credentials():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("hive_id",""), cfg.get("hive_pw","")
    return "",""

def load_cookies(ctx):
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        ctx.add_cookies(cookies); print(f"[INFO] 쿠키 {len(cookies)}개")

def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")

def do_login(page, ctx, hid, hpw):
    page.goto(PLATFORM_LOGIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.fill("#userId", hid); page.fill("#passWd", hpw)
    page.click("button:text('로그인')")
    time.sleep(3)
    for sel in ["button:text('확인')", ".modal button:text('확인')"]:
        try: page.click(sel, timeout=2_000); time.sleep(1); break
        except: pass
    page.wait_for_load_state("networkidle", timeout=30_000)
    time.sleep(2)
    if "platform.withhive.com" not in page.url:
        save_cookies(ctx); return True
    return False

def find_inquiry_frame(page):
    for f in page.frames:
        url = f.url
        if ("inquiry.withhive.com" in url
                and "/inquiry" in url
                and "smarteditor" not in url.lower()
                and "inputarea" not in url
                and "Skin.html" not in url):
            return f
    return None


def do_search_on_frame(hf, page, label, game_id=DKR_GAME_ID, period_months=3):
    """
    frame에서 게임 선택 + 상태전체 + 기간 + 검색 → 건수/rows 반환
    """
    search_urls = []
    def track(req):
        if "inquiry.withhive.com/inquiry?" in req.url and "menu_cd=415" in req.url and "smarteditor" not in req.url:
            search_urls.append(req.url)
    page.on("request", track)

    print(f"\n{'='*55}")
    print(f"[{label}]")

    # 게임 선택 옵션 확인
    game_opts = hf.evaluate("""
        () => Array.from(document.querySelectorAll('select#search_game option')).map(o => ({val: o.value, txt: o.textContent.trim()}))
    """)
    print(f"  sg 옵션: {[o['val'] for o in game_opts]}")
    dkr_ok = any(o['val'] == game_id for o in game_opts)

    # 게임 선택
    if dkr_ok and game_id != "-1":
        hf.select_option("select#search_game", value=game_id, timeout=5_000)
    elif game_id == "-1":
        hf.select_option("select#search_game", value="-1", timeout=5_000)
    sel = hf.evaluate("() => document.querySelector('select#search_game')?.value")
    print(f"  게임 선택: {sel}")

    # 상태 체크박스 확인
    cb_names = hf.evaluate("""
        () => Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(cb => cb.name && cb.name.startsWith('ss_')).map(cb => ({n: cb.name, c: cb.checked}))
    """)
    print(f"  ss_* 체크박스: {[(c['n'], c['c']) for c in cb_names]}")

    # 상태 전체 체크 (native Playwright)
    for cb in cb_names:
        if not cb['c']:
            try:
                hf.check(f"input[name='{cb['n']}']", timeout=2_000)
            except:
                pass
    # 추가로 all_check_status 버튼이 있으면 클릭
    try:
        btn = hf.evaluate("""
            () => {
                var cbs = document.querySelectorAll('input[name^="ss_"]');
                var allChecked = Array.from(cbs).every(cb => cb.checked);
                if (!allChecked) {
                    var btn = document.querySelector('#all_check_status');
                    if (btn) { btn.click(); return 'clicked'; }
                }
                return 'ok';
            }
        """)
    except:
        pass
    time.sleep(0.3)

    cb_after = hf.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]')).map(cb => ({n: cb.name, c: cb.checked}))
    """)
    print(f"  상태 체크 후: {[(c['n'], c['c']) for c in cb_after]}")

    # 기간 버튼
    period_btn = "3개월" if period_months >= 3 else "1개월"
    try:
        hf.click(f"button:text('{period_btn}')", timeout=3_000)
        time.sleep(1)
    except:
        pass
    date_val = hf.evaluate("() => document.querySelector('#search_date')?.value || ''")
    print(f"  기간: {date_val}")

    # 페이지 크기 200
    try:
        hf.select_option("select[name='spc']", value="200", timeout=3_000)
    except:
        pass

    # hidden lang 확인
    hidden_lang = hf.evaluate("""
        () => document.querySelector('input[name="lang"]')?.value || 'N/A'
    """)
    print(f"  lang(hidden): {hidden_lang}")

    # 검색 클릭
    prev_cnt = len(search_urls)
    print(f"  ▶ 검색 클릭")
    hf.click("button#btn_submit", timeout=5_000)

    # 대기
    count = 0
    for i in range(20):
        time.sleep(1)
        try:
            body = hf.inner_text("body")
            m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
            if m:
                count = int(m.group(1).replace(',',''))
                print(f"  [{i+1}초] 건수: {count}")
                break
        except:
            pass

    # 검색 URL 분석
    new_urls = search_urls[prev_cnt:]
    for u in new_urls[:2]:
        lang_m = re.search(r'lang=([^&]+)', u)
        sg_m = re.search(r'[?&]sg=([^&]+)', u)
        ss_m = re.findall(r'ss_\d+=\w+', u)
        print(f"  URL → lang={lang_m.group(1) if lang_m else '?'} sg={sg_m.group(1) if sg_m else '?'} ss={ss_m}")
        print(f"    full(500): {u[:500]}")

    # rows
    rows = hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('table tbody tr').forEach(row => {
                var cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10)
                    result.push(cells);
            });
            return result;
        }
    """)
    print(f"  테이블 행: {len(rows)}")
    for i, row in enumerate(rows[:3]):
        print(f"    [{i+1}] {row[1]} | {row[4]} | {row[5][:20]} | {row[7][:10]} | {row[9]}")

    page.remove_listener("request", track)
    return count, rows


def main():
    hive_id, hive_pw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width":1440,"height":900}, locale="ko-KR",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        load_cookies(ctx)
        page = ctx.new_page()

        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        if "platform.withhive.com" in page.url:
            do_login(page, ctx, hive_id, hive_pw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)

        hf = find_inquiry_frame(page)
        if not hf:
            print("[ERROR] HIVEframe 없음"); browser.close(); return
        print(f"[초기 HIVEframe] {hf.url}")

        # ─────────────────────────────────────────
        # 방법: frame.goto()로 한국어 탭 URL 직접 로드
        # (탭 링크 href와 동일한 URL)
        # ─────────────────────────────────────────
        print(f"\n[frame.goto()] 한국어 탭 URL: {KOREAN_TAB}")
        hf.goto(KOREAN_TAB, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print(f"  현재 frame URL: {hf.url}")

        # ─────────────────────────────────────────
        # TEST A: 한국어 탭 + DKR + 전체상태 + 3개월
        # ─────────────────────────────────────────
        count_a, rows_a = do_search_on_frame(hf, page, "한국어 탭 + DKR + 3개월", game_id=DKR_GAME_ID, period_months=3)

        # ─────────────────────────────────────────
        # TEST B: 한국어 탭 + 게임=전체 + 3개월
        # ─────────────────────────────────────────
        hf.goto(KOREAN_TAB, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        count_b, rows_b = do_search_on_frame(hf, page, "한국어 탭 + 게임=전체 + 3개월", game_id="-1", period_months=3)

        # ─────────────────────────────────────────
        # 최종 요약
        # ─────────────────────────────────────────
        print(f"\n{'='*55}")
        print("[최종 결과 요약]")
        print(f"  A. 한국어 + DKR + 3개월: {count_a}건")
        print(f"  B. 한국어 + 전체게임 + 3개월: {count_b}건")
        print(f"{'='*55}")
        if count_a > 0:
            print("✅ DKR 문의 데이터 존재 → 수집 가능")
        elif count_b > 0:
            print("⚠️ 전체 게임에는 데이터 있으나 DKR 0건 → DKR 게임 ID 확인 필요")
        else:
            print("❌ 한국어 탭 전체 게임도 0건 → 실제 데이터 없거나 권한 문제")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
