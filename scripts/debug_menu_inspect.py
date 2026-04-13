#!/usr/bin/env python3
"""
debug_menu_inspect.py — console.withhive.com 메뉴 구조 파악
"""

import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[ERROR] playwright 미설치")
    sys.exit(1)

SCRIPTS_DIR   = Path(__file__).parent
RAW_DIR       = SCRIPTS_DIR / "raw"
COOKIE_FILE   = RAW_DIR / "hive_cookies.json"
CONFIG_FILE   = SCRIPTS_DIR.parent / "config.local.json"
CONSOLE_MAIN  = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
RAW_DIR.mkdir(exist_ok=True)


def load_credentials():
    import os
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("hive_id", ""), cfg.get("hive_pw", "")
    return "", ""


def load_cookies(ctx):
    if COOKIE_FILE.exists():
        try:
            cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            ctx.add_cookies(cookies)
            print(f"[INFO] 쿠키 로드 {len(cookies)}개")
            return True
        except:
            pass
    return False


def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")


def do_login(page, ctx, hive_id, hive_pw):
    print(f"[로그인]")
    page.goto(PLATFORM_LOGIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.fill("#userId", hive_id, timeout=5_000)
    page.fill("#passWd", hive_pw, timeout=5_000)
    page.click("button:text('로그인')", timeout=5_000)
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
    ok = "platform.withhive.com" not in page.url
    if ok:
        save_cookies(ctx)
        print(f"[OK] 로그인 성공 → {page.url}")
    return ok


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

        # console 진입
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

        if "platform.withhive.com" in page.url:
            if not do_login(page, ctx, hive_id, hive_pw):
                browser.close()
                sys.exit(1)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)

        print(f"[console] {page.url}")

        # ── 페이지 구조 파악 ──
        print("\n[1] frame 목록:")
        for f in page.frames:
            print(f"  - {f.url}")

        print("\n[2] console 메인 iframe 내 링크 목록:")
        # home iframe 찾기
        home_frame = None
        for f in page.frames:
            if "home" in f.url:
                home_frame = f
                break

        if home_frame:
            links = home_frame.evaluate("""
                () => Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.textContent.trim(),
                    href: a.getAttribute('href') || '',
                    onclick: a.getAttribute('onclick') || '',
                    class: a.className || ''
                })).filter(l => l.text.length > 0)
            """)
            for lnk in links:
                print(f"  [{lnk['text'][:20]}] href={lnk['href']} onclick={lnk['onclick'][:50]} class={lnk['class'][:30]}")
        else:
            print("  home frame 없음 — 메인 페이지에서 직접 탐색")

        # 메인 페이지 링크
        links_main = page.evaluate("""
            () => Array.from(document.querySelectorAll('a')).map(a => ({
                text: a.textContent.trim().replace(/\\s+/g, ' '),
                href: a.getAttribute('href') || '',
                onclick: a.getAttribute('onclick') || '',
                class: a.className || ''
            })).filter(l => l.text.length > 0 && l.text.length < 30)
        """)
        print("\n[3] 메인 페이지 전체 링크 목록:")
        for lnk in links_main:
            if any(kw in lnk['text'] for kw in ['문의', '고객', 'CS', 'cs', '목록', '센터']):
                print(f"  ★ [{lnk['text']}] onclick={lnk['onclick'][:60]}")
            else:
                print(f"  [{lnk['text']}]")

        # showContents 관련 요소 찾기
        show_contents = page.evaluate("""
            () => Array.from(document.querySelectorAll('[onclick*="showContents"]')).map(el => ({
                tag: el.tagName,
                text: el.textContent.trim().replace(/\\s+/g, ' '),
                onclick: el.getAttribute('onclick') || ''
            }))
        """)
        print("\n[4] showContents 관련 요소:")
        for el in show_contents:
            print(f"  [{el['text'][:30]}] onclick={el['onclick'][:60]}")

        # 메뉴 415 탐색 (문의 목록 menu_cd)
        menu_415 = page.evaluate("""
            () => Array.from(document.querySelectorAll('*')).filter(el => {
                var onclick = el.getAttribute('onclick') || '';
                var href = el.getAttribute('href') || '';
                return onclick.includes('415') || href.includes('415');
            }).map(el => ({
                tag: el.tagName,
                text: el.textContent.trim().replace(/\\s+/g, ' ').substring(0, 30),
                onclick: el.getAttribute('onclick') || '',
                href: el.getAttribute('href') || ''
            }))
        """)
        print("\n[5] menu=415 관련 요소:")
        for el in menu_415:
            print(f"  [{el['text']}] onclick={el['onclick'][:60]}")

        # 전체 body 텍스트에서 메뉴 키워드 탐색
        body_text = page.inner_text("body")
        print(f"\n[6] body 텍스트 중 '문의' 포함 부분:")
        for line in body_text.split('\n'):
            if '문의' in line and len(line.strip()) < 50:
                print(f"  '{line.strip()}'")

        # "문의 목록" 클릭 시도 후 frame 변화 관찰
        print("\n[7] '문의 목록' 클릭 시도 →")
        try:
            page.click("a:text('문의 목록')", timeout=3_000)
            print("  클릭 성공")
        except Exception as e:
            print(f"  클릭 실패: {e}")
            # 다른 방법
            try:
                page.evaluate("""
                    () => {
                        var els = Array.from(document.querySelectorAll('*'));
                        for (var el of els) {
                            if (el.textContent.trim() === '문의 목록' && el.children.length === 0) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                print("  JS click 시도")
            except:
                pass

        time.sleep(3)
        print("\n[8] 클릭 후 frame 목록:")
        for f in page.frames:
            print(f"  - {f.url}")

        # console nav frame이 있으면 그 안에서 탐색
        print("\n[9] 각 frame 내 '문의 목록' 관련 요소:")
        for f in page.frames:
            try:
                els = f.evaluate("""
                    () => Array.from(document.querySelectorAll('*')).filter(el => {
                        return el.textContent.trim() === '문의 목록' && el.children.length === 0;
                    }).map(el => ({
                        tag: el.tagName,
                        onclick: el.getAttribute('onclick') || '',
                        href: el.getAttribute('href') || ''
                    }))
                """)
                if els:
                    print(f"  Frame {f.url[:50]}: {els}")
            except:
                pass

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
