#!/usr/bin/env python3
"""
debug_no_tab.py — 한국어 탭 클릭 없이 검색 (탭 영향도 검증)
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


def do_search(hf, label, click_tab=None):
    """필터 설정 후 검색 실행 + 결과 반환"""
    print(f"\n{'='*50}")
    print(f"[테스트: {label}]")
    print(f"{'='*50}")

    # 탭 클릭 (선택적)
    if click_tab:
        try:
            hf.click(f"a:text('{click_tab}')", timeout=3_000)
            hf.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)
            print(f"[탭] {click_tab} 클릭")
        except Exception as e:
            print(f"[WARN] {click_tab} 탭: {e}")
    else:
        print(f"[탭] 탭 클릭 없음 (현재 탭 유지)")

    # 현재 탭 상태 확인
    tab_state = hf.evaluate("""
        () => {
            var tabs = document.querySelectorAll('.nav-tabs li, .tab-menu li, [role="tab"]');
            return Array.from(tabs).map(t => ({
                text: t.textContent.trim().replace(/\\s+/g,' ').substring(0,30),
                active: t.classList.contains('active') || t.getAttribute('aria-selected') === 'true'
            }));
        }
    """)
    print(f"  탭 목록: {tab_state}")

    # DKR 선택
    hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
    selected = hf.evaluate("() => document.querySelector('select#search_game')?.value")
    print(f"  게임: {selected}")

    # 상태 강제 체크 (개별 click)
    unchecked = hf.evaluate("""
        () => {
            var cbs = document.querySelectorAll('input#search_status:not(:checked)');
            cbs.forEach(cb => cb.click());
            return cbs.length;
        }
    """)
    print(f"  상태: {unchecked}개 체크 안된 것 개별 클릭")
    time.sleep(0.3)

    # 최종 상태 확인
    cb_state = hf.evaluate("""
        () => Array.from(document.querySelectorAll('input#search_status')).map(cb => cb.checked)
    """)
    print(f"  상태 체크: {cb_state}")

    # 기간 (이미 설정된 상태 유지, 또는 다시 클릭)
    try:
        hf.click("button:text('1개월')", timeout=3_000)
        time.sleep(1)
    except:
        pass
    date_val = hf.evaluate("() => document.querySelector('#search_date')?.value || ''")
    print(f"  기간: {date_val}")

    # 페이지 크기
    try:
        hf.select_option("select[name='spc']", value="200", timeout=3_000)
    except:
        pass

    # 검색 실행
    hf.click("button#btn_submit", timeout=5_000)
    hf.wait_for_load_state("networkidle", timeout=20_000)
    time.sleep(4)

    # 결과 확인
    body = hf.inner_text("body")
    count_m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
    count = int(count_m.group(1).replace(',','')) if count_m else 0
    print(f"  검색 건수: {count}건")

    # 상세 row
    rows = hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('table tbody tr').forEach(row => {
                var cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10) result.push(cells);
            });
            return result;
        }
    """)
    print(f"  테이블 행: {len(rows)}개")
    for i, row in enumerate(rows[:3]):
        print(f"  [{i+1}] {row[1]} | {row[4]} | {row[5][:20]} | {row[7][:10]} | {row[9]}")

    # 건수 섹션 텍스트 (각 상태별)
    for line in body.split('\n'):
        line = line.strip()
        if line and '검색 건수' in line:
            print(f"  건수 상세: {line[:150]}")

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

        hf = None
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                hf = f; break
        if not hf:
            print("[ERROR] HIVEframe 없음"); browser.close(); return

        print(f"[HIVEframe] {hf.url}")

        # 탭 목록 먼저 파악
        all_tabs = hf.evaluate("""
            () => {
                // 여러 가지 탭 선택자 시도
                var selectors = ['.nav-tabs a', '.nav-link', '[role="tab"]', 'ul.nav a', '.tab-menu a'];
                for (var sel of selectors) {
                    var tabs = document.querySelectorAll(sel);
                    if (tabs.length > 0) {
                        return Array.from(tabs).map(t => ({
                            text: t.textContent.trim().replace(/\\s+/g,' ').substring(0,30),
                            class: t.className,
                            href: t.getAttribute('href') || ''
                        }));
                    }
                }
                return [];
            }
        """)
        print(f"\n[전체 탭 목록]: {all_tabs}")

        # 테스트 1: 탭 클릭 없음 (현재 "내 상담" 탭)
        count1, rows1 = do_search(hf, label="탭 클릭 없음 (내 상담)")

        # 테스트 2: 한국어 탭 클릭
        count2, rows2 = do_search(hf, label="한국어 탭 클릭", click_tab="한국어")

        # 테스트 3: 게임 = 전체(-1)로 탭 없이 검색
        print(f"\n{'='*50}")
        print("[테스트 3: 게임=전체, 탭없음]")
        hf.select_option("select#search_game", value="-1", timeout=5_000)
        hf.evaluate("""
            () => document.querySelectorAll('input#search_status:not(:checked)').forEach(cb => cb.click())
        """)
        try: hf.click("button:text('1개월')", timeout=3_000); time.sleep(1)
        except: pass
        try: hf.select_option("select[name='spc']", value="200", timeout=3_000)
        except: pass
        hf.click("button#btn_submit", timeout=5_000)
        hf.wait_for_load_state("networkidle", timeout=20_000)
        time.sleep(4)
        body3 = hf.inner_text("body")
        m3 = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body3)
        count3 = int(m3.group(1).replace(',','')) if m3 else 0
        print(f"  게임=전체 검색 건수: {count3}건")
        for line in body3.split('\n'):
            line = line.strip()
            if '검색 건수' in line: print(f"  건수 상세: {line[:150]}")

        # 결과 요약
        print(f"\n{'='*50}")
        print("[테스트 결과 요약]")
        print(f"  탭 클릭 없음: {count1}건")
        print(f"  한국어 탭 클릭: {count2}건")
        print(f"  게임=전체: {count3}건")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
