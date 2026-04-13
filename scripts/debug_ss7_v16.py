#!/usr/bin/env python3
"""
debug_ss7_v16.py — ss_7(상담원 미배정) 미체크 상태로 검색
===========================================================
사용자 실제 화면 기준:
  ss_1~ss_6 = ON  /  ss_7(상담원 미배정) = OFF (미체크)
  결과: 19건 (답변완료 12~13, 조회완료 6~7)

자동화 이전 방식:
  ss_1~ss_7 ALL ON → 0건 (원인 확인 필요)

이번 스크립트:
  ss_7 명시적 uncheck → DOM checked=false 확인 후 검색 실행
"""

import json, re, time
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


def parse_summary(frame):
    try:
        body = frame.locator("body").inner_text(timeout=5000)
        m = re.search(
            r"검색\s*건수\s*:\s*(\d+).*?접수\s*완료\s*:\s*(\d+).*?"
            r"처리\s*중\s*:\s*(\d+).*?답변\s*완료\s*:\s*(\d+).*?"
            r"조회\s*완료\s*:\s*(\d+).*?삭제\s*:\s*(\d+).*?관리자\s*삭제\s*:\s*(\d+)",
            body, re.S
        )
        if not m:
            return None
        return {"total": int(m.group(1)), "received": int(m.group(2)),
                "in_progress": int(m.group(3)), "answered": int(m.group(4)),
                "viewed": int(m.group(5)), "deleted": int(m.group(6)),
                "admin_deleted": int(m.group(7))}
    except Exception:
        return None


def wait_change(frame, before, timeout_ms=12000):
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        now = parse_summary(frame)
        if now is not None and now != before:
            return now
        time.sleep(0.5)
    return None


def click_search(page, frame):
    btn = frame.locator("button#btn_submit")
    btn.wait_for(state="visible", timeout=10000)
    before = parse_summary(frame)
    try:
        btn.scroll_into_view_if_needed(timeout=3000)
        btn.click(timeout=3000)
        changed = wait_change(frame, before, 12000)
        if changed is not None:
            return before, changed, "normal_click"
    except Exception:
        pass
    try:
        btn.click(force=True, timeout=3000)
        changed = wait_change(frame, before, 12000)
        if changed is not None:
            return before, changed, "force_click"
    except Exception:
        pass
    try:
        frame.evaluate("() => { const el = document.querySelector('button#btn_submit'); if(el){el.scrollIntoView({block:'center'}); el.click();} }")
        changed = wait_change(frame, before, 12000)
        if changed is not None:
            return before, changed, "js_click"
    except Exception:
        pass
    after = parse_summary(frame)
    return before, after, "no_change"


def read_rows(hf):
    return hf.evaluate("""
        () => {
            var r = [];
            document.querySelectorAll('table tbody tr').forEach(function(row) {
                var cells = Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
                if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10) r.push(cells);
            });
            return r;
        }
    """)


def load_credentials():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return cfg["hive_id"], cfg["hive_pw"]

def load_cookies(ctx):
    if COOKIE_FILE.exists():
        ctx.add_cookies(json.loads(COOKIE_FILE.read_text()))

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

def find_frame(page):
    for f in page.frames:
        if ("inquiry.withhive.com" in f.url and "/inquiry" in f.url
                and "smarteditor" not in f.url.lower()
                and "inputarea" not in f.url
                and "Skin.html" not in f.url):
            return f
    return None

def get_frame(page, ctx, hid, hpw):
    page.goto(CONSOLE_MAIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(2)
    if "platform.withhive.com" in page.url:
        do_login(page, ctx, hid, hpw)
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)
    hf = None
    for _ in range(10):
        hf = find_frame(page)
        if hf: break
        time.sleep(1)
    if not hf:
        for sel in ["a[menu='415']", "a:text('문의 목록')"]:
            try: page.click(sel, timeout=3_000); break
            except Exception: pass
        for _ in range(20):
            time.sleep(1); hf = find_frame(page)
            if hf: break
    if not hf:
        BASE = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
        page.evaluate(f"() => {{ var el = document.querySelector('#consoleContents,iframe[name=\"HIVEframe\"]'); if(el) el.src='{BASE}'; }}")
        for _ in range(15):
            time.sleep(1); hf = find_frame(page)
            if hf: break
    return hf


def main():
    print("=" * 65)
    print("  ss_7(상담원 미배정) 미체크 검색 검증 v16")
    print(f"  조건: DKR(2474) / {START_DATE}~{END_DATE}")
    print(f"  ss_1~ss_6=ON  /  ss_7=OFF (사용자 실제 화면 기준)")
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

        print("\n[SETUP] HIVEframe 진입")
        hf = get_frame(page, ctx, hid, hpw)
        if not hf:
            print("  ❌ HIVEframe 진입 실패"); browser.close(); return
        print(f"  ✅ {hf.url}")

        print("\n[A] 한국어 탭 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print(f"  frame URL: {hf.url}")

        print("\n[B] DKR 게임 선택")
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        selected = hf.evaluate("() => document.querySelector('select#search_game')?.value || '?'")
        print(f"  sg={selected}  {'✅' if selected == DKR_GAME_ID else '❌'}")

        # ── [C] ss_* 상태 설정: ss_1~ss_6 ON, ss_7 OFF ──────────────────
        print("\n[C] ss_* 상태 설정 (ss_7 명시적 미체크)")

        # 초기 상태 확인
        ss_init = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                .map(cb => ({n: cb.name, c: cb.checked, v: cb.value}))
        """)
        print(f"  초기 상태: {[(x['n'], x['c']) for x in ss_init]}")

        # ss_1~ss_6 체크 ON
        for i in range(1, 7):
            name = f"ss_{i}"
            try:
                hf.check(f"input[name='{name}']", timeout=2_000)
            except Exception:
                hf.evaluate(f"() => {{ var el = document.querySelector('input[name=\"{name}\"]'); if(el && !el.checked) el.click(); }}")

        # ss_7 명시적 UNCHECK
        try:
            hf.uncheck("input[name='ss_7']", timeout=2_000)
            print("  ss_7: uncheck() 실행")
        except Exception as e:
            print(f"  ss_7: uncheck() 실패({e}) → JS로 강제 해제")
            hf.evaluate("""
                () => {
                    var el = document.querySelector('input[name="ss_7"]');
                    if (el && el.checked) { el.checked = false; el.click(); }
                    else if (el && el.checked) { el.checked = false; }
                }
            """)

        time.sleep(0.3)

        # DOM 실제 상태 재확인
        ss_after = hf.evaluate("""
            () => Array.from(document.querySelectorAll('input[name^="ss_"]'))
                .map(cb => ({
                    n: cb.name,
                    c: cb.checked,
                    label: cb.closest('label,li,span')?.textContent.trim().substring(0,15) || cb.name
                }))
        """)

        print(f"\n  [DOM checked 상태 — 설정 후]")
        all_correct = True
        for x in ss_after:
            expected = (x['n'] != 'ss_7')  # ss_7만 false여야 함
            ok = x['c'] == expected
            if not ok:
                all_correct = False
            mark = "✅" if ok else "❌"
            print(f"    {mark} {x['n']} checked={x['c']}  label={x['label']}")

        print(f"\n  ss_7 checked={[x['c'] for x in ss_after if x['n'] == 'ss_7']}  {'✅ OFF 확인' if not any(x['c'] for x in ss_after if x['n']=='ss_7') else '❌ 아직 ON'}")
        print(f"  전체 설정 정확: {'✅' if all_correct else '❌'}")

        # ── [D] 날짜 설정 ─────────────────────────────────────────────────
        print(f"\n[D] 날짜 설정: {START_DATE} ~ {END_DATE}")
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
        d = hf.evaluate("() => ({ sds: document.querySelector('input[name=\"sds\"]')?.value||'', sde: document.querySelector('input[name=\"sde\"]')?.value||'' })")
        print(f"  sds={d['sds']} {'✅' if d['sds']==START_DATE else '❌'}  sde={d['sde']} {'✅' if d['sde']==END_DATE else '❌'}")

        # form serialize 확인 (ss_7 포함 여부)
        form_ss = hf.evaluate("""
            () => {
                var form = document.querySelector('form');
                if (!form) return {};
                var fd = new FormData(form);
                var r = {};
                for (var [k,v] of fd.entries()) r[k] = v;
                return r;
            }
        """)
        ss_keys = {k: v for k, v in form_ss.items() if k.startswith('ss_')}
        print(f"\n  form 제출 ss_* 파라미터: {ss_keys}")
        print(f"  ss_7 form 포함: {'❌ 포함 안 됨 (정상)' if 'ss_7' not in ss_keys else '⚠ 포함됨'}")

        # ── [E] 검색 실행 ─────────────────────────────────────────────────
        print(f"\n[E] 검색 버튼 클릭")
        before, after, method = click_search(page, hf)
        print(f"  클릭 방식: {method}")
        print(f"  클릭 전:  {before}")
        print(f"  클릭 후:  {after}")

        # ── [F] 결과 ──────────────────────────────────────────────────────
        rows = read_rows(hf)
        print(f"\n[F] 결과 테이블")
        print(f"  row 수: {len(rows)}개")
        if rows:
            print(f"  첫 5개 row:")
            for i, r in enumerate(rows[:5]):
                print(f"    [{i+1}] {r}")

        # 검색 건수 원문
        count_text = hf.evaluate("""
            () => {
                var m = document.body.innerText.match(/검색 건수.{0,200}/);
                return m ? m[0].replace(/\\n/g,' ').trim() : '';
            }
        """)
        print(f"\n  검색 건수 DOM 원문: {count_text}")

        # ── [G] 최종 대조표 ───────────────────────────────────────────────
        print("\n" + "=" * 65)
        print("  최종 기준값 대조")
        print("=" * 65)
        expected = {"total": 19, "received": 0, "in_progress": 0,
                    "answered": 13, "viewed": 6, "deleted": 0, "admin_deleted": 0}
        labels = {"total": "검색건수", "received": "접수완료", "in_progress": "처리중",
                  "answered": "답변완료", "viewed": "조회완료", "deleted": "삭제", "admin_deleted": "관리자삭제"}
        print(f"  {'항목':12} {'기준':>8} {'실제':>8} {'일치':>6}")
        print(f"  {'─'*40}")
        if after:
            for k, exp in expected.items():
                actual = after.get(k, -1)
                ok = "✅" if actual == exp else ("△" if abs(actual-exp) <= 2 else "❌")
                print(f"  {labels[k]:12} {exp:>8} {actual:>8} {ok:>6}")
        else:
            print("  요약 없음")

        print(f"\n  사용 iframe URL:\n  {hf.url}")

        browser.close()
        print("\n[완료]")


if __name__ == "__main__":
    main()
