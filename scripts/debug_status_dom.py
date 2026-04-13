#!/usr/bin/env python3
"""
debug_status_dom.py — 상태 필터 DOM 정밀 분석 + 기간 버튼 탐색
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
    page.fill("#userId", hid)
    page.fill("#passWd", hpw)
    page.click("button:text('로그인')")
    time.sleep(3)
    for sel in ["button:text('확인')", ".modal button:text('확인')"]:
        try: page.click(sel, timeout=2_000); time.sleep(1); break
        except: pass
    page.wait_for_load_state("networkidle", timeout=30_000)
    time.sleep(2)
    if "platform.withhive.com" not in page.url:
        save_cookies(ctx); print(f"[OK] 로그인"); return True
    return False


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

        # HIVEframe 찾기
        hf = None
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                hf = f; break
        if not hf:
            print("[ERROR] HIVEframe 없음")
            browser.close(); return

        print(f"[HIVEframe] {hf.url}")

        # 1. 한국어 탭
        try:
            hf.click("a:text('한국어')", timeout=5_000)
            hf.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)
            print("[OK] 한국어 탭")
        except Exception as e:
            print(f"[WARN] 한국어 탭: {e}")

        # 2. DKR 선택
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        print(f"[OK] 게임 선택")

        # 3. 상태 섹션 전체 HTML 덤프
        status_html = hf.evaluate("""
            () => {
                // "상태" 키워드 포함 섹션 찾기
                var sections = Array.from(document.querySelectorAll('tr, div, li, dl, table')).filter(el => {
                    return el.children.length > 0 && el.textContent.includes('상태');
                });
                // 가장 작은(구체적인) 섹션 반환
                sections.sort((a,b) => a.innerHTML.length - b.innerHTML.length);
                return sections.slice(0,3).map(s => ({
                    tag: s.tagName,
                    class: s.className,
                    html: s.innerHTML.substring(0,1000)
                }));
            }
        """)
        print("\n[A] 상태 섹션 HTML (후보 3개):")
        for i, s in enumerate(status_html):
            print(f"\n  [{i}] {s['tag']}.{s['class']}:")
            print(f"  {s['html'][:300]}")

        # 4. 모든 체크박스 상세 (label 포함)
        all_cbs = hf.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => {
                    // 상위 요소에서 텍스트 추출
                    var parent = cb.parentElement;
                    var text = '';
                    for (var i = 0; i < 4; i++) {
                        if (!parent) break;
                        text = parent.textContent.trim().replace(/\\s+/g,' ').substring(0,40);
                        if (text.length > 0) break;
                        parent = parent.parentElement;
                    }
                    var lbl = document.querySelector('label[for="' + (cb.id||'__none__') + '"]');
                    return {
                        id: cb.id || '',
                        name: cb.name || '',
                        value: cb.value || '',
                        checked: cb.checked,
                        label_el: lbl ? lbl.textContent.trim() : '',
                        parent_text: text,
                        class: cb.className || ''
                    };
                });
            }
        """)
        print(f"\n[B] 전체 체크박스 ({len(all_cbs)}개):")
        for cb in all_cbs:
            mark = "✓" if cb['checked'] else "✗"
            print(f"  [{mark}] id={cb['id']} name={cb['name']} val={cb['value']} lbl='{cb['label_el']}' parent='{cb['parent_text'][:30]}'")

        # 5. 기간 관련 요소 탐색
        period_els = hf.evaluate("""
            () => {
                var kw = ['1개월', '3개월', '7일', '오늘', '직접입력', '1 month', '3 months'];
                var result = [];
                kw.forEach(function(k) {
                    var els = Array.from(document.querySelectorAll('a, button, span, label')).filter(
                        el => el.textContent.trim() === k || el.textContent.trim().includes(k)
                    );
                    els.forEach(el => result.push({
                        keyword: k,
                        tag: el.tagName,
                        text: el.textContent.trim().substring(0,20),
                        class: el.className.substring(0,30),
                        onclick: (el.getAttribute('onclick')||'').substring(0,50),
                        href: el.getAttribute('href')||''
                    }));
                });
                return result;
            }
        """)
        print(f"\n[C] 기간 관련 요소:")
        for el in period_els:
            print(f"  [{el['keyword']}] {el['tag']} class={el['class']} onclick={el['onclick']}")

        # 6. 날짜 input 요소
        date_inputs = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[type="date"], input[type="text"]')).filter(
                inp => inp.name && (inp.name.includes('date') || inp.id.includes('date'))
            ).map(inp => ({id: inp.id, name: inp.name, value: inp.value, type: inp.type}))
        """)
        print(f"\n[D] 날짜 input 요소:")
        for inp in date_inputs:
            print(f"  id={inp['id']} name={inp['name']} val={inp['value']} type={inp['type']}")

        # 7. "전체" 버튼 탐색 (상태 섹션)
        all_btns = hf.evaluate("""
            () => {
                var els = Array.from(document.querySelectorAll('a, button, input[type="button"], span')).filter(
                    el => el.textContent.trim() === '전체' || (el.type === 'button' && el.value === '전체')
                );
                return els.map(el => {
                    var rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        text: el.textContent.trim(),
                        class: el.className,
                        onclick: (el.getAttribute('onclick')||'').substring(0,80),
                        id: el.id,
                        top: Math.round(rect.top),
                        left: Math.round(rect.left)
                    };
                });
            }
        """)
        print(f"\n[E] '전체' 요소 목록:")
        for b in all_btns:
            print(f"  {b['tag']} id={b['id']} class={b['class']} onclick={b['onclick']} top={b['top']}")

        # 8. 검색 버튼 탐색
        search_btns = hf.evaluate("""
            () => Array.from(document.querySelectorAll('button, input[type="submit"]')).filter(
                el => el.id === 'btn_submit' || el.textContent.trim() === '검색'
            ).map(el => ({id: el.id, text: el.textContent.trim(), class: el.className}))
        """)
        print(f"\n[F] 검색 버튼: {search_btns}")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
