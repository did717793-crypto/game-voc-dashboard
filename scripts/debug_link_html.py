#!/usr/bin/env python3
"""
debug_link_html.py — '문의 목록' 링크의 data 속성 및 iframe 상태 파악
"""

import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(1)

SCRIPTS_DIR   = Path(__file__).parent
RAW_DIR       = SCRIPTS_DIR / "raw"
COOKIE_FILE   = RAW_DIR / "hive_cookies.json"
CONFIG_FILE   = SCRIPTS_DIR.parent / "config.local.json"
CONSOLE_MAIN  = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"


def load_credentials():
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("hive_id", ""), cfg.get("hive_pw", "")
    return "", ""


def load_cookies(ctx):
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        ctx.add_cookies(cookies)
        print(f"[INFO] 쿠키 로드 {len(cookies)}개")


def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")


def do_login(page, ctx, hive_id, hive_pw):
    page.goto(PLATFORM_LOGIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.fill("#userId", hive_id)
    page.fill("#passWd", hive_pw)
    page.click("button:text('로그인')")
    time.sleep(3)
    for sel in ["button:text('확인')", ".modal button:text('확인')"]:
        try:
            page.click(sel, timeout=2_000)
            time.sleep(1)
            break
        except:
            pass
    page.wait_for_load_state("networkidle", timeout=30_000)
    time.sleep(2)
    if "platform.withhive.com" not in page.url:
        save_cookies(ctx)
        print(f"[OK] 로그인 → {page.url}")
        return True
    return False


def main():
    hive_id, hive_pw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        load_cookies(ctx)
        page = ctx.new_page()

        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

        if "platform.withhive.com" in page.url:
            do_login(page, ctx, hive_id, hive_pw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(3)

        print(f"[console] {page.url}")

        # HIVEframe이 이미 있는지 확인
        print("\n[A] 초기 frame 목록:")
        for f in page.frames:
            print(f"  {f.url}")

        # '문의 목록' 링크의 전체 속성 확인
        link_attrs = page.evaluate("""
            () => {
                var links = Array.from(document.querySelectorAll('a')).filter(
                    a => a.textContent.trim() === '문의 목록'
                );
                return links.map(a => {
                    var attrs = {};
                    for (var i = 0; i < a.attributes.length; i++) {
                        attrs[a.attributes[i].name] = a.attributes[i].value;
                    }
                    return {
                        text: a.textContent.trim(),
                        attrs: attrs,
                        outerHTML: a.outerHTML.substring(0, 200)
                    };
                });
            }
        """)
        print("\n[B] '문의 목록' 링크 전체 속성:")
        for lnk in link_attrs:
            print(f"  HTML: {lnk['outerHTML']}")
            print(f"  attrs: {lnk['attrs']}")

        # iframe 요소 확인
        iframes = page.evaluate("""
            () => {
                return Array.from(document.querySelectorAll('iframe')).map(f => ({
                    id: f.id || '',
                    name: f.name || '',
                    src: f.src || '',
                    class: f.className || ''
                }));
            }
        """)
        print(f"\n[C] iframe 요소 목록: {len(iframes)}개")
        for f in iframes:
            print(f"  id={f['id']} name={f['name']} src={f['src'][:80]} class={f['class']}")

        # showContents 함수 소스 확인
        show_fn = page.evaluate("""
            () => {
                if (typeof showContents === 'function') {
                    return showContents.toString().substring(0, 500);
                }
                return 'showContents 함수 없음';
            }
        """)
        print(f"\n[D] showContents 함수:\n{show_fn}")

        # HIVEframe이 이미 있으면 사용, 없으면 클릭
        hf = None
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                hf = f
                print(f"\n[E] HIVEframe 이미 존재: {f.url}")
                break

        if not hf:
            print("\n[E] HIVEframe 없음 → '문의 목록' 클릭")
            page.click("a:text('문의 목록')", timeout=5_000)
            time.sleep(5)

            print("[E2] 클릭 후 frame 목록:")
            for f in page.frames:
                print(f"  {f.url}")

            # iframe src 변화 확인
            iframes_after = page.evaluate("""
                () => Array.from(document.querySelectorAll('iframe')).map(f => ({
                    id: f.id || '', name: f.name || '', src: f.src || ''
                }))
            """)
            print(f"[E3] 클릭 후 iframe 요소:")
            for f in iframes_after:
                print(f"  id={f['id']} name={f['name']} src={f['src'][:100]}")

            # JS로 HIVEframe 직접 로드 시도
            print("\n[F] JS로 HIVEframe src 직접 설정 시도")
            result = page.evaluate("""
                () => {
                    var inquiry_url = 'https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415';
                    var iframeEl = document.querySelector('iframe[name="HIVEframe"]') ||
                                   document.querySelector('#HIVEframe') ||
                                   document.querySelector('iframe');
                    if (!iframeEl) return {success: false, msg: 'iframe 없음'};
                    iframeEl.src = inquiry_url;
                    return {success: true, msg: 'src 설정 완료', name: iframeEl.name, id: iframeEl.id};
                }
            """)
            print(f"  결과: {result}")
            time.sleep(5)

            print("[F2] JS 설정 후 frame 목록:")
            for f in page.frames:
                print(f"  {f.url}")

            for f in page.frames:
                if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                    hf = f
                    print(f"[OK] HIVEframe 로드 성공: {f.url}")
                    break

        if hf:
            # sg select 옵션 확인
            time.sleep(3)
            game_opts = hf.evaluate("""
                () => Array.from(document.querySelectorAll('select#search_game option')).map(o => ({val: o.value, txt: o.textContent.trim()}))
            """)
            print(f"\n[G] sg select 옵션: {game_opts}")

            # 체크박스 확인
            checkboxes = hf.evaluate("""
                () => Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => {
                    var lbl = cb.id ? document.querySelector('label[for="' + cb.id + '"]') : null;
                    return {id: cb.id, checked: cb.checked, label: lbl?.textContent.trim() || ''};
                })
            """)
            print(f"\n[H] 체크박스 현재 상태:")
            for cb in checkboxes:
                print(f"  [{cb['checked']}] id={cb['id']} label={cb['label']}")
        else:
            print("\n[ERROR] HIVEframe 로드 실패")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
