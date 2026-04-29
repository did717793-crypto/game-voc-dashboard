#!/usr/bin/env python3
"""
collect_cs_browser.py — DKR CS 브라우저 자동 수집기 v2.3
============================================================
변경(v2.2→v2.3):
  [FIX] ss_7(상담원 미배정) 명시적 제외 — ss_7=ON 시 서버가 0건 반환하는 버그 대응
        ss_1~ss_6만 체크, ss_7은 unchecked 상태로 강제 유지
  [검증] ss_7=OFF 상태에서 DKR 한국어 탭 19건 재현 확인 (2026-04-11)

변경(v2.1→v2.2):
  [FIX] 한국어 탭: a-tag 클릭(AJAX) → hf.goto(KOREAN_TAB_URL) 직접 로드
  [FIX] 날짜 설정: 버튼 클릭 불안정 → JS로 input value 직접 설정
  [FIX] 기본 기간: DKR 출시일(2025-04-18)부터 오늘까지 (1년치)
  [FIX] 상태 체크: hf.check() 개별 적용 + 검증 강화
  [검증] DKR 한국어 탭 1년 기준 286건 확인 (2026-04-10)

【iframe 구조 (실제 확인)】
  <iframe id="consoleContents" name="HIVEframe" src="inquiry.withhive.com/...">

【컬럼 매핑 (실제 검증)】
  cells[0]  = 체크박스
  cells[1]  = 번호
  cells[2]  = 경로
  cells[3]  = 게임명
  cells[4]  = 분류
  cells[5]  = 제목
  cells[6]  = 아이디
  cells[7]  = 문의 접수일 (YYYY-MM-DD HH:MM:SS)
  cells[8]  = 답변 완료일
  cells[9]  = 상태
  cells[10] = 상담원

【사용법】
  python3 collect_cs_browser.py               # 오늘 기준 (KST)
  python3 collect_cs_browser.py --date 2026-04-09
  python3 collect_cs_browser.py --headed      # 브라우저 창 표시
  python3 collect_cs_browser.py --no-analyze  # raw 저장만
  python3 collect_cs_browser.py --period 3    # 최근 3개월치
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("[ERROR] playwright 미설치 → pip install playwright --break-system-packages && python3 -m playwright install chromium")
    sys.exit(1)

# ── 경로 ─────────────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).parent
RAW_DIR      = SCRIPTS_DIR / "raw"
COOKIE_FILE  = RAW_DIR / "hive_cookies.json"
CONFIG_FILE  = SCRIPTS_DIR.parent / "config.local.json"
KST          = timezone(timedelta(hours=9))
RAW_DIR.mkdir(exist_ok=True)

# ── DKR 게임 ID ───────────────────────────────────────────────────────────────
DKR_GAME_ID = "2474"

# ── URL 상수 ─────────────────────────────────────────────────────────────────
CONSOLE_MAIN   = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
# 기본 inquiry URL (menu_cd=415: 문의 목록)
INQUIRY_BASE   = "https://inquiry.withhive.com/inquiry?company_cd=342&console_lang=ko&menu_cd=415"
# 한국어 탭 직접 URL (AJAX 방식이 아닌 frame.goto()로 로드)
KOREAN_TAB_URL = "https://inquiry.withhive.com/inquiry?menu_cd=415&page=1&lang=0014010001&company_cd=342"
# DKR 출시일 (한국)
DKR_LAUNCH_DATE = "2025-04-18"


# ── 자격증명 ─────────────────────────────────────────────────────────────────
def load_credentials() -> tuple[str, str]:
    import os, getpass
    hive_id = os.environ.get("HIVE_ID", "")
    hive_pw = os.environ.get("HIVE_PW", "")
    if hive_id and hive_pw:
        return hive_id, hive_pw
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            hive_id = cfg.get("hive_id", "")
            hive_pw = cfg.get("hive_pw", "")
            if hive_id and hive_pw:
                print("[INFO] config.local.json에서 자격증명 로드")
                return hive_id, hive_pw
        except Exception:
            pass
    hive_id = input("  Hive ID: ").strip()
    hive_pw = getpass.getpass("  Hive PW: ")
    return hive_id, hive_pw


# ── 쿠키 ─────────────────────────────────────────────────────────────────────
def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 쿠키 저장 ({len(ctx.cookies())}개)")


def load_cookies(ctx) -> bool:
    if not COOKIE_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        ctx.add_cookies(cookies)
        print(f"[INFO] 쿠키 로드 ({len(cookies)}개)")
        return True
    except Exception as e:
        print(f"[WARN] 쿠키 로드 실패: {e}")
        return False


# ── 로그인 ────────────────────────────────────────────────────────────────────
def do_login(page, ctx, hive_id: str, hive_pw: str) -> bool:
    print(f"[INFO] 로그인 → {PLATFORM_LOGIN}")
    try:
        page.goto(PLATFORM_LOGIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        page.fill("#userId", hive_id, timeout=5_000)
        page.fill("#passWd", hive_pw, timeout=5_000)
        print("  ID/PW 입력 완료")
        page.click("button:text('로그인')", timeout=5_000)
        print("  로그인 버튼 클릭")

        # 동시접속 팝업
        time.sleep(3)
        for sel in ["button:text('확인')", ".modal button:text('확인')", "button.btn-primary"]:
            try:
                page.click(sel, timeout=2_000)
                print(f"  동시접속 팝업 확인 ({sel})")
                time.sleep(1)
                break
            except Exception:
                pass

        page.wait_for_load_state("networkidle", timeout=30_000)
        time.sleep(3)

        if "platform.withhive.com" in page.url:
            print(f"[ERROR] 로그인 실패 ({page.url})")
            return False

        save_cookies(ctx)
        print(f"[OK] 로그인 성공 → {page.url}")
        return True

    except Exception as e:
        print(f"[ERROR] 로그인 예외: {e}")
        return False


# ── HIVEframe 진입 ────────────────────────────────────────────────────────────
def get_hive_frame(page, ctx, hive_id: str, hive_pw: str):
    """
    HIVEframe 진입 전략:
    1. console 메인 로드
    2. HIVEframe 이미 로드됐는지 먼저 확인
    3. 없으면 '문의 목록' 클릭 → 대기
    4. 그래도 없으면 JS로 iframe src 직접 설정
    """
    page.goto(CONSOLE_MAIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(3)

    # 세션 만료 → 재로그인
    if "platform.withhive.com" in page.url:
        print("[INFO] 세션 만료 → 재로그인")
        if not do_login(page, ctx, hive_id, hive_pw):
            return None
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)

    print(f"[console] {page.url}")

    # ── 방법 1: 이미 로드된 HIVEframe 확인 ──
    def find_existing_frame():
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                return f
        return None

    hf = find_existing_frame()
    if hf:
        print(f"[HIVEframe] 이미 로드됨: {hf.url}")
        return hf

    # ── 방법 2: '문의 목록' 클릭 ──
    print("[INFO] HIVEframe 없음 → '문의 목록' 클릭")
    try:
        page.click("a[menu='415']", timeout=5_000)
        print("[클릭] a[menu='415'] (문의 목록)")
    except Exception:
        try:
            page.click("a:text('문의 목록')", timeout=5_000)
            print("[클릭] '문의 목록' 텍스트 매칭")
        except Exception as e:
            print(f"[WARN] 클릭 실패: {e}")

    # 클릭 후 대기 (최대 20초)
    for i in range(20):
        time.sleep(1)
        hf = find_existing_frame()
        if hf:
            try:
                hf.wait_for_load_state("networkidle", timeout=10_000)
                time.sleep(2)
                print(f"[HIVEframe] 클릭 후 로드: {hf.url}")
                return hf
            except Exception:
                pass

    # ── 방법 3: JS로 iframe src 직접 설정 ──
    print("[INFO] 클릭 후 HIVEframe 미로드 → JS iframe src 설정 시도")
    result = page.evaluate(f"""
        () => {{
            var el = document.querySelector('#consoleContents, iframe[name="HIVEframe"], iframe');
            if (!el) return 'iframe 요소 없음';
            el.src = '{INQUIRY_BASE}';
            return 'src 설정: ' + (el.id || el.name || 'unknown');
        }}
    """)
    print(f"  JS 결과: {result}")

    for i in range(15):
        time.sleep(1)
        hf = find_existing_frame()
        if hf:
            try:
                hf.wait_for_load_state("networkidle", timeout=10_000)
                time.sleep(2)
                print(f"[HIVEframe] JS 설정 후 로드: {hf.url}")
                return hf
            except Exception:
                pass

    print("[ERROR] HIVEframe 진입 실패 — 모든 방법 소진")
    return None


# ── 상태 필터 전체 선택 ────────────────────────────────────────────────────────
def apply_status_all(hf) -> dict:
    """
    checkAll 체크박스를 2회 토글해 모든 상태 선택 보장.
    반환: {checked: [레이블...], unchecked: [레이블...], all_ok: bool}
    """
    print("\n[상태 필터] checkAll 처리 시작")

    # 현재 상태 파악
    def get_status_cbs():
        return hf.evaluate("""
            () => {
                var cbs = document.querySelectorAll('input#search_status, input[id="search_status"]');
                return Array.from(cbs).map(cb => ({
                    value: cb.value,
                    checked: cb.checked,
                    label: cb.closest('label, li, span')?.textContent.trim().substring(0, 20) || cb.value
                }));
            }
        """)

    before = get_status_cbs()
    print(f"  초기 상태: {[(c['value'], c['checked']) for c in before]}")

    # 상태 전체 선택 전략:
    # button#all_check_status = 상태 "전체" 버튼 (실제 확인)
    # 이미 모두 체크됐으면 → 2회 토글 (해제→전체선택)
    # 체크 안 된 게 있으면 → 1회 클릭 (전체 선택)
    all_checked_now = all(c['checked'] for c in before) if before else False

    def click_all_check_status():
        return hf.evaluate("""
            () => {
                // 방법 1: id=all_check_status 버튼
                var btn = document.querySelector('#all_check_status');
                if (btn) { btn.click(); return 'all_check_status'; }
                // 방법 2: 상태 섹션의 "전체" 버튼 (top~467)
                var btns = Array.from(document.querySelectorAll('button')).filter(
                    b => b.textContent.trim() === '전체'
                );
                // id=all_check (경로 전체, top≈373) 다음의 "전체" 버튼이 상태 전체
                var statusBtn = btns.find(b => b.id === 'all_check_status') || btns[btns.length-1];
                if (statusBtn) { statusBtn.click(); return 'btn-전체: ' + statusBtn.id; }
                // 방법 3: 개별 체크박스 강제 체크
                document.querySelectorAll('input#search_status').forEach(cb => {
                    if (!cb.checked) cb.click();
                });
                return 'individual';
            }
        """)

    if all_checked_now:
        # 2회 토글
        for _ in range(2):
            r = click_all_check_status()
            print(f"  토글 클릭: {r}")
            time.sleep(0.5)
    else:
        # 전체 선택될 때까지 최대 2번
        for attempt in range(2):
            cbs = get_status_cbs()
            if all(c['checked'] for c in cbs) and cbs:
                break
            r = click_all_check_status()
            print(f"  전체선택 클릭 (시도 {attempt+1}): {r}")
            time.sleep(0.5)

    # 최종 상태 확인
    after = get_status_cbs()
    checked   = [c['label'] for c in after if c['checked']]
    unchecked = [c['label'] for c in after if not c['checked']]
    all_ok    = len(unchecked) == 0 and len(checked) > 0

    print(f"  체크됨  ({len(checked)}개): {checked}")
    print(f"  미체크  ({len(unchecked)}개): {unchecked}")
    print(f"  전체선택 OK: {all_ok}")

    return {"checked": checked, "unchecked": unchecked, "all_ok": all_ok}


# ── row 파싱 ─────────────────────────────────────────────────────────────────
def parse_row(cells: list[str]) -> dict | None:
    if len(cells) < 10:
        return None

    def extract_date(s: str) -> str | None:
        m = re.match(r'(\d{4}-\d{2}-\d{2})', s.strip())
        return m.group(1) if m else None

    received = extract_date(cells[7])
    if not received:
        return None

    completed_raw = cells[8].strip()
    return {
        "ask_id":    cells[1].strip(),           # 문의 번호 — 상세 페이지 접근용
        "title":     cells[5].strip(),
        "category":  cells[4].strip(),
        "game":      cells[3].strip(),           # 게임명 (DK : REBORN / ETC 등) — 필터용
        "path":      cells[2].strip(),
        "uid":       cells[6].strip().split("\n")[0],
        "received":  received,
        "completed": extract_date(completed_raw) if completed_raw != "-" else None,
        "status":    cells[9].strip(),
        "body":      None,                       # 상세 페이지 수집 시 채워짐
    }


# ── 상세 페이지 본문 수집 ───────────────────────────────────────────────────────
_DETAIL_BASE_URL = (
    "https://inquiry.withhive.com/inquiry/view?"
    "ask_id={ask_id}&menu_cd=415&company_cd=342&lang=0014010001"
)

def fetch_inquiry_body(hf, ask_id: str) -> str:
    """
    문의 상세 페이지에서 본문(body) 추출.

    본문은 JavaScript의 content_body 변수에 HTML 형태로 저장되어 있음.
    패턴: content_body += '...<br/>...';
    확인됨 (2026-04-29): inquiry/view?ask_id=10009368 → 신화인형 본문 정상 추출
    """
    if not ask_id:
        return ""
    try:
        detail_url = _DETAIL_BASE_URL.format(ask_id=ask_id)
        hf.goto(detail_url, timeout=10_000)
        time.sleep(2)

        # HTML에서 content_body JS 변수 값 추출
        inner_html = hf.inner_html("html")
        # content_body += '...'; 패턴 (CSS 제외 — CSS는 body{} 형태)
        chunks = re.findall(r"content_body\s*\+=\s*'([^']*)'", inner_html)
        body_parts = []
        for chunk in chunks:
            # CSS body 제외
            if "font-family" in chunk or "font-size" in chunk or chunk.strip().startswith("body"):
                continue
            # HTML 태그 제거, 줄바꿈 정리
            clean = re.sub(r'<br\s*/?>', '\n', chunk, flags=re.IGNORECASE)
            clean = re.sub(r'<[^>]+>', '', clean)
            clean = re.sub(r'[\r\n]+', ' ', clean).strip()
            clean = clean.replace('. ', ' ').replace(',', ', ')  # 마침표 뒤 공백 정리
            if clean:
                body_parts.append(clean)

        return ' '.join(body_parts).strip()
    except Exception as e:
        return ""


# ── 날짜 JS 직접 설정 ────────────────────────────────────────────────────────
def set_date_range_js(hf, start: str, end: str):
    """
    날짜 input을 JS로 직접 설정 (버튼 클릭 방식은 form 반영 불안정).
    start, end: 'YYYY-MM-DD' 형식
    """
    hf.evaluate(f"""
        () => {{
            var sdf = document.querySelector('#search_date, input[name="sdf"]');
            var sds = document.querySelector('input[name="sds"]');
            var sde = document.querySelector('input[name="sde"]');
            if (sdf) sdf.value = '{start} - {end}';
            if (sds) sds.value = '{start}';
            if (sde) sde.value = '{end}';
        }}
    """)
    time.sleep(0.3)
    # 설정 확인
    result = hf.evaluate("() => document.querySelector('#search_date, input[name=\"sdf\"]')?.value || ''")
    print(f"[기간] JS 설정 → {result}")
    return result


# ── 데이터 수집 ───────────────────────────────────────────────────────────────
def collect_all_pages(hive_frame, page, start_date: str, end_date: str) -> list[dict]:
    """
    hf.goto(KOREAN_TAB_URL) + JS 날짜 설정 방식으로 DKR 문의 전체 수집.

    검증된 방법 (2026-04-10):
      - lang=0014010001 (한국어) + sg=2474 (DKR) + ss_1~ss_7 전체 + 1년 기간 → 286건
      - 날짜 버튼 클릭(button:text('3개월'))은 form 반영 불안정 → JS 직접 설정 필수
    """
    all_records: list[dict] = []

    # 1. 한국어 탭 직접 로드 (frame.goto)
    print(f"\n[STEP 1] 한국어 탭 직접 로드: {KOREAN_TAB_URL}")
    try:
        hive_frame.goto(KOREAN_TAB_URL, timeout=15_000)
        hive_frame.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print(f"  frame URL: {hive_frame.url}")
    except Exception as e:
        print(f"[ERROR] 한국어 탭 goto 실패: {e}")
        return []

    # lang 확인
    hidden_lang = hive_frame.evaluate("() => document.querySelector('input[name=\"lang\"]')?.value || ''")
    print(f"  hidden lang: {hidden_lang}")
    if hidden_lang != "0014010001":
        print(f"[WARN] lang 불일치: {hidden_lang} (기대: 0014010001)")

    # 1-b. 페이지 크기 먼저 설정 (ss_* 설정 전에 해야 AJAX 초기화 방지)
    try:
        hive_frame.select_option("select[name='spc']", value="200", timeout=3_000)
        print("  페이지크기: 200 (ss_* 설정 전 적용)")
    except Exception:
        pass
    time.sleep(0.3)

    # 2. 게임 선택: DKR
    print(f"\n[STEP 2] 게임 선택: DKR ({DKR_GAME_ID})")
    try:
        opts = hive_frame.evaluate("""
            () => Array.from(document.querySelectorAll('select#search_game option')).map(o => ({v: o.value, t: o.textContent.trim()}))
        """)
        print(f"  옵션: {[(o['v'], o['t']) for o in opts]}")
        if not any(o['v'] == DKR_GAME_ID for o in opts):
            print(f"[ERROR] DKR(2474) 옵션 없음 → 수집 불가")
            return []
        hive_frame.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        selected = hive_frame.evaluate("() => document.querySelector('select#search_game')?.value")
        print(f"  선택 값: {selected}")
        if selected != DKR_GAME_ID:
            print("[ERROR] 게임 선택 실패")
            return []
    except Exception as e:
        print(f"[ERROR] 게임 선택 예외: {e}")
        return []

    # 3. 상태 필터: ss_1~ss_6 체크 ON / ss_7(상담원 미배정) 명시적 OFF
    #    ※ ss_7=ON 시 서버가 0건을 반환하는 버그 확인 (2026-04-11)
    #      사용자 실제 화면과 동일하게 ss_7은 unchecked 유지
    print(f"\n[STEP 3] 상태 필터 설정 (ss_1~ss_6 ON / ss_7 OFF)")
    cb_names = hive_frame.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]')).map(cb => ({n: cb.name, c: cb.checked}))
    """)
    print(f"  초기 상태: {[(c['n'], c['c']) for c in cb_names]}")

    for cb in cb_names:
        cb_name = cb['n']
        if cb_name == 'ss_7':
            # ss_7: 반드시 uncheck
            try:
                hive_frame.uncheck(f"input[name='ss_7']", timeout=2_000)
            except Exception:
                hive_frame.evaluate(
                    "() => { var el = document.querySelector('input[name=\"ss_7\"]'); "
                    "if (el && el.checked) { el.checked = false; el.click(); } }"
                )
        else:
            # ss_1~ss_6: check ON
            if not cb['c']:
                try:
                    hive_frame.check(f"input[name='{cb_name}']", timeout=2_000)
                except Exception:
                    hive_frame.evaluate(f"() => {{ var el = document.querySelector('input[name=\"{cb_name}\"]'); if(el && !el.checked) el.click(); }}")
    time.sleep(0.3)

    cb_after = hive_frame.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]')).map(cb => ({n: cb.name, c: cb.checked}))
    """)
    print(f"  설정 후 상태:")
    for c in cb_after:
        expected = (c['n'] != 'ss_7')
        ok = c['c'] == expected
        mark = "✅" if ok else "❌"
        print(f"    {mark} {c['n']} checked={c['c']}")

    ss7_off = not any(c['c'] for c in cb_after if c['n'] == 'ss_7')
    ss16_on = all(c['c'] for c in cb_after if c['n'] != 'ss_7')
    print(f"  ss_7=False 확인: {'✅ OK' if ss7_off else '❌ FAIL — ss_7 아직 체크됨'}")
    print(f"  ss_1~ss_6 전체 ON: {'✅ OK' if ss16_on else '❌ WARN'}")
    if not ss7_off:
        print("[WARN] ss_7 해제 실패 — 결과가 0건으로 나올 수 있음")

    # 4. 날짜 설정 (JS 직접)
    print(f"\n[STEP 4] 날짜 JS 설정: {start_date} ~ {end_date}")
    set_date_range_js(hive_frame, start_date, end_date)

    # 5(skip). 페이지 크기는 STEP 1-b에서 이미 설정 완료

    # 6. ss_* 최종 상태 재확인 (클릭 직전)
    cb_final = hive_frame.evaluate("""
        () => Array.from(document.querySelectorAll('input[name^="ss_"]')).map(cb => ({n: cb.name, c: cb.checked}))
    """)
    print(f"\n[STEP 5] 클릭 직전 ss_* 최종 상태:")
    for c in cb_final:
        expected = (c['n'] != 'ss_7')
        ok = c['c'] == expected
        mark = "✅" if ok else "❌"
        print(f"    {mark} {c['n']} checked={c['c']}")

    # ss_7이 다시 켜진 경우 재해제
    if any(c['c'] for c in cb_final if c['n'] == 'ss_7'):
        print("  ⚠ ss_7 재체크됨 → 강제 해제")
        try:
            hive_frame.uncheck("input[name='ss_7']", timeout=2_000)
        except Exception:
            hive_frame.evaluate(
                "() => { var el = document.querySelector('input[name=\"ss_7\"]'); "
                "if (el && el.checked) { el.checked = false; } }"
            )

    # 7. 검색 실행 — 요약바 변경 감지 방식
    print(f"\n[STEP 6] 검색 버튼 클릭 (요약바 변경 감지)")

    def _parse_summary(hf):
        try:
            body = hf.inner_text("body")
            m2 = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body)
            return int(m2.group(1).replace(',', '')) if m2 else None
        except Exception:
            return None

    before_count = _parse_summary(hive_frame)
    print(f"  클릭 전 검색 건수: {before_count}")

    try:
        hive_frame.locator("button#btn_submit").scroll_into_view_if_needed(timeout=3_000)
        hive_frame.click("button#btn_submit", timeout=5_000)
        print("  클릭 완료")
    except Exception as e:
        print(f"  [ERROR] 버튼 클릭 실패: {e}")
        return []

    # 최대 30초 대기 — before와 달라진 값을 기다림
    total = 0
    for i in range(30):
        time.sleep(1)
        try:
            cur = _parse_summary(hive_frame)
            if cur is not None and cur != before_count:
                total = cur
                print(f"  [{i+1}초] 검색 건수 변경 감지: {before_count} → {total}건")
                break
            elif cur is not None and i >= 5:
                # 5초 이상 지났는데 변화 없으면 현재 값 사용
                total = cur
                print(f"  [{i+1}초] 검색 건수 (변화 없음): {total}건")
                break
        except Exception:
            pass
    else:
        print("[WARN] 검색 건수 확인 시간 초과")

    if total == 0:
        print("[WARN] 검색 결과 없음 (0건) — 필터 또는 데이터 문제")
        return []

    # 첫 row 샘플
    sample_rows = hive_frame.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('table tbody tr').forEach(function(row) {
                var cells = Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
                if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10) result.push(cells);
            });
            return result.slice(0, 3);
        }
    """)
    print(f"[샘플] 첫 페이지 {len(sample_rows)}행:")
    for i, row in enumerate(sample_rows):
        print(f"  [{i+1}] 번호={row[1]} 분류={row[4]} 제목={row[5][:20]} 접수일={row[7][:10]} 상태={row[9]}")

    # 7. 모든 페이지 순회
    page_no = 1
    while True:
        rows_data = hive_frame.evaluate("""
            () => {
                var result = [];
                document.querySelectorAll('table tbody tr').forEach(function(row) {
                    var cells = Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim());
                    if (cells.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && cells.length >= 10) result.push(cells);
                });
                return result;
            }
        """)

        page_records = [r for r in (parse_row(row) for row in rows_data) if r]
        all_records.extend(page_records)
        print(f"  [PAGE {page_no}] {len(page_records)}건 (누적: {len(all_records)}/{total})")

        if len(all_records) >= total:
            break

        # 다음 페이지 클릭
        try:
            has_next = hive_frame.evaluate("""
                () => {
                    var pagination = document.querySelectorAll('.pagination a, .pager a, [class*="paging"] a, [class*="page"] a');
                    for (var p of pagination) {
                        var txt = p.textContent.trim();
                        if (txt === '>' || txt === '다음' || p.getAttribute('aria-label') === 'Next') {
                            p.click();
                            return true;
                        }
                    }
                    var active = document.querySelector('.active > a, .on > a, .cur > a');
                    if (active) {
                        var parent = active.closest('li, span, a').parentElement;
                        var nxt = parent?.nextElementSibling?.querySelector('a');
                        if (nxt) { nxt.click(); return true; }
                    }
                    return false;
                }
            """)
            if not has_next:
                print("  [마지막 페이지]")
                break
            hive_frame.wait_for_load_state("networkidle", timeout=10_000)
            time.sleep(2)
            page_no += 1
        except Exception as e:
            print(f"  [WARN] 페이지 이동 실패: {e}")
            break

    return all_records


# ── 메인 ─────────────────────────────────────────────────────────────────────
def collect_pages_get_url(hf, start_date: str, end_date: str) -> tuple[list, list]:
    """
    GET URL 직접 호출 방식으로 특정 날짜 범위 수집.
    검증된 방식 (2026-04-28): sds/sde 파라미터가 서버에 정확히 적용됨.

    반환: (전체 records, DK:REBORN 필터 records)
    """
    from collections import Counter

    # 검증된 GET URL 템플릿
    GET_URL_TMPL = (
        "https://inquiry.withhive.com/inquiry?"
        "menu_cd=415&company_cd=342&lang=0014010001"
        f"&sg={DKR_GAME_ID}"
        "&sc=-1&sc3=-1&qs=&si=-1&sa=-1&detail_sc=-1&gsi=-1"
        "&sf_1=on&sf_2=on&sf_3=on&sf_4=on&sf_5=on&sf_6=on&sf_7=on&sf_8=on&sf_9=on"
        "&sdf={sdf}&sds={sds}&sde={sde}"
        "&ss_1=on&ss_2=on&ss_3=on&ss_4=on&ss_5=on&ss_6=on"
        "&sst=-1&stx=&agent=-1&modiCompany=-1&modiLanguage=-1"
        "&sd_date=st&spc=200&page={page}"
    )

    sdf = f"{start_date}+--+{end_date}".replace("-", "-")
    sdf_display = f"{start_date} - {end_date}"
    all_records = []
    page_no = 1

    url = GET_URL_TMPL.format(sdf=sdf_display.replace(" ", "+"), sds=start_date, sde=end_date, page=1)
    print(f"  [GET URL] {url[:130]}...")
    hf.goto(url, timeout=15_000)
    time.sleep(4)

    body = hf.inner_text("body")
    m = re.search(r"검색\s*건수\s*:?\s*([\d,]+)", body)
    total = int(m.group(1).replace(",", "")) if m else 0
    dates_v = hf.evaluate("""() => ({
        sds: document.querySelector('input[name="sds"]')?.value || '',
        sde: document.querySelector('input[name="sde"]')?.value || ''
    })""")
    print(f"  서버 적용 날짜: {dates_v['sds']} ~ {dates_v['sde']}")
    print(f"  총 건수: {total}건")

    if total == 0:
        return [], []

    while True:
        rows = hf.evaluate("""
            () => Array.from(document.querySelectorAll('table tbody tr')).map(row =>
                Array.from(row.querySelectorAll('td')).map(c => c.innerText.trim())
            ).filter(c => c.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t)) && c.length >= 10)
        """)
        page_records = [r for r in (parse_row(row) for row in rows) if r]
        all_records.extend(page_records)
        print(f"  [PAGE {page_no}] {len(page_records)}건 (누적: {len(all_records)}/{total})")

        if len(all_records) >= total:
            break

        page_no += 1
        url_next = GET_URL_TMPL.format(sdf=sdf_display.replace(" ", "+"), sds=start_date, sde=end_date, page=page_no)
        hf.goto(url_next, timeout=15_000)
        time.sleep(3)

    # DK : REBORN 필터 (이중 안전장치)
    dkr_records  = [r for r in all_records if r.get("game", "") == "DK : REBORN"]
    other_cnt    = Counter(r.get("game", "?") for r in all_records if r.get("game") != "DK : REBORN")

    print(f"\n  [필터]")
    print(f"  total_raw    = {len(all_records)}건")
    print(f"  filtered_raw = {len(dkr_records)}건 (DK : REBORN only)")
    if other_cnt:
        print(f"  제외 게임: {dict(other_cnt)}")

    # ── 상세 페이지 본문 수집 ───────────────────────────────────────
    print(f"\n  [상세 본문 수집] {len(dkr_records)}건 상세 페이지 접근 시작...")
    body_ok = 0
    for i, record in enumerate(dkr_records):
        ask_id = record.get("ask_id", "")
        if not ask_id:
            continue
        body_text = fetch_inquiry_body(hf, ask_id)
        record["body"] = body_text if body_text else None
        if body_text:
            body_ok += 1
        if (i + 1) % 10 == 0:
            print(f"    진행: {i+1}/{len(dkr_records)}건 (본문 수집: {body_ok}건)")
    print(f"  [완료] 본문 수집 성공: {body_ok}/{len(dkr_records)}건")

    return all_records, dkr_records


def main():
    today = datetime.now(KST).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="DKR CS 브라우저 자동 수집 v2.3")
    parser.add_argument("--date", "-d",
                        default=today,
                        help="분석 기준 날짜 (기본: 오늘 KST)")
    parser.add_argument("--start", "-s",
                        default=DKR_LAUNCH_DATE,
                        help=f"수집 시작일 (기본: DKR 출시일 {DKR_LAUNCH_DATE})")
    parser.add_argument("--end", "-e",
                        default=today,
                        help="수집 종료일 (기본: 오늘)")
    parser.add_argument("--headed", action="store_true", help="브라우저 창 표시")
    parser.add_argument("--no-analyze", action="store_true", help="raw 저장만")
    parser.add_argument("--get-url", action="store_true",
                        help="GET URL 직접 호출 방식 사용 (날짜 범위 정확 적용)")
    args = parser.parse_args()

    target_date = args.date
    start_date  = args.start
    end_date    = args.end
    out_file    = RAW_DIR / f"cs_raw_{target_date}.json"

    print(f"\n{'='*55}")
    print(f"  DKR CS 수집  기준날짜: {target_date}")
    print(f"  수집 기간: {start_date} ~ {end_date}")
    print(f"{'='*55}\n")

    hive_id, hive_pw = load_credentials()
    if not hive_id or not hive_pw:
        print("[ERROR] 자격증명 없음")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ko-KR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        load_cookies(ctx)
        page = ctx.new_page()

        hf = get_hive_frame(page, ctx, hive_id, hive_pw)
        if not hf:
            print("[ERROR] HIVEframe 진입 실패")
            browser.close()
            sys.exit(1)

        if args.get_url:
            # ── GET URL 방식 (날짜 범위 정확 적용) ──
            print(f"\n[MODE] GET URL 직접 호출 방식 (sds={start_date} ~ sde={end_date})")
            all_records, records = collect_pages_get_url(hf, start_date=start_date, end_date=end_date)
        else:
            # ── 기존 UI 방식 ──
            all_records = collect_all_pages(hf, page, start_date=start_date, end_date=end_date)
            records = all_records

        browser.close()

    if not records:
        print("[WARN] 수집 records 없음 → 파일 미저장")
        sys.exit(1)

    # 저장
    payload = {
        "collected_at":  datetime.now(KST).isoformat(),
        "target_date":   target_date,
        "start_date":    start_date,
        "end_date":      end_date,
        "total_raw":     len(all_records) if args.get_url else len(records),
        "filtered_raw":  len(records) if args.get_url else len(records),
        "filter":        "game == 'DK : REBORN'" if args.get_url else "none",
        "total":         len(records),
        "records":       records,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 저장 완료 → {out_file.name} ({len(records)}건)")

    # 날짜별 미리보기
    from collections import Counter
    date_counts = Counter(r["received"] for r in records)
    print(f"\n[날짜별 건수]:")
    for d in sorted(date_counts):
        print(f"  {d}: {date_counts[d]}건")

    # 상태별 미리보기
    status_counts = Counter(r["status"] for r in records)
    print(f"\n[상태별 건수]:")
    for s, c in status_counts.most_common():
        print(f"  {s}: {c}건")

    # collect_cs_data.py 실행
    if not args.no_analyze:
        print(f"\n[INFO] collect_cs_data.py 실행 → {target_date}")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "collect_cs_data.py"),
             target_date, "--data", str(out_file)],
            capture_output=False,
        )
        if result.returncode == 0:
            print("[OK] collect_cs_data.py 완료")
        else:
            print(f"[WARN] collect_cs_data.py 실패")
    else:
        print(f"\n[INFO] --no-analyze → collect_cs_data.py 스킵")

    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
