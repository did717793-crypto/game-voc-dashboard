#!/usr/bin/env python3
"""
debug_network.py — 검색 AJAX 네트워크 요청/응답 모니터링
============================================================
목적:
  1. 검색 버튼 클릭 시 어떤 XHR 요청이 발생하는지 확인
  2. 서버 응답 코드/본문 확인
  3. 필터 없는 기본 검색 → DKR 필터 검색 비교
  4. "내 상담" 탭 vs "한국어" 탭 응답 비교
"""
import json, sys, time, re
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Route, Request
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


def capture_search_request(hf, page, label=""):
    """
    검색 버튼 클릭 시 발생하는 네트워크 요청 캡처
    """
    print(f"\n{'='*55}")
    print(f"[네트워크 테스트: {label}]")
    print(f"{'='*55}")

    # 검색 버튼 클릭 전 상태
    pre_state = hf.evaluate("""
        () => ({
            game: document.querySelector('select#search_game')?.value,
            date: document.querySelector('#search_date')?.value,
            status_checked: Array.from(document.querySelectorAll('input#search_status:checked')).map(cb => cb.name),
            status_unchecked: Array.from(document.querySelectorAll('input#search_status:not(:checked)')).map(cb => cb.name)
        })
    """)
    print(f"  [클릭 전 필터]")
    print(f"    게임: {pre_state['game']}")
    print(f"    날짜: {pre_state['date']}")
    print(f"    상태 체크: {pre_state['status_checked']}")
    print(f"    상태 미체크: {pre_state['status_unchecked']}")

    # 네트워크 요청 수집용 리스트
    captured = []

    def on_request(request):
        if "inquiry" in request.url or "search" in request.url.lower():
            captured.append({
                "type": "request",
                "method": request.method,
                "url": request.url,
                "post_data": request.post_data or ""
            })

    def on_response(response):
        if "inquiry" in response.url or "search" in response.url.lower():
            try:
                body = response.body()
                body_str = body.decode('utf-8', errors='replace')[:500]
            except:
                body_str = "(body 없음)"
            captured.append({
                "type": "response",
                "status": response.status,
                "url": response.url,
                "body_preview": body_str
            })

    # 이벤트 리스너 등록 (page 레벨에서)
    page.on("request", on_request)
    page.on("response", on_response)

    # 검색 버튼 클릭
    print(f"\n  [검색 버튼 클릭]")
    try:
        hf.click("button#btn_submit", timeout=5_000)
        print(f"    click() 성공")
    except Exception as e:
        print(f"    click() 실패: {e}")
        # JS로 클릭 시도
        r = hf.evaluate("() => { var btn = document.querySelector('button#btn_submit'); if(btn){btn.click(); return 'JS click OK';} return 'NOT FOUND'; }")
        print(f"    JS click: {r}")

    # 결과 대기 (table row 또는 검색건수 텍스트 기준)
    print(f"  [결과 로딩 대기]")
    waited = 0
    count = 0
    for i in range(20):  # 최대 20초
        time.sleep(1)
        waited += 1
        body_text = hf.inner_text("body")
        m = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body_text)
        if m:
            count = int(m.group(1).replace(',',''))
            print(f"    {waited}초 후 결과 확인: {count}건")
            break
        # 테이블 row 확인
        row_count = hf.evaluate("""
            () => document.querySelectorAll('table tbody tr td').length
        """)
        if row_count > 0:
            print(f"    {waited}초 후 table td 발견: {row_count}개")
            break

    # 이벤트 리스너 해제
    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)

    # 캡처된 네트워크 요청 출력
    print(f"\n  [캡처된 네트워크 이벤트: {len(captured)}개]")
    for ev in captured:
        if ev['type'] == 'request':
            print(f"  ▶ REQ [{ev['method']}] {ev['url']}")
            if ev['post_data']:
                print(f"      POST: {ev['post_data'][:200]}")
        else:
            print(f"  ◀ RES [{ev['status']}] {ev['url']}")
            print(f"      BODY: {ev['body_preview'][:200]}")

    # 최종 검색 건수 확인
    body_final = hf.inner_text("body")
    m_final = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body_final)
    final_count = int(m_final.group(1).replace(',','')) if m_final else 0

    # 상세 카운트 라인
    for line in body_final.split('\n'):
        if '검색 건수' in line.strip():
            print(f"\n  건수 상세: {line.strip()[:150]}")

    # 테이블 rows
    rows = hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('table tbody tr').forEach(row => {
                var cells = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                if (cells.length > 5) result.push(cells);
            });
            return result.slice(0, 5);
        }
    """)
    print(f"\n  테이블 행(전체): {len(rows)}개")
    for i, row in enumerate(rows[:3]):
        print(f"  [{i+1}] {' | '.join(row[:10])}")

    return final_count, captured


def main():
    hive_id, hive_pw = load_credentials()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport={"width":1440,"height":900}, locale="ko-KR",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        load_cookies(ctx)
        page = ctx.new_page()

        # 네트워크 이벤트를 page 레벨에서 수집
        all_network = []
        def track_req(request):
            all_network.append({"type":"req", "method": request.method, "url": request.url})
        def track_res(response):
            all_network.append({"type":"res", "status": response.status, "url": response.url})
        page.on("request", track_req)
        page.on("response", track_res)

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

        # 초기 페이지 body 확인 (검색 전)
        init_body = hf.inner_text("body")
        print(f"\n[초기 페이지 상태 (검색 전)]:")
        for line in init_body.split('\n'):
            line = line.strip()
            if line and any(kw in line for kw in ['건수', '검색', '총', '접수', '처리']):
                print(f"  {line[:100]}")

        # ── 테스트 1: 아무 필터 건드리지 않고 검색 ──
        print("\n\n[TEST 1: 필터 변경 없이 바로 검색]")
        count1, net1 = capture_search_request(hf, page, label="필터 변경 없음")

        # ── 테스트 2: "내 상담" 탭에서 DKR 선택 + 전체 상태 + 검색 ──
        print("\n\n[TEST 2: 내 상담 탭 + DKR + 상태전체 + 검색]")
        # 내 상담 탭으로 이동
        try:
            hf.click("a:text('내 상담')", timeout=3_000)
            hf.wait_for_load_state("networkidle", timeout=10_000)
            time.sleep(2)
            print("  내 상담 탭 클릭")
        except Exception as e:
            print(f"  내 상담 탭 클릭 실패: {e}")

        # DKR 선택
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)

        # 상태 전체 체크 (개별 클릭)
        hf.evaluate("""
            () => document.querySelectorAll('input#search_status:not(:checked)').forEach(cb => cb.click())
        """)
        time.sleep(0.3)

        # 1개월
        try: hf.click("button:text('1개월')", timeout=3_000); time.sleep(1)
        except: pass

        # 200개
        try: hf.select_option("select[name='spc']", value="200", timeout=3_000)
        except: pass

        count2, net2 = capture_search_request(hf, page, label="내 상담 + DKR + 전체")

        # ── 테스트 3: 게임=전체(-1), 탭 없음, 상태 전체 ──
        print("\n\n[TEST 3: 게임=전체, 기본 탭, 상태 전체]")
        hf.select_option("select#search_game", value="-1", timeout=5_000)
        hf.evaluate("""
            () => document.querySelectorAll('input#search_status:not(:checked)').forEach(cb => cb.click())
        """)
        count3, net3 = capture_search_request(hf, page, label="게임=전체")

        # ── 전체 네트워크 로그 ──
        print(f"\n\n{'='*55}")
        print(f"[전체 네트워크 로그 (inquiry 관련)]")
        print(f"{'='*55}")
        for ev in all_network:
            if 'inquiry' in ev['url']:
                if ev['type'] == 'req':
                    print(f"  ▶ [{ev['method']}] {ev['url']}")
                else:
                    print(f"  ◀ [{ev['status']}] {ev['url']}")

        # ── 결과 요약 ──
        print(f"\n\n{'='*55}")
        print(f"[결과 요약]")
        print(f"  TEST 1 (필터 없음): {count1}건")
        print(f"  TEST 2 (내상담+DKR): {count2}건")
        print(f"  TEST 3 (게임=전체): {count3}건")
        print(f"{'='*55}")

        browser.close()
    print("\n[완료]")


if __name__ == "__main__":
    main()
