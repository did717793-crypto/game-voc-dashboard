#!/usr/bin/env python3
"""
debug_korean_tab.py v2 — 한국어 탭 정확 동작 검증 (frame 선택 버그 수정)
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
    """SmartEditor sub-frame 제외, 메인 inquiry frame만 반환"""
    for f in page.frames:
        url = f.url
        if ("inquiry.withhive.com" in url
                and "/inquiry" in url
                and "smarteditor" not in url
                and "SmartEditor" not in url
                and "inputarea" not in url
                and "Skin.html" not in url):
            return f
    return None


def main():
    hive_id, hive_pw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width":1440,"height":900}, locale="ko-KR",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        load_cookies(ctx)
        page = ctx.new_page()

        # 네트워크 캡처
        search_urls = []
        def track_req(req):
            if "inquiry.withhive.com/inquiry?" in req.url and "menu_cd=415" in req.url and "smarteditor" not in req.url:
                search_urls.append(req.url)
        page.on("request", track_req)

        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        if "platform.withhive.com" in page.url:
            do_login(page, ctx, hive_id, hive_pw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)

        # 초기 HIVEframe
        hf = find_inquiry_frame(page)
        if not hf:
            print("[ERROR] HIVEframe 없음"); browser.close(); return
        print(f"\n[초기 HIVEframe] {hf.url}")

        # ═══════════════════════════════════════
        # STEP 1: 한국어 탭 클릭
        # ═══════════════════════════════════════
        print("\n[STEP 1] 한국어 탭 클릭")
        hf.click("a:text('한국어')", timeout=5_000)
        # frame navigation 대기
        for i in range(15):
            time.sleep(1)
            hf_new = find_inquiry_frame(page)
            if hf_new and "lang=0014010001" in hf_new.url:
                hf = hf_new
                print(f"  [OK] frame 갱신됨: {hf.url}")
                break
            if i % 3 == 2:
                print(f"  {i+1}초 대기... frame: {[f.url for f in page.frames if 'inquiry' in f.url]}")
        else:
            hf = find_inquiry_frame(page) or hf
            print(f"  [타임아웃] 현재 frame: {hf.url}")

        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        # ═══════════════════════════════════════
        # STEP 2: 현재 frame URL + sg select 확인
        # ═══════════════════════════════════════
        print(f"\n[STEP 2] 현재 frame: {hf.url}")
        lang_in_url = re.search(r'lang=([^&]+)', hf.url)
        print(f"  URL의 lang 파라미터: {lang_in_url.group(1) if lang_in_url else 'N/A'}")

        game_opts = hf.evaluate("""
            () => Array.from(document.querySelectorAll('select#search_game option')).map(o => ({val: o.value, txt: o.textContent.trim()}))
        """)
        print(f"  sg select 옵션: {game_opts}")
        dkr_ok = any(o['val'] == DKR_GAME_ID for o in game_opts)
        print(f"  DKR(2474) 존재: {dkr_ok}")

        # hidden fields (특히 lang)
        hidden_fields = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[type="hidden"]')).filter(i => i.name).map(i => ({n: i.name, v: i.value}))
        """)
        print(f"  hidden inputs: {hidden_fields[:10]}")

        # ═══════════════════════════════════════
        # STEP 3: DKR 선택
        # ═══════════════════════════════════════
        print("\n[STEP 3] DKR 선택")
        if dkr_ok:
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        else:
            print("  DKR 없음 → 게임=전체")
        sel_val = hf.evaluate("() => document.querySelector('select#search_game')?.value")
        print(f"  선택값: {sel_val}")

        # ═══════════════════════════════════════
        # STEP 4: 상태 체크박스 전체 체크
        # ═══════════════════════════════════════
        print("\n[STEP 4] 상태 체크박스 (native Playwright check)")
        before = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input#search_status')).map(cb => ({n: cb.name, c: cb.checked}))
        """)
        print(f"  체크 전: {[(c['n'], c['c']) for c in before]}")

        for i in range(1, 8):
            try:
                hf.check(f"input[name='ss_{i}']", timeout=2_000)
            except:
                pass
        time.sleep(0.3)

        after = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input#search_status')).map(cb => ({n: cb.name, c: cb.checked}))
        """)
        print(f"  체크 후: {[(c['n'], c['c']) for c in after]}")
        all_ok = all(c['c'] for c in after)
        print(f"  전체 체크: {all_ok}")

        # ═══════════════════════════════════════
        # STEP 5: 기간 3개월
        # ═══════════════════════════════════════
        print("\n[STEP 5] 3개월 기간 설정")
        try:
            hf.click("button:text('3개월')", timeout=3_000)
            time.sleep(1)
            print("  3개월 버튼 클릭 성공")
        except:
            print("  3개월 버튼 실패")
        date_val = hf.evaluate("() => document.querySelector('#search_date')?.value || ''")
        print(f"  날짜: {date_val}")

        # ═══════════════════════════════════════
        # STEP 6: 200개/페이지
        # ═══════════════════════════════════════
        try:
            hf.select_option("select[name='spc']", value="200", timeout=3_000)
        except:
            pass

        # ═══════════════════════════════════════
        # STEP 7: 최종 상태 덤프 + 검색
        # ═══════════════════════════════════════
        pre_search = hf.evaluate("""
            () => ({
                game: document.querySelector('select#search_game')?.value,
                date: document.querySelector('#search_date')?.value,
                spc: document.querySelector('select[name="spc"]')?.value,
                ss: Array.from(document.querySelectorAll('input#search_status')).map(cb => cb.checked),
                lang_hidden: document.querySelector('input[name="lang"]')?.value || ''
            })
        """)
        print(f"\n[STEP 7] 검색 직전 최종 상태:")
        print(f"  게임: {pre_search['game']}")
        print(f"  날짜: {pre_search['date']}")
        print(f"  페이지크기: {pre_search['spc']}")
        print(f"  상태(True 개수): {sum(1 for x in pre_search['ss'] if x)}/{len(pre_search['ss'])}")
        print(f"  lang hidden: {pre_search['lang_hidden']}")

        # 검색 버튼 클릭
        print("\n  ▶▶ 검색 버튼 클릭 (button#btn_submit)")
        prev_url_cnt = len(search_urls)
        hf.click("button#btn_submit", timeout=5_000)
        print("  클릭 완료")

        # 결과 로딩 대기
        result_count = 0
        for i in range(25):
            time.sleep(1)
            try:
                body = hf.inner_text("body")
                m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
                if m:
                    result_count = int(m.group(1).replace(',',''))
                    print(f"  [{i+1}초] 검색 건수: {result_count}건")
                    break
            except:
                pass

        # ═══════════════════════════════════════
        # STEP 8: 결과
        # ═══════════════════════════════════════
        print(f"\n{'='*55}")
        print("[STEP 8] 결과 분석")

        new_urls = search_urls[prev_url_cnt:]
        print(f"\n검색 요청 URL ({len(new_urls)}개):")
        for u in new_urls:
            lang_m = re.search(r'lang=([^&]+)', u)
            sg_m   = re.search(r'[&?]sg=([^&]+)', u)
            ss_m   = re.findall(r'ss_\d+=\w+', u)
            print(f"  lang={lang_m.group(1) if lang_m else '?'}")
            print(f"  sg={sg_m.group(1) if sg_m else '?'}")
            print(f"  ss={ss_m}")
            print(f"  full: {u[:300]}")

        body_f = hf.inner_text("body")
        for line in body_f.split('\n'):
            if '검색 건수' in line.strip():
                print(f"\n건수 상세: {line.strip()[:150]}")

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
        print(f"\n테이블 행: {len(rows)}개")
        for i, row in enumerate(rows[:5]):
            print(f"  [{i+1}] 번호={row[1]} | {row[4]} | {row[5][:25]} | {row[7][:10]} | {row[9]}")

        print(f"\n{'='*55}")
        if result_count > 0:
            print(f"✅ {result_count}건 — 수집 가능")
        else:
            print("❌ 0건")
            # lang 확인
            if new_urls:
                lang_m = re.search(r'lang=([^&]+)', new_urls[-1])
                print(f"  검색 lang: {lang_m.group(1) if lang_m else '?'}")
                if lang_m and lang_m.group(1) == 'my':
                    print("  → 여전히 lang=my. 탭 전환이 실제로 적용 안됨")
                elif lang_m and lang_m.group(1) == '0014010001':
                    print("  → lang=0014010001 (한국어) 정상. 실제 데이터 없음 가능성 높음")
        print(f"{'='*55}")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
