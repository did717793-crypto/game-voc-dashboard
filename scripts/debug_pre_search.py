#!/usr/bin/env python3
"""
debug_pre_search.py — 검색 직전 전체 필터 상태 덤프 + 검색 결과 확인
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
        ctx.add_cookies(cookies)
        print(f"[INFO] 쿠키 {len(cookies)}개")

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


def dump_filter_state(hf, label=""):
    """현재 HIVEframe의 전체 필터 상태 출력"""
    state = hf.evaluate("""
        () => {
            return {
                game: {
                    value: document.querySelector('select#search_game')?.value || '',
                    text: document.querySelector('select#search_game option:checked')?.textContent.trim() || ''
                },
                status_cbs: Array.from(document.querySelectorAll('input#search_status')).map(cb => ({
                    name: cb.name, checked: cb.checked
                })),
                date: {
                    range: document.querySelector('#search_date')?.value || '',
                    start: document.querySelector('input[name="daterangepicker_start"]')?.value || '',
                    end: document.querySelector('input[name="daterangepicker_end"]')?.value || ''
                },
                page_size: document.querySelector('select[name="spc"]')?.value || '',
                lang_tab: Array.from(document.querySelectorAll('.nav-tabs a.active, .tab-menu a.active, li.active a')).map(a => a.textContent.trim())
            };
        }
    """)
    print(f"\n{'='*50}")
    print(f"[필터 상태: {label}]")
    print(f"  게임: {state['game']['value']} ({state['game']['text']})")
    print(f"  날짜: {state['date']['range']} / {state['date']['start']}~{state['date']['end']}")
    print(f"  페이지크기: {state['page_size']}")
    print(f"  언어탭: {state['lang_tab']}")
    print(f"  상태 체크박스:")
    for cb in state['status_cbs']:
        mark = "✓" if cb['checked'] else "✗"
        print(f"    [{mark}] {cb['name']}")
    all_ok = all(cb['checked'] for cb in state['status_cbs']) if state['status_cbs'] else False
    print(f"  → 상태 전체선택: {all_ok}")
    print(f"{'='*50}")
    return state


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

        hf = None
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                hf = f; break
        if not hf:
            print("[ERROR] HIVEframe 없음"); browser.close(); return

        print(f"[HIVEframe] {hf.url}")

        # STEP 1: 초기 상태
        dump_filter_state(hf, "초기")

        # STEP 2: 한국어 탭
        try:
            hf.click("a:text('한국어')", timeout=5_000)
            hf.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)
            print("[OK] 한국어 탭")
        except Exception as e:
            print(f"[WARN] 한국어 탭: {e}")

        dump_filter_state(hf, "한국어 탭 클릭 후")

        # STEP 3: DKR 선택
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        time.sleep(1)
        dump_filter_state(hf, "게임 선택 후")

        # STEP 4: 상태 전체 선택
        print("\n[상태 필터 처리]")
        # all_check_status 버튼 클릭
        result = hf.evaluate("""
            () => {
                var btn = document.querySelector('#all_check_status');
                if (!btn) return 'NOT FOUND';

                // 현재 상태 확인
                var cbs = document.querySelectorAll('input#search_status');
                var allChecked = Array.from(cbs).every(cb => cb.checked);

                if (allChecked) {
                    // 이미 모두 체크 → 2번 클릭 (해제→재선택)
                    btn.click();
                    return 'already_all: clicked_once';
                } else {
                    // 체크 안 된 게 있음 → 1번 클릭
                    btn.click();
                    return 'clicked_to_select_all';
                }
            }
        """)
        print(f"  1차 결과: {result}")
        time.sleep(0.5)

        # 확인
        cbs = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input#search_status')).map(cb => ({name: cb.name, checked: cb.checked}))
        """)
        all_ok = all(c['checked'] for c in cbs)
        print(f"  체크 상태: {[(c['name'], c['checked']) for c in cbs]}")
        print(f"  전체선택: {all_ok}")

        if not all_ok:
            # 강제 개별 클릭
            print("  → 개별 클릭으로 강제 선택")
            hf.evaluate("""
                () => {
                    document.querySelectorAll('input#search_status').forEach(cb => {
                        if (!cb.checked) {
                            cb.checked = true;
                            cb.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    });
                }
            """)
            time.sleep(0.3)

        dump_filter_state(hf, "상태 필터 처리 후")

        # STEP 5: 1개월 버튼
        try:
            hf.click("button:text('1개월')", timeout=3_000)
            time.sleep(1)
            print("[OK] 1개월 클릭")
        except Exception as e:
            print(f"[WARN] 1개월 버튼: {e}")

        dump_filter_state(hf, "1개월 클릭 후")

        # STEP 6: 페이지 크기 200
        try:
            hf.select_option("select[name='spc']", value="200", timeout=3_000)
            print("[OK] 200개/페이지")
        except:
            pass

        # STEP 7: 검색 직전 최종 상태
        dump_filter_state(hf, "검색 직전 최종")

        # STEP 8: 검색 실행
        print("\n[검색 실행]")
        hf.click("button#btn_submit", timeout=5_000)
        hf.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(4)

        # STEP 9: 결과 확인
        body = hf.inner_text("body")
        count_m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
        count = int(count_m.group(1).replace(',','')) if count_m else 0
        print(f"\n[검색 결과]")
        print(f"  검색 건수: {count}건")

        # 테이블 rows
        rows = hf.evaluate("""
            () => {
                var result = [];
                document.querySelectorAll('table tbody tr').forEach(row => {
                    var cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                    if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10) {
                        result.push(cells);
                    }
                });
                return result;
            }
        """)
        print(f"  테이블 행 수: {len(rows)}")
        for i, row in enumerate(rows[:5]):
            print(f"  [{i+1}] 번호={row[1]} 분류={row[4]} 제목={row[5][:20]} 접수일={row[7][:10]} 상태={row[9]}")

        # body에 "검색 건수" 텍스트가 없을 경우 다른 패턴 탐색
        if count == 0:
            print("\n  [검색 건수 텍스트 탐색]")
            for pattern in [r'(\d+)건', r'total.*?(\d+)', r'count.*?(\d+)']:
                m = re.search(pattern, body, re.IGNORECASE)
                if m:
                    print(f"  패턴 '{pattern}' → {m.group(1)}")
            # body 일부 출력
            for line in body.split('\n'):
                line = line.strip()
                if line and ('건' in line or '검색' in line or '총' in line):
                    print(f"  LINE: {line[:80]}")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
