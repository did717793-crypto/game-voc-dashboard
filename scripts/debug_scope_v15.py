#!/usr/bin/env python3
"""
debug_scope_v15.py — 내 상담 / 전체 상담 토글 확인 및 강제 전환
================================================================
검증 목표:
  [1] 현재 내 상담 / 전체 상담 토글 상태 DOM 확인
  [2] 전체 상담으로 강제 전환 후 검색
  [3] ss_1~ss_7 실제 checked 값 출력
  [4] sg 제거(전체 게임) + 날짜 검색
  [5] 모든 필터 제거 + 날짜만 검색 (데이터 존재 여부 확인)
"""

import json, re, sys, time
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
START_DATE     = "2026-04-03"
END_DATE       = "2026-04-10"
KST            = timezone(timedelta(hours=9))


def parse_summary_text(frame):
    try:
        body = frame.locator("body").inner_text(timeout=5000)
        m = re.search(
            r"검색\s*건수\s*:\s*(\d+).*?"
            r"접수\s*완료\s*:\s*(\d+).*?"
            r"처리\s*중\s*:\s*(\d+).*?"
            r"답변\s*완료\s*:\s*(\d+).*?"
            r"조회\s*완료\s*:\s*(\d+).*?"
            r"삭제\s*:\s*(\d+).*?"
            r"관리자\s*삭제\s*:\s*(\d+)",
            body, re.S
        )
        if not m:
            return None
        return {
            "total": int(m.group(1)), "received": int(m.group(2)),
            "in_progress": int(m.group(3)), "answered": int(m.group(4)),
            "viewed": int(m.group(5)), "deleted": int(m.group(6)),
            "admin_deleted": int(m.group(7)),
        }
    except Exception:
        return None


def wait_summary_change(frame, before, timeout_ms=12000):
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        try:
            now = parse_summary_text(frame)
            if now is not None and now != before:
                return now
        except Exception:
            pass
        time.sleep(0.5)
    return None


def click_search(page, frame, selector="button#btn_submit"):
    """클릭 후 요약바 변경 확인. (before, after, method) 반환."""
    btn = frame.locator(selector)
    btn.wait_for(state="visible", timeout=10000)
    before = parse_summary_text(frame)

    # 1. 일반 클릭
    try:
        btn.scroll_into_view_if_needed(timeout=3000)
        btn.click(timeout=3000)
        changed = wait_summary_change(frame, before, timeout_ms=10000)
        if changed is not None:
            return before, changed, "normal_click"
    except Exception:
        pass

    # 2. force click
    try:
        btn.click(timeout=3000, force=True)
        changed = wait_summary_change(frame, before, timeout_ms=10000)
        if changed is not None:
            return before, changed, "force_click"
    except Exception:
        pass

    # 3. JS click
    try:
        frame.evaluate("(sel) => { const el = document.querySelector(sel); if(el){el.scrollIntoView({block:'center'}); el.click();} }", selector)
        changed = wait_summary_change(frame, before, timeout_ms=10000)
        if changed is not None:
            return before, changed, "js_click"
    except Exception:
        pass

    # 4. bbox 클릭
    try:
        box = btn.bounding_box(timeout=3000)
        frame_el = page.locator("iframe[name='HIVEframe'], #consoleContents").first
        frame_box = frame_el.bounding_box()
        if box and frame_box:
            x = frame_box["x"] + box["x"] + box["width"] / 2
            y = frame_box["y"] + box["y"] + box["height"] / 2
            page.mouse.click(x, y)
            changed = wait_summary_change(frame, before, timeout_ms=10000)
            if changed is not None:
                return before, changed, "bbox_click"
    except Exception:
        pass

    # 클릭은 됐지만 변경 없음 (0→0 같은 경우)
    after = parse_summary_text(frame)
    return before, after, "clicked_no_change"


def set_dates(hf, start, end):
    hf.evaluate(f"""
        () => {{
            var sdf = document.querySelector('#search_date, input[name="sdf"]');
            var sds = document.querySelector('input[name="sds"]');
            var sde = document.querySelector('input[name="sde"]');
            if (sdf) sdf.value = '{start} - {end}';
            if (sds) sds.value = '{start}';
            if (sde) sde.value = '{end}';
        }}
    """)
    time.sleep(0.3)


def check_all_ss(hf):
    cb_names = hf.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
            .map(cb => ({n: cb.name, c: cb.checked}))
    """)
    for cb in cb_names:
        if not cb['c']:
            name = cb['n']
            try:
                hf.check(f"input[name='{name}']", timeout=2_000)
            except Exception:
                hf.evaluate(f"() => {{ var el = document.querySelector('input[name=\"{name}\"]'); if(el && !el.checked) el.click(); }}")
    time.sleep(0.3)
    return hf.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
            .map(cb => ({n: cb.name, c: cb.checked}))
    """)


def read_rows(hf):
    return hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('table tbody tr').forEach(function(row) {
                var cells = Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
                if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10)
                    result.push(cells);
            });
            return result;
        }
    """)


def print_result(label, before, after, method, rows):
    print(f"\n{'─'*55}")
    print(f"  [{label}]")
    print(f"  클릭 방식 : {method}")
    print(f"  클릭 전   : {before}")
    print(f"  클릭 후   : {after}")
    print(f"  row 수    : {len(rows)}개")
    if rows:
        print(f"  첫 5개 row:")
        for i, r in enumerate(rows[:5]):
            print(f"    [{i+1}] {r}")
    else:
        print(f"  → 결과 없음")


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

def get_hive_frame(page, ctx, hid, hpw):
    page.goto(CONSOLE_MAIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(2)
    if "platform.withhive.com" in page.url:
        print("  세션 만료 → 재로그인")
        do_login(page, ctx, hid, hpw)
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
    print(f"  console URL: {page.url}")

    hf = None
    for _ in range(10):
        hf = find_inquiry_frame(page)
        if hf: break
        time.sleep(1)
    if not hf:
        for sel in ["a[menu='415']", "a:text('문의 목록')"]:
            try: page.click(sel, timeout=3_000); print(f"  클릭: {sel}"); break
            except Exception: pass
        for i in range(20):
            time.sleep(1); hf = find_inquiry_frame(page)
            if hf: break
    if not hf:
        INQUIRY_BASE = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
        page.evaluate(f"() => {{ var el = document.querySelector('#consoleContents, iframe[name=\"HIVEframe\"]'); if(el) el.src = '{INQUIRY_BASE}'; }}")
        for _ in range(15):
            time.sleep(1); hf = find_inquiry_frame(page)
            if hf: break
    return hf


# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print(f"  내/전체 상담 토글 확인 + 조회 범위 검증 v15")
    print(f"  날짜: {START_DATE} ~ {END_DATE}")
    print("=" * 65)

    hid, hpw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        load_cookies(ctx)
        page = ctx.new_page()

        # ── 로그인 / HIVEframe 진입 ───────────────────────────────────────
        print("\n[SETUP] 로그인 및 HIVEframe 진입")
        hf = get_hive_frame(page, ctx, hid, hpw)
        if not hf:
            print("  ❌ HIVEframe 진입 실패"); browser.close(); return
        print(f"  ✅ iframe URL: {hf.url}")

        # ── 한국어 탭 로드 ────────────────────────────────────────────────
        print("\n[SETUP] 한국어 탭 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print(f"  frame URL: {hf.url}")

        # ══════════════════════════════════════════════════════════════════
        # [1] 내 상담 / 전체 상담 토글 상태 DOM 전수 조사
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[1] 내 상담 / 전체 상담 토글 DOM 전수 조사")
        print("═"*65)

        scope_info = hf.evaluate("""
            () => {
                var result = {};

                // hidden input: lang, my_flag, scope 등 후보
                var hiddens = Array.from(document.querySelectorAll('input[type="hidden"]'))
                    .map(el => ({name: el.name, id: el.id, value: el.value}))
                    .filter(el => el.name || el.id);
                result.hidden_inputs = hiddens;

                // 탭/링크: 내 상담, 전체 관련 텍스트
                var allLinks = Array.from(document.querySelectorAll('a, button, label'))
                    .filter(el => {
                        var t = el.textContent.trim();
                        return t.includes('내') || t.includes('전체') ||
                               t.includes('my') || t.includes('all') ||
                               t.includes('All') || t.includes('My');
                    })
                    .map(el => ({
                        tag: el.tagName,
                        text: el.textContent.trim().substring(0, 30),
                        href: el.href || '',
                        class: el.className,
                        id: el.id,
                        active: el.classList.contains('active') || el.classList.contains('on') || el.classList.contains('selected')
                    }));
                result.scope_links = allLinks;

                // select 중 my/all 관련
                var selects = Array.from(document.querySelectorAll('select'))
                    .map(sel => ({
                        name: sel.name, id: sel.id,
                        value: sel.value,
                        options: Array.from(sel.options).map(o => ({v: o.value, t: o.text.trim()}))
                    }))
                    .filter(sel => sel.name || sel.id);
                result.selects = selects;

                // radio 버튼
                var radios = Array.from(document.querySelectorAll('input[type="radio"]'))
                    .map(r => ({name: r.name, value: r.value, checked: r.checked, id: r.id,
                        label: document.querySelector('label[for="'+r.id+'"]')?.textContent.trim() || ''}));
                result.radios = radios;

                // 현재 URL의 lang 파라미터
                result.current_url = window.location.href;

                // form action/method
                var form = document.querySelector('form');
                result.form = form ? {action: form.action, method: form.method,
                    id: form.id, name: form.name} : null;

                // form의 hidden input 중 lang 관련
                result.lang_inputs = Array.from(document.querySelectorAll('input[name="lang"], input[name="my_cs"], input[name="scope"], input[name="view_type"]'))
                    .map(el => ({name: el.name, value: el.value, type: el.type}));

                // 탭 영역 전체 HTML (ul.nav-tabs 등)
                var navTabs = document.querySelector('.nav-tabs, ul.tab, .search-tab, #tab_area');
                result.nav_tabs_html = navTabs ? navTabs.outerHTML.substring(0, 800) : '없음';

                // 상단 탭 링크들 href 전체
                result.all_tab_links = Array.from(document.querySelectorAll('.nav-tabs a, ul.tab a, li a'))
                    .map(a => ({text: a.textContent.trim().substring(0,20), href: a.href, class: a.className}))
                    .slice(0, 20);

                return result;
            }
        """)

        print(f"\n  현재 URL: {scope_info.get('current_url', '?')}")
        print(f"\n  lang 관련 input:")
        for el in scope_info.get('lang_inputs', []):
            print(f"    name={el['name']} type={el['type']} value={el['value']}")

        print(f"\n  hidden inputs 전체:")
        for el in scope_info.get('hidden_inputs', []):
            print(f"    name={el['name']} id={el['id']} value={el['value']}")

        print(f"\n  radio 버튼:")
        radios = scope_info.get('radios', [])
        if radios:
            for r in radios:
                print(f"    name={r['name']} value={r['value']} checked={r['checked']} label={r['label']}")
        else:
            print("    없음")

        print(f"\n  select 요소:")
        for sel in scope_info.get('selects', []):
            print(f"    name={sel['name']} id={sel['id']} value={sel['value']}")
            print(f"      options: {[(o['v'], o['t']) for o in sel['options']]}")

        print(f"\n  내/전체/my/all 관련 링크:")
        for lnk in scope_info.get('scope_links', []):
            print(f"    [{lnk['tag']}] '{lnk['text']}' class={lnk['class'][:40]} active={lnk['active']} href={lnk['href'][:60]}")

        print(f"\n  탭 영역 HTML (첫 800자):")
        print(f"  {scope_info.get('nav_tabs_html', '없음')[:800]}")

        print(f"\n  탭 링크 전체:")
        for t in scope_info.get('all_tab_links', []):
            print(f"    '{t['text']}' href={t['href'][:80]} class={t['class'][:30]}")

        # form의 실제 제출 파라미터 직접 확인
        print(f"\n  form 정보: {scope_info.get('form')}")

        # ══════════════════════════════════════════════════════════════════
        # [2] 전체 상담 URL로 직접 전환 시도
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[2] 전체 상담 URL 직접 전환")
        print("═"*65)

        # lang=my 제거 → 전체 조회로 추정되는 URL들 시도
        ALL_SCOPE_URLS = [
            # lang 파라미터 없이 → 전체
            "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&company_cd=342",
            # lang=0014010001 유지 (현재) → 이미 시도함
            # lang=all 또는 lang=0 시도
            "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=all&company_cd=342",
            "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0&company_cd=342",
        ]

        scope_results = {}

        for url in ALL_SCOPE_URLS:
            short = url.split("?")[1][:60]
            print(f"\n  → 시도: {short}")
            try:
                hf.goto(url, timeout=12_000)
                hf.wait_for_load_state("networkidle", timeout=12_000)
                time.sleep(2)
                summary = parse_summary_text(hf)
                lang_val = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || 'NONE'")
                print(f"    hidden lang={lang_val} | 초기 요약={summary}")
                scope_results[short] = {"summary": summary, "lang": lang_val, "url": url}
            except Exception as e:
                print(f"    예외: {e}")

        # ══════════════════════════════════════════════════════════════════
        # [3] 현재 한국어 탭(lang=0014010001) + DKR + 날짜 → ss_* 실제 체크 상태 출력
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[3] ss_* 실제 checked 상태 + form 파라미터 직접 출력")
        print("═"*65)

        # 한국어 탭으로 복귀
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

        # DKR 선택
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        except Exception as e:
            print(f"  게임 선택 실패: {e}")

        # ss_* 전체 체크
        cb_after = check_all_ss(hf)
        print(f"  ss_* 체크 상태: {[(c['n'], c['c']) for c in cb_after]}")
        all_checked = all(c['c'] for c in cb_after)
        print(f"  전체 체크: {'✅' if all_checked else '❌'}")

        # 날짜 설정
        set_dates(hf, START_DATE, END_DATE)

        # form serialize 확인 (실제 제출 파라미터)
        form_data = hf.evaluate("""
            () => {
                var form = document.querySelector('form');
                if (!form) return 'form 없음';
                var fd = new FormData(form);
                var result = {};
                for (var [k, v] of fd.entries()) {
                    if (result[k]) {
                        if (!Array.isArray(result[k])) result[k] = [result[k]];
                        result[k].push(v);
                    } else {
                        result[k] = v;
                    }
                }
                return result;
            }
        """)
        print(f"\n  form serialize (실제 제출 파라미터):")
        if isinstance(form_data, dict):
            for k, v in form_data.items():
                print(f"    {k} = {v}")
        else:
            print(f"  {form_data}")

        # ══════════════════════════════════════════════════════════════════
        # [4] 검색 실행 A: lang=0014010001 + DKR + 날짜 (현재 방식)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[4-A] 검색: lang=0014010001 + DKR(2474) + 날짜")
        print("═"*65)
        before, after, method = click_search(page, hf)
        rows = read_rows(hf)
        print_result("lang=0014010001 + DKR + 날짜", before, after, method, rows)

        # ══════════════════════════════════════════════════════════════════
        # [4-B] sg 제거 (전체 게임) + 날짜
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[4-B] 검색: lang=0014010001 + 게임 필터 없음 + 날짜")
        print("═"*65)

        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

        # 게임 선택 안 함 (기본 -1 또는 전체)
        try:
            hf.select_option("select#search_game", value="-1", timeout=3_000)
            print("  sg=-1 설정 (전체 게임)")
        except Exception:
            try:
                hf.select_option("select#search_game", index=0, timeout=3_000)
                print("  sg=index 0 설정 (전체 게임)")
            except Exception as e:
                print(f"  게임 초기화 실패: {e}")

        check_all_ss(hf)
        set_dates(hf, START_DATE, END_DATE)

        sg_val = hf.evaluate("() => document.querySelector('select#search_game')?.value || '?'")
        print(f"  sg 현재 값: {sg_val}")

        before, after, method = click_search(page, hf)
        rows_b = read_rows(hf)
        print_result("전체 게임 + 날짜", before, after, method, rows_b)

        # ══════════════════════════════════════════════════════════════════
        # [4-C] lang 파라미터 없이 + DKR + 날짜 (전체 상담 가능성)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[4-C] 검색: lang 없음(전체) + DKR(2474) + 날짜")
        print("═"*65)

        NO_LANG_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&company_cd=342"
        hf.goto(NO_LANG_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        print(f"  frame URL: {hf.url}")

        hidden_lang_c = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || 'NONE'")
        print(f"  hidden lang: {hidden_lang_c}")

        init_c = parse_summary_text(hf)
        print(f"  초기 요약: {init_c}")

        # DKR 선택
        try:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
            print(f"  DKR 선택 OK")
        except Exception as e:
            print(f"  DKR 선택 실패: {e}")

        check_all_ss(hf)
        set_dates(hf, START_DATE, END_DATE)

        before, after, method = click_search(page, hf)
        rows_c = read_rows(hf)
        print_result("lang 없음 + DKR + 날짜", before, after, method, rows_c)

        # ══════════════════════════════════════════════════════════════════
        # [5] 모든 필터 제거 + 날짜만 (데이터 존재 여부)
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("[5] 검색: 게임 없음 + lang 없음 + 날짜만 (데이터 존재 확인)")
        print("═"*65)

        hf.goto(NO_LANG_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

        # 게임 전체
        try:
            hf.select_option("select#search_game", value="-1", timeout=3_000)
        except Exception:
            try:
                hf.select_option("select#search_game", index=0, timeout=3_000)
            except Exception:
                pass

        check_all_ss(hf)
        set_dates(hf, START_DATE, END_DATE)

        before, after, method = click_search(page, hf)
        rows_d = read_rows(hf)
        print_result("전체 게임 + lang 없음 + 날짜만", before, after, method, rows_d)

        # ══════════════════════════════════════════════════════════════════
        # 최종 비교표
        # ══════════════════════════════════════════════════════════════════
        print("\n" + "═"*65)
        print("  최종 비교 요약")
        print("═"*65)
        print(f"  {'조건':<35} {'total':>6} {'answered':>8} {'viewed':>8}")
        print(f"  {'-'*60}")

        cases = [
            ("기준(사용자 실제 화면)", {"total":19,"answered":13,"viewed":6}),
            ("4-A: lang=0014010001+DKR+날짜", after if '[4-A]' else None),
        ]

        # 각 케이스의 after 값 재출력
        def fmt(d):
            if not d: return f"{'?':>6} {'?':>8} {'?':>8}"
            return f"{d.get('total',0):>6} {d.get('answered',0):>8} {d.get('viewed',0):>8}"

        ref = {"total":19, "answered":13, "viewed":6}
        print(f"  {'[기준] 사용자 화면':<35} {fmt(ref)}")

        cases_data = [
            ("[4-A] ko+DKR+날짜", after),
            ("[4-B] ko+전체게임+날짜", after if not rows_b else parse_summary_text(hf) if False else None),  # 마지막 실행 후 상태
        ]
        # 실제로는 각 검색 후 after 값 사용
        for label, d in [
            ("[4-A] ko탭+DKR+날짜", None),      # 위에서 이미 출력
            ("[4-B] ko탭+전체게임+날짜", None),
            ("[4-C] lang없음+DKR+날짜", None),
            ("[5] lang없음+전체+날짜만", None),
        ]:
            pass  # 각 섹션에서 이미 출력됨

        print(f"\n  ※ 각 케이스 상세 결과는 위 섹션 [4-A~C] [5] 참조")

        browser.close()
        print("\n[완료]")


if __name__ == "__main__":
    main()
