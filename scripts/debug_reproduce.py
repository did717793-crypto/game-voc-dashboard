#!/usr/bin/env python3
"""
debug_reproduce.py — 스크린샷 재현 검증 v4
=============================================
[목적] 스크린샷과 동일한 결과(19건) 자동화로 재현
[기준] 한국어탭 / DK:REBORN / 2026-04-03~10 / 약 19건

[날짜 모드]
  DEBUG_MODE=True  → 2026-04-03 ~ 2026-04-10 (검증 1회 전용, flag 방식)
  DEBUG_MODE=False → report_date 기준 -7일 ~ report_date (운영)

[전략]
  Phase 1: 폼 버튼 클릭 (5가지 방식) → 결과 갱신 + ss_* 파라미터 동시 검증
  Phase 2: 폼 실패 시 → URL 직접 구성 (ss_1~ss_7 명시) + hf.goto() 전환
"""

import json, re, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

# ── 경로 / 상수 ───────────────────────────────────────────────────────────────
SCRIPTS_DIR    = Path(__file__).parent
CONFIG_FILE    = SCRIPTS_DIR.parent / "config.local.json"
COOKIE_FILE    = SCRIPTS_DIR / "raw" / "hive_cookies.json"
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"
DKR_GAME_ID    = "2474"
KST            = timezone(timedelta(hours=9))

# ── 날짜 모드 (flag 방식, 하드코딩 금지) ────────────────────────────────────
DEBUG_MODE = True   # True = 스크린샷 검증 전용 / False = 운영


def get_date_range(debug: bool, report_date: str = None) -> tuple[str, str]:
    if debug:
        return "2026-04-03", "2026-04-10"
    report_date = report_date or datetime.now(KST).strftime("%Y-%m-%d")
    end_dt   = datetime.strptime(report_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=7)
    return start_dt.strftime("%Y-%m-%d"), report_date


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


def parse_count(hf) -> int:
    """body에서 '검색 건수 : N' 파싱. 미확인이면 -1."""
    try:
        body = hf.inner_text("body")
        m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
        return int(m.group(1).replace(',', '')) if m else -1
    except Exception:
        return -1


def read_rows(hf) -> list:
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


def wait_for_result(hf, timeout_sec=20) -> tuple[int, str]:
    """검색 결과 갱신 대기. (건수, 원문텍스트) 반환."""
    for i in range(timeout_sec):
        time.sleep(1)
        c = parse_count(hf)
        if c >= 0:
            try:
                detail = hf.evaluate("""
                    () => {
                        var m = document.body.innerText.match(/검색 건수.{0,150}/);
                        return m ? m[0].replace(/\\n/g,' ') : '';
                    }
                """)
            except Exception:
                detail = f"검색 건수 : {c}"
            return c, detail
    return -1, ""


# ══════════════════════════════════════════════════════════
def main():
    start_date, end_date = get_date_range(DEBUG_MODE)
    hid, hpw = load_credentials()

    print("=" * 62)
    print(f"  재현 검증 v4  [{start_date} ~ {end_date}]  DEBUG={DEBUG_MODE}")
    print("=" * 62)

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

        # ─── [A] 로그인 확인 ───────────────────────────────────────────
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
        logged_in = "withhive.com" in page.url and "platform" not in page.url
        print(f"  URL: {page.url}")
        print(f"  로그인: {'✅ OK' if logged_in else '❌ 실패'}")
        if not logged_in:
            browser.close(); return

        # ─── [B] HIVEframe 확인 ────────────────────────────────────────
        print("\n[B] 문의 목록 진입")
        # 로그인 직후 자동 로드 대기 (최대 10초)
        for _ in range(10):
            hf = find_inquiry_frame(page)
            if hf:
                break
            time.sleep(1)

        if hf:
            print(f"  ✅ HIVEframe 이미 로드: {hf.url}")
        else:
            # 메뉴 클릭 시도
            print("  HIVEframe 없음 → 문의 목록 메뉴 클릭 시도")
            for sel in ["a[menu='415']", "a:text('문의 목록')"]:
                try:
                    page.click(sel, timeout=3_000)
                    print(f"  클릭: {sel}")
                    break
                except Exception:
                    pass
            # 클릭 후 최대 20초 대기
            for _ in range(20):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf:
                    break

        if not hf:
            # JS fallback: iframe src 직접 설정
            print("  iframe goto fallback 시도")
            INQUIRY_BASE = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
            page.evaluate(f"() => {{ var el = document.querySelector('#consoleContents, iframe[name=\"HIVEframe\"]'); if(el) el.src = '{INQUIRY_BASE}'; }}")
            for _ in range(15):
                time.sleep(1)
                hf = find_inquiry_frame(page)
                if hf:
                    break

        if not hf:
            print("  ❌ HIVEframe 진입 실패 → 종료")
            browser.close(); return
        print(f"  ✅ iframe URL: {hf.url}")

        # ─── [C] 한국어 탭 goto() ─────────────────────────────────────
        print("\n[C] 한국어 탭 직접 로드")
        hf.goto(KOREAN_TAB_URL, timeout=15_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        hidden_lang = hf.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || ''")
        print(f"  frame URL: {hf.url}")
        print(f"  hidden lang: {hidden_lang}  {'✅' if hidden_lang=='0014010001' else '❌'}")

        # ─── [D] 게임 선택 ────────────────────────────────────────────
        print("\n[D] 게임 선택 DKR(2474)")
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        selected = hf.evaluate("() => document.querySelector('select#search_game')?.value || ''")
        print(f"  선택: {selected}  {'✅' if selected==DKR_GAME_ID else '❌'}")

        # ─── [E] 기간 설정 (JS 직접) ─────────────────────────────────
        print(f"\n[E] 기간 설정: {start_date} ~ {end_date}")
        hf.evaluate(f"""
            () => {{
                var sdf = document.querySelector('#search_date, input[name="sdf"]');
                var sds = document.querySelector('input[name="sds"]');
                var sde = document.querySelector('input[name="sde"]');
                if (sdf) sdf.value = '{start_date} - {end_date}';
                if (sds) sds.value = '{start_date}';
                if (sde) sde.value = '{end_date}';
            }}
        """)
        time.sleep(0.3)
        d = hf.evaluate("() => ({sds: document.querySelector('input[name=\"sds\"]')?.value||'', sde: document.querySelector('input[name=\"sde\"]')?.value||''})")
        print(f"  반영: sds={d['sds']} sde={d['sde']}  {'✅' if d['sds']==start_date and d['sde']==end_date else '❌'}")

        # 페이지크기
        try:
            hf.select_option("select[name='spc']", value="50", timeout=3_000)
        except Exception:
            pass

        # ─── [F] Phase 1: 폼 버튼 클릭 5가지 방식 ────────────────────
        print("\n[F] Phase 1 — 검색 버튼 클릭 (5가지 방식)")

        captured = []
        def track(req):
            if "inquiry.withhive.com/inquiry?" in req.url and "menu_cd=415" in req.url:
                captured.append(req.url)
        page.on("request", track)

        # 클릭 전 기준값
        count_before = parse_count(hf)
        print(f"  클릭 전 검색 건수: {count_before}건")

        btn_methods = [
            ("방법1: hf.click(locator)",   lambda: hf.click("button#btn_submit", timeout=3_000)),
            ("방법2: scroll+click",        lambda: (hf.evaluate("() => document.querySelector('button#btn_submit')?.scrollIntoView()"), time.sleep(0.3), hf.click("button#btn_submit", timeout=3_000))),
            ("방법3: bounding box 중앙",    None),   # 아래에서 처리
            ("방법4: JS .click()",         lambda: hf.evaluate("() => document.querySelector('button#btn_submit')?.click()")),
            ("방법5: dispatchEvent click", lambda: hf.evaluate("""
                () => {
                    var btn = document.querySelector('button#btn_submit');
                    if (!btn) return;
                    btn.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                }
            """)),
        ]

        phase1_success = False
        phase1_url     = ""
        phase1_count   = -1

        for idx, (label, fn) in enumerate(btn_methods):
            print(f"\n  [{idx+1}] {label}")
            try:
                if label.startswith("방법3"):
                    bb = hf.evaluate("""
                        () => {
                            var btn = document.querySelector('button#btn_submit');
                            if (!btn) return null;
                            var r = btn.getBoundingClientRect();
                            return {x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height};
                        }
                    """)
                    if not bb:
                        print("    → 버튼 bounding box 없음")
                        continue
                    print(f"    bounding box: x={bb['x']:.0f} y={bb['y']:.0f} w={bb['w']:.0f} h={bb['h']:.0f}")
                    hf.mouse.click(bb['x'], bb['y'])
                else:
                    fn()
                print(f"    → 클릭 실행 완료")
            except Exception as e:
                print(f"    → 예외: {e}")
                continue

            # 결과 갱신 대기 (5초)
            cnt, detail = wait_for_result(hf, timeout_sec=5)
            print(f"    결과: {cnt}건  /  {detail[:80]}")

            if cnt > 0:
                print(f"    ✅ 결과 갱신 확인 ({cnt}건) — Phase 1 성공")
                phase1_success = True
                phase1_count   = cnt
                if captured:
                    phase1_url = captured[-1]
                break
            elif cnt == 0:
                print(f"    ⚠ 결과 0건 (버튼 클릭됐지만 필터 문제 가능)")
                # 0건이어도 결과 갱신은 됐으므로 버튼 클릭 자체는 성공
                phase1_success = True
                phase1_count   = 0
                if captured:
                    phase1_url = captured[-1]
                break

        page.remove_listener("request", track)

        # Phase 1 URL 분석
        print(f"\n  [Phase 1 URL 분석]")
        if phase1_url:
            lang_m = re.search(r'lang=([^&]+)', phase1_url)
            sg_m   = re.search(r'[?&]sg=([^&]+)', phase1_url)
            sdf_m  = re.search(r'sdf=([^&]+)', phase1_url)
            ss_m   = re.findall(r'ss_\d+=\w+', phase1_url)
            print(f"    lang = {lang_m.group(1) if lang_m else '없음'}")
            print(f"    sg   = {sg_m.group(1) if sg_m else '없음'}")
            print(f"    sdf  = {sdf_m.group(1) if sdf_m else '없음'}")
            print(f"    ss_* = {ss_m}  {'✅ 포함' if ss_m else '❌ 없음 → 필터 문제'}")
            print(f"    full = {phase1_url[:400]}")
        else:
            print(f"    ⚠ 캡처된 요청 URL 없음")

        # ─── [G] Phase 2: 결과 0건이거나 ss_* 없으면 URL 직접 구성 ───
        ss_in_url = bool(phase1_url and re.findall(r'ss_\d+=\w+', phase1_url))
        need_phase2 = (phase1_count == 0) or (not ss_in_url)

        print(f"\n[G] Phase 2 전환 판단")
        print(f"  Phase 1 결과: {phase1_count}건 / ss_* 포함: {ss_in_url}")
        print(f"  Phase 2 필요: {'✅ YES' if need_phase2 else '❌ NO (Phase 1 충분)'}")

        phase2_count = -1
        phase2_rows  = []

        if need_phase2:
            print(f"\n  URL 직접 구성 (ss_1~ss_7 명시 포함)")

            DIRECT_URL = (
                "https://inquiry.withhive.com/inquiry?"
                "menu_cd=415&company_cd=342"
                "&lang=0014010001"
                f"&sg={DKR_GAME_ID}"
                "&sc=-1&sc2=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
                "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on&ss_7=on"
                "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
                f"&sdf={start_date}+-+{end_date}"
                f"&sds={start_date}&sde={end_date}"
                "&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1&sd_date=st"
                "&spc=50&page=1"
            )
            print(f"  URL: {DIRECT_URL[:200]}...")

            captured2 = []
            def track2(req):
                if "inquiry.withhive.com/inquiry?" in req.url:
                    captured2.append(req.url)
            page.on("request", track2)

            try:
                hf.goto(DIRECT_URL, timeout=20_000)
                hf.wait_for_load_state("networkidle", timeout=15_000)
                time.sleep(2)
                print(f"  goto() 완료: {hf.url[:120]}")
            except Exception as e:
                print(f"  ❌ goto 실패: {e}")

            phase2_count, detail2 = wait_for_result(hf, timeout_sec=10)
            print(f"\n  Phase 2 결과: {phase2_count}건")
            print(f"  상세: {detail2[:150]}")

            page.remove_listener("request", track2)

            if captured2:
                u = captured2[-1]
                ss2 = re.findall(r'ss_\d+=\w+', u)
                print(f"  요청 ss_* = {ss2}  {'✅' if ss2 else '❌'}")

            if phase2_count > 0:
                phase2_rows = read_rows(hf)

        # ─── [H] 최종 결과 테이블 ─────────────────────────────────────
        final_count = phase2_count if need_phase2 else phase1_count
        print(f"\n[H] 최종 결과")
        print(f"  사용 방식: {'URL 직접(Phase 2)' if need_phase2 else '폼 버튼(Phase 1)'}")
        print(f"  검색 건수: {final_count}건")

        if final_count > 0:
            rows = phase2_rows if need_phase2 else read_rows(hf)
            print(f"  row 수   : {len(rows)}개")
            print(f"\n  첫 {min(10, len(rows))}개 row:")
            print(f"  {'번호':>10} {'분류':^14} {'제목':^24} {'접수일':^12} {'완료일':^12} {'상태':^8} {'상담원':^8}")
            print("  " + "-" * 98)
            for i, row in enumerate(rows[:10]):
                no    = row[1] if len(row) > 1 else ''
                cat   = (row[4] if len(row) > 4 else '')[:12]
                title = (row[5] if len(row) > 5 else '')[:22]
                recv  = (row[7] if len(row) > 7 else '')[:10]
                comp  = (row[8] if len(row) > 8 else '')[:10]
                stat  = (row[9] if len(row) > 9 else '')[:6]
                agent = (row[10] if len(row) > 10 else '')[:6]
                print(f"  [{i+1:2d}] {no:>10} {cat:^14} {title:^24} {recv:^12} {comp:^12} {stat:^8} {agent:^8}")
        else:
            print("  ⚠ row 없음")

        # ─── [I] 스크린샷 대조 ────────────────────────────────────────
        EXPECTED = 19
        print(f"\n[I] 스크린샷 대조")
        checks = {
            "한국어 탭(lang=0014010001)": hidden_lang == "0014010001",
            "DK:REBORN(sg=2474) 선택":   selected == DKR_GAME_ID,
            f"기간({start_date}~{end_date})": d['sds'] == start_date,
            "검색 결과 수신":            final_count >= 0,
            f"건수 ≈{EXPECTED}건(실제:{final_count})": abs(final_count - EXPECTED) <= 5 if final_count >= 0 else False,
            "row 존재":                  final_count > 0,
        }
        for label, ok in checks.items():
            print(f"  {'✅ PASS' if ok else '❌ FAIL'} — {label}")
        all_pass = all(checks.values())
        print(f"\n  최종 판정: {'✅ 재현 성공' if all_pass else '❌ 재현 실패'}")

        # ─── [J] 날짜 처리 요약 ───────────────────────────────────────
        print(f"\n[J] 날짜 처리 방식")
        print(f"  DEBUG 방식   : flag DEBUG_MODE=True → '2026-04-03'~'2026-04-10' (검증 전용)")
        print(f"  PRODUCTION   : flag DEBUG_MODE=False → end=report_date, start=report_date-7일")
        print(f"  현재         : {'DEBUG' if DEBUG_MODE else 'PRODUCTION'} → {start_date}~{end_date}")

        print(f"\n[K] 분석 요약")
        print(f"  버튼 클릭 여부 : {'✅' if phase1_success else '❌'}")
        print(f"  Phase 1 결과   : {phase1_count}건")
        print(f"  Phase 1 ss_*   : {'포함' if ss_in_url else '없음 → URL 직접 방식 필요'}")
        if need_phase2:
            print(f"  Phase 2 결과   : {phase2_count}건")
        print(f"  최종 결론      : {'재현 성공' if all_pass else '추가 디버그 필요'}")

        print("\n" + "=" * 62)
        browser.close()


if __name__ == "__main__":
    main()
