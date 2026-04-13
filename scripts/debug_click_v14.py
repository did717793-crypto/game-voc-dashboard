#!/usr/bin/env python3
"""
debug_click_v14.py — 검색 버튼 실제 작동 증명
================================================
목적: 검색 버튼 클릭 후 요약바/테이블이 실제로 갱신되는지 증명
조건: 한국어탭 / DK:REBORN(sg=2474) / 2026-04-03~2026-04-10 / ss_1~ss_7 ALL
기준: 검색건수=19 / 답변완료=13 / 조회완료=6

클릭 순서:
  1. 일반 클릭 (scroll_into_view + click)
  2. force click
  3. JS click
  4. bounding box 좌표 클릭 (중앙 → 오른쪽 치우침)
각 시도마다 요약바 변경 여부로 성공 판정
"""

import json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS_DIR  = Path(__file__).parent
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE  = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"
DKR_GAME_ID  = "2474"
START_DATE   = "2026-04-03"
END_DATE     = "2026-04-10"
KST          = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────────────────────────────────────
# HELPER: parse_summary_text
# ──────────────────────────────────────────────────────────────────────────────
def parse_summary_text(frame):
    body = frame.locator("body").inner_text(timeout=5000)
    m = re.search(
        r"검색\s*건수\s*:\s*(\d+).*?"
        r"접수\s*완료\s*:\s*(\d+).*?"
        r"처리\s*중\s*:\s*(\d+).*?"
        r"답변\s*완료\s*:\s*(\d+).*?"
        r"조회\s*완료\s*:\s*(\d+).*?"
        r"삭제\s*:\s*(\d+).*?"
        r"관리자\s*삭제\s*:\s*(\d+)",
        body,
        re.S
    )
    if not m:
        return None
    return {
        "total":        int(m.group(1)),
        "received":     int(m.group(2)),
        "in_progress":  int(m.group(3)),
        "answered":     int(m.group(4)),
        "viewed":       int(m.group(5)),
        "deleted":      int(m.group(6)),
        "admin_deleted":int(m.group(7)),
    }


def wait_summary_change(frame, before, timeout_ms=10000):
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


def click_search_button_strong(page, frame, selector="button#btn_submit"):
    btn = frame.locator(selector)
    btn.wait_for(state="visible", timeout=10000)
    before = parse_summary_text(frame)
    print(f"  [클릭 전 요약] {before}")

    # 1. 일반 클릭
    print("  [시도1] 일반 클릭 (scroll_into_view + click)")
    try:
        btn.scroll_into_view_if_needed(timeout=3000)
        btn.click(timeout=3000)
        changed = wait_summary_change(frame, before, timeout_ms=8000)
        if changed is not None:
            return ("normal_click", before, changed)
        print("    → 요약바 변경 없음")
    except Exception as e:
        print(f"    → 예외: {e}")

    # 2. force click
    print("  [시도2] force click")
    try:
        btn.click(timeout=3000, force=True)
        changed = wait_summary_change(frame, before, timeout_ms=8000)
        if changed is not None:
            return ("force_click", before, changed)
        print("    → 요약바 변경 없음")
    except Exception as e:
        print(f"    → 예외: {e}")

    # 3. JS click
    print("  [시도3] JS click")
    try:
        frame.evaluate("""
            (sel) => {
                const el = document.querySelector(sel);
                if (!el) throw new Error("search button not found");
                el.scrollIntoView({block: "center"});
                el.click();
            }
        """, selector)
        changed = wait_summary_change(frame, before, timeout_ms=8000)
        if changed is not None:
            return ("js_click", before, changed)
        print("    → 요약바 변경 없음")
    except Exception as e:
        print(f"    → 예외: {e}")

    # 4. bounding box 좌표 클릭
    print("  [시도4] bounding box 좌표 클릭")
    try:
        box = btn.bounding_box(timeout=3000)
        if box:
            frame_el = page.locator("iframe[name='HIVEframe'], #consoleContents").first
            frame_box = frame_el.bounding_box()
            if frame_box:
                # 중앙
                x  = frame_box["x"] + box["x"] + box["width"] / 2
                y  = frame_box["y"] + box["y"] + box["height"] / 2
                print(f"    → bbox 중앙 클릭: ({x:.1f}, {y:.1f})")
                page.mouse.click(x, y)
                changed = wait_summary_change(frame, before, timeout_ms=8000)
                if changed is not None:
                    return ("bbox_center_click", before, changed)
                print("    → 요약바 변경 없음 (중앙)")

                # 오른쪽 치우침
                x2 = frame_box["x"] + box["x"] + box["width"] * 0.8
                y2 = frame_box["y"] + box["y"] + box["height"] / 2
                print(f"    → bbox offset 클릭: ({x2:.1f}, {y2:.1f})")
                page.mouse.click(x2, y2)
                changed = wait_summary_change(frame, before, timeout_ms=8000)
                if changed is not None:
                    return ("bbox_offset_click", before, changed)
                print("    → 요약바 변경 없음 (offset)")
        else:
            print("    → bounding box 없음")
    except Exception as e:
        print(f"    → 예외: {e}")

    raise RuntimeError("검색 버튼 클릭 실패: 어떤 방식으로도 결과 갱신이 발생하지 않음")


# ──────────────────────────────────────────────────────────────────────────────
# 기타 헬퍼
# ──────────────────────────────────────────────────────────────────────────────
def load_credentials():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return cfg["hive_id"], cfg["hive_pw"]

def load_cookies(ctx):
    if COOKIE_FILE.exists():
        ctx.add_cookies(json.loads(COOKIE_FILE.read_text()))
        print(f"  쿠키 로드: {len(json.loads(COOKIE_FILE.read_text()))}개")
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
            page.click(sel, timeout=2_000)
            time.sleep(1)
            break
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


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print(f"  검색 버튼 실제 작동 증명 v14")
    print(f"  조건: DKR(2474) / {START_DATE}~{END_DATE} / ss_1~ss_7 ALL")
    print(f"  기준: 검색건수=19 / 답변완료=13 / 조회완료=6")
    print("=" * 65)

    hid, hpw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        load_cookies(ctx)
        page = ctx.new_page()

        # ── [A] 로그인 확인 ──────────────────────────────────────────────────
        print("\n[A] 로그인 확인")
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
        if "platform.withhive.com" in page.url:
            print("  세션 만료 → 재로그인")
            do_login(page, ctx, hid, hpw)
            page.goto(CONSOLE_MAIN, timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=15_000)
            time.sleep(2)
        print(f"  URL: {page.url}")
        logged_in = "platform" not in page.url and "withhive.com" in page.url
        print(f"  로그인: {'✅ OK' if logged_in else '❌ 실패'}")
        if not logged_in:
            browser.close(); return

        # ── [B] HIVEframe 진입 ───────────────────────────────────────────────
        print("\n[B] HIVEframe 진입")
        hf = None
        for _ in range(10):
            hf = find_inquiry_frame(page)
            if hf: break
            time.sleep(1)

        if not hf:
            print("  HIVEframe 없음 → 문의 목록 메뉴 클릭")
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try:
                    page.click(sel, timeout=3_000)
                    print(f"  클릭: {sel}")
                    break
                except Exception:
                    pass
            for i in range(20):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf:
                    break
                if (i+1) % 5 == 0:
                    print(f"  대기 {i+1}초...")

        if not hf:
            print("  JS fallback: iframe src 직접 설정")
            INQUIRY_BASE = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
            page.evaluate(f"() => {{ var el = document.querySelector('#consoleContents, iframe[name=\"HIVEframe\"]'); if(el) el.src = '{INQUIRY_BASE}'; }}")
            for _ in range(15):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf: break

        if not hf:
            print("  ❌ HIVEframe 진입 실패 → 종료")
            browser.close(); return
        print(f"  ✅ iframe URL: {hf.url}")

        # ── [C] 한국어 탭 직접 로드 ─────────────────────────────────────────
        print("\n[C] 한국어 탭 직접 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print(f"  frame URL: {hf.url}")
        hidden_lang = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || ''")
        print(f"  hidden lang: {hidden_lang}  {'✅' if hidden_lang == '0014010001' else '❌ WARN'}")

        # 초기 요약 확인
        init_summary = parse_summary_text(hf)
        print(f"  초기 요약: {init_summary}")

        # ── [D] 게임 선택 DKR(2474) ─────────────────────────────────────────
        print(f"\n[D] 게임 선택 DKR({DKR_GAME_ID})")
        try:
            opts = hf.evaluate("""
                () => Array.from(document.querySelectorAll('select#search_game option'))
                    .map(o => ({v: o.value, t: o.textContent.trim()}))
            """)
            print(f"  옵션 수: {len(opts)}")
            dkr_found = any(o['v'] == DKR_GAME_ID for o in opts)
            print(f"  DKR(2474) 옵션: {'✅ 있음' if dkr_found else '❌ 없음'}")
            if not dkr_found:
                print(f"  사용 가능 옵션: {[(o['v'], o['t']) for o in opts[:5]]}")
                browser.close(); return
            hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
            selected = hf.evaluate("() => document.querySelector('select#search_game')?.value || ''")
            print(f"  선택값: {selected}  {'✅' if selected == DKR_GAME_ID else '❌'}")
        except Exception as e:
            print(f"  ❌ 게임 선택 실패: {e}")
            browser.close(); return

        # ── [E] ss_* 전체 체크 ─────────────────────────────────────────────
        print(f"\n[E] ss_* 전체 체크")
        cb_names = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                .map(cb => ({n: cb.name, c: cb.checked}))
        """)
        print(f"  초기 ss_* 상태: {[(c['n'], c['c']) for c in cb_names]}")
        for cb in cb_names:
            if not cb['c']:
                name = cb['n']
                try:
                    hf.check(f"input[name='{name}']", timeout=2_000)
                except Exception:
                    hf.evaluate(f"() => {{ var el = document.querySelector('input[name=\"{name}\"]'); if(el && !el.checked) el.click(); }}")
        time.sleep(0.3)
        cb_after = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                .map(cb => ({n: cb.name, c: cb.checked}))
        """)
        all_checked = all(c['c'] for c in cb_after)
        print(f"  체크 후: {[(c['n'], c['c']) for c in cb_after]}")
        print(f"  전체 체크: {'✅ OK' if all_checked else '❌ WARN'}")

        # ── [F] 날짜 설정 (JS 직접) ─────────────────────────────────────────
        print(f"\n[F] 날짜 설정: {START_DATE} ~ {END_DATE}")
        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{START_DATE} - {END_DATE}';
                if (sds) sds.value = '{START_DATE}';
                if (sde) sde.value = '{END_DATE}';
            }}
        """)
        time.sleep(0.3)
        d = hf.evaluate("""
            () => ({
                sdf: document.querySelector('#search_date, input[name="sdf"]')?.value || '',
                sds: document.querySelector('input[name="sds"]')?.value || '',
                sde: document.querySelector('input[name="sde"]')?.value || ''
            })
        """)
        print(f"  sdf={d['sdf']}")
        print(f"  sds={d['sds']}  {'✅' if d['sds'] == START_DATE else '❌'}")
        print(f"  sde={d['sde']}  {'✅' if d['sde'] == END_DATE else '❌'}")

        # 클릭 직전 최종 요약
        before_summary = parse_summary_text(hf)
        print(f"\n[클릭 전 최종 요약]: {before_summary}")

        # ── [G] 강제 클릭 실행 ───────────────────────────────────────────────
        print(f"\n[G] 검색 버튼 강제 클릭 (4단계)")
        click_method = None
        before = None
        after = None
        try:
            click_method, before, after = click_search_button_strong(page, hf, "button#btn_submit")
            print(f"\n  ✅ 클릭 성공 방식: [{click_method}]")
            print(f"  클릭 전 요약: {before}")
            print(f"  클릭 후 요약: {after}")
        except RuntimeError as e:
            print(f"\n  ❌ {e}")
            # 실패해도 현재 상태 읽기
            after = parse_summary_text(hf)
            print(f"  현재 요약 (갱신 없음): {after}")

        # ── [H] 결과 row 읽기 ────────────────────────────────────────────────
        print(f"\n[H] 결과 테이블")
        rows = read_rows(hf)
        print(f"  총 row 수: {len(rows)}개")
        if rows:
            print(f"\n  첫 {min(5, len(rows))}개 row raw text:")
            for i, row in enumerate(rows[:5]):
                print(f"  row[{i+1}]: {row}")
        else:
            print("  row 없음")

        # ── [I] 최종 증거 출력 ───────────────────────────────────────────────
        print("\n" + "=" * 65)
        print("  최종 증거 출력")
        print("=" * 65)
        print(f"  [1] 검색 전 요약바:    {before_summary}")
        print(f"  [2] 검색 후 요약바:    {after}")
        print(f"  [3] 클릭 성공 방식:    {click_method or '없음 (갱신 실패)'}")
        print(f"  [4] 검색 후 row 수:    {len(rows)}")
        print(f"  [5] 사용한 iframe URL: {hf.url}")
        print(f"  [6] 검색 후 frame URL: {hf.url}")

        # 검색 건수 텍스트 원문
        try:
            count_text = hf.evaluate("""
                () => {
                    var m = document.body.innerText.match(/검색 건수.{0,200}/);
                    return m ? m[0].replace(/\\n/g,' ').trim() : '읽기 실패';
                }
            """)
            print(f"  [7] 검색 건수 DOM 원문: {count_text}")
        except Exception as e:
            print(f"  [7] 검색 건수 DOM 읽기 실패: {e}")

        # 기준값 대조
        print(f"\n  [기준값 대조]")
        print(f"  {'항목':12} {'기준':>8} {'실제':>8} {'일치':>6}")
        print(f"  {'-'*40}")
        expected = {"total": 19, "received": 0, "in_progress": 0,
                    "answered": 13, "viewed": 6, "deleted": 0, "admin_deleted": 0}
        labels   = {"total": "검색건수", "received": "접수완료", "in_progress": "처리중",
                    "answered": "답변완료", "viewed": "조회완료", "deleted": "삭제", "admin_deleted": "관리자삭제"}
        if after:
            for k, exp in expected.items():
                actual = after.get(k, -1)
                ok = "✅" if actual == exp else "❌"
                print(f"  {labels[k]:12} {exp:>8} {actual:>8} {ok:>6}")
        else:
            print("  요약 없음 — 기준값 대조 불가")

        print("\n" + "=" * 65)
        browser.close()


if __name__ == "__main__":
    main()
