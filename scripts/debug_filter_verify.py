#!/usr/bin/env python3
"""
debug_filter_verify.py — HIVEframe 필터 상태 완전 검증 스크립트
=================================================================
목적:
  1. console 로그인 → 문의 목록 iframe 진입
  2. 상태 체크박스 DOM 실제 확인
  3. "전체" 버튼 2회 클릭으로 초기화
  4. 게임=DKR, 기간=1개월, 건수=200으로 설정 후 검색
  5. 검색 건수 / 체크박스 상태 / 첫 5개 row 출력
"""

import json
import re
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
DKR_GAME_ID   = "2474"
CONSOLE_MAIN  = "https://console.withhive.com/main/"
PLATFORM_LOGIN = "https://platform.withhive.com/auth/login"
RAW_DIR.mkdir(exist_ok=True)


def load_credentials():
    import os
    hive_id = os.environ.get("HIVE_ID", "")
    hive_pw = os.environ.get("HIVE_PW", "")
    if hive_id and hive_pw:
        return hive_id, hive_pw
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("hive_id", ""), cfg.get("hive_pw", "")
    print("[ERROR] 자격증명 없음")
    sys.exit(1)


def save_cookies(ctx):
    COOKIE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False, indent=2), encoding="utf-8")


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


def do_login(page, ctx, hive_id, hive_pw):
    print(f"[로그인] → {PLATFORM_LOGIN}")
    page.goto(PLATFORM_LOGIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.fill("#userId", hive_id, timeout=5_000)
    page.fill("#passWd", hive_pw, timeout=5_000)
    page.click("button:text('로그인')", timeout=5_000)
    time.sleep(3)
    # 동시접속 팝업
    for sel in ["button:text('확인')", ".modal button:text('확인')", "button.btn-primary:text('확인')"]:
        try:
            page.click(sel, timeout=2_000)
            print(f"  [팝업] 확인 클릭 ({sel})")
            time.sleep(1)
            break
        except:
            pass
    page.wait_for_load_state("networkidle", timeout=30_000)
    time.sleep(3)
    ok = "platform.withhive.com" not in page.url
    if ok:
        save_cookies(ctx)
        print(f"[OK] 로그인 성공 → {page.url}")
    else:
        print(f"[ERROR] 로그인 실패: {page.url}")
    return ok


def get_hive_frame(page, ctx, hive_id, hive_pw):
    """console → '문의 목록' 클릭 → HIVEframe"""
    page.goto(CONSOLE_MAIN, timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    time.sleep(2)

    if "platform.withhive.com" in page.url:
        print("[INFO] 세션 만료 → 재로그인")
        if not do_login(page, ctx, hive_id, hive_pw):
            return None
        page.goto(CONSOLE_MAIN, timeout=20_000)
        page.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(2)

    print(f"[console] {page.url}")

    # 메뉴 클릭 시도 (여러 방법)
    clicked = False

    # 방법 1: 직접 텍스트 매칭
    try:
        page.click("a:text('문의 목록')", timeout=5_000)
        print("[클릭] '문의 목록' (직접)")
        clicked = True
    except:
        pass

    # 방법 2: 부분 텍스트 매칭
    if not clicked:
        try:
            page.click("a:text-is('문의 목록')", timeout=5_000)
            print("[클릭] '문의 목록' (exact)")
            clicked = True
        except:
            pass

    # 방법 3: 메뉴 계층 클릭
    if not clicked:
        try:
            # 고객센터 > 문의 > 문의 목록 순서로
            page.click("text=고객센터", timeout=3_000)
            time.sleep(1)
            page.click("text=문의", timeout=3_000)
            time.sleep(1)
            page.click("text=문의 목록", timeout=3_000)
            print("[클릭] 고객센터 > 문의 > 문의 목록 (계층)")
            clicked = True
        except:
            pass

    if not clicked:
        # 현재 페이지의 모든 링크 출력 (디버깅용)
        links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.textContent.trim()).filter(t => t.length > 0 && t.length < 30)")
        print(f"[DEBUG] 현재 페이지 링크들: {links[:30]}")
        return None

    # HIVEframe 로드 대기 (최대 25초)
    for i in range(25):
        time.sleep(1)
        for f in page.frames:
            if "inquiry.withhive.com" in f.url and "/inquiry" in f.url:
                try:
                    f.wait_for_load_state("networkidle", timeout=10_000)
                    time.sleep(2)
                    print(f"[HIVEframe] {f.url}")
                    return f
                except Exception as e:
                    print(f"  [WARN] frame 로드 대기 중 ({i+1}s): {e}")
        if i % 5 == 4:
            print(f"  [대기중] {i+1}초... frame 목록: {[f.url for f in page.frames]}")

    print("[ERROR] HIVEframe 진입 실패")
    return None


def check_and_fix_status_filter(hf):
    """
    상태 필터 DOM 완전 검증:
    1. 현재 체크박스 상태 확인
    2. "전체" 버튼 2회 클릭 (초기화)
    3. 재확인
    """
    print("\n" + "="*50)
    print("[상태 필터 검증]")
    print("="*50)

    # 현재 상태 체크박스 전체 조회
    def get_checkbox_states():
        return hf.evaluate("""
            () => {
                var result = [];
                // 상태 체크박스 탐색 (다양한 방법)
                var checkboxes = document.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(function(cb) {
                    var label = '';
                    // label 태그 or 인접 텍스트
                    if (cb.id) {
                        var lbl = document.querySelector('label[for="' + cb.id + '"]');
                        if (lbl) label = lbl.textContent.trim();
                    }
                    if (!label && cb.nextSibling) {
                        label = cb.parentElement?.textContent.trim() || '';
                    }
                    result.push({
                        id: cb.id || '',
                        name: cb.name || '',
                        value: cb.value || '',
                        checked: cb.checked,
                        label: label.substring(0, 30)
                    });
                });
                return result;
            }
        """)

    def get_all_status_info():
        return hf.evaluate("""
            () => {
                var info = {};

                // 방법 1: 상태 관련 버튼/링크
                info.statusButtons = Array.from(document.querySelectorAll(
                    'a[onclick*="status"], button[onclick*="status"], .status-btn, [class*="status"] a, [class*="status"] button'
                )).map(el => ({text: el.textContent.trim(), class: el.className}));

                // 방법 2: 전체 버튼
                info.allBtn = Array.from(document.querySelectorAll('a, button')).filter(
                    el => el.textContent.trim() === '전체'
                ).map(el => ({text: el.textContent.trim(), tag: el.tagName, class: el.className, onclick: el.getAttribute('onclick')}));

                // 방법 3: 체크박스 목록
                info.checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).map(cb => {
                    var lbl = cb.id ? document.querySelector('label[for="' + cb.id + '"]') : null;
                    return {
                        id: cb.id,
                        value: cb.value,
                        checked: cb.checked,
                        name: cb.name,
                        label: lbl ? lbl.textContent.trim() : (cb.parentElement?.textContent.trim().substring(0, 20) || '')
                    };
                });

                // 방법 4: 검색 건수 텍스트
                info.countText = document.body.innerText.match(/검색\s*건수\s*:?\s*[\d,]+/)?.[0] || '미확인';

                // 방법 5: select 상태
                info.gameSelect = {
                    value: document.querySelector('select#search_game')?.value || '',
                    options: Array.from(document.querySelectorAll('select#search_game option')).map(o => ({val: o.value, txt: o.text}))
                };

                // 방법 6: 날짜 입력값
                info.dateRange = {
                    start: document.querySelector('#start_date, input[name="start_date"]')?.value || '',
                    end: document.querySelector('#end_date, input[name="end_date"]')?.value || ''
                };

                return info;
            }
        """)

    # 현재 상태 진단
    print("\n[1단계] 현재 필터 상태 진단")
    status_info = get_all_status_info()

    print(f"  게임 선택: {status_info['gameSelect']['value']}")
    print(f"  게임 옵션: {status_info['gameSelect']['options']}")
    print(f"  날짜 범위: {status_info['dateRange']['start']} ~ {status_info['dateRange']['end']}")
    print(f"  검색 건수: {status_info['countText']}")
    print(f"  '전체' 버튼 목록: {status_info['allBtn']}")
    print(f"  상태 버튼 목록: {status_info['statusButtons'][:5]}")
    print(f"\n  체크박스 목록:")
    for cb in status_info['checkboxes']:
        print(f"    [{cb['checked']}] id={cb['id']} value={cb['value']} label={cb['label']}")

    # "전체" 버튼 2회 클릭 (초기화)
    print("\n[2단계] '전체' 버튼 2회 클릭 (상태 초기화)")
    for attempt in range(2):
        try:
            # 상태 관련 "전체" 버튼 클릭
            all_btns = hf.evaluate("""
                () => {
                    var btns = Array.from(document.querySelectorAll('a, button, span, label')).filter(
                        el => el.textContent.trim() === '전체'
                    );
                    return btns.map(b => ({
                        idx: btns.indexOf(b),
                        tag: b.tagName,
                        text: b.textContent.trim(),
                        class: b.className,
                        onclick: b.getAttribute('onclick') || ''
                    }));
                }
            """)
            print(f"  '전체' 요소 목록: {all_btns}")

            # 상태 섹션의 "전체" 버튼 클릭 시도
            clicked_all = False
            for btn in all_btns:
                # 상태 관련 버튼인지 확인 (onclick에 status 포함 또는 위치 기반)
                if 'status' in btn.get('onclick', '').lower() or 'state' in btn.get('class', '').lower():
                    # 해당 인덱스 버튼 클릭
                    hf.evaluate(f"""
                        () => {{
                            var btns = Array.from(document.querySelectorAll('a, button, span, label')).filter(
                                el => el.textContent.trim() === '전체'
                            );
                            if (btns[{btn['idx']}]) btns[{btn['idx']}].click();
                        }}
                    """)
                    print(f"  클릭 #{attempt+1}: '전체' ({btn['class']})")
                    clicked_all = True
                    time.sleep(1)
                    break

            if not clicked_all:
                # onclick 없는 경우 모든 "전체" 버튼 중 첫 번째 or 가장 관련있는 것
                try:
                    # "상태:" 레이블 근처의 "전체" 버튼 찾기
                    hf.evaluate("""
                        () => {
                            // 상태 영역의 전체 버튼 클릭
                            var btns = Array.from(document.querySelectorAll('a, button')).filter(
                                el => el.textContent.trim() === '전체'
                            );
                            // 두 번째 이후의 "전체" 버튼 (첫 번째는 게임 전체일 수 있음)
                            if (btns.length > 1) btns[1].click();
                            else if (btns.length === 1) btns[0].click();
                        }
                    """)
                    print(f"  클릭 #{attempt+1}: '전체' (위치 기반)")
                    time.sleep(1)
                except Exception as e:
                    print(f"  [WARN] '전체' 클릭 실패: {e}")

        except Exception as e:
            print(f"  [ERROR] 전체 버튼 처리 실패: {e}")

    time.sleep(1)

    # 클릭 후 체크박스 재확인
    print("\n[3단계] 전체 클릭 후 체크박스 상태 재확인")
    cb_states = get_checkbox_states()
    print(f"  체크박스 수: {len(cb_states)}")
    for cb in cb_states:
        print(f"    [{cb['checked']}] id={cb['id']} value={cb['value']} label={cb['label']}")

    return True


def run_search_and_verify(hf):
    """
    필터 설정 후 검색 실행 + 결과 검증
    """
    print("\n" + "="*50)
    print("[검색 필터 설정 및 검증]")
    print("="*50)

    # 1. 한국어 탭 클릭
    try:
        hf.click("a:text('한국어')", timeout=5_000)
        hf.wait_for_load_state("networkidle", timeout=15_000)
        time.sleep(3)
        print("[탭] 한국어 클릭")
    except Exception as e:
        print(f"[WARN] 한국어 탭: {e}")

    # 게임 선택 옵션 확인
    game_opts = hf.evaluate("""
        () => Array.from(document.querySelectorAll('select#search_game option')).map(o => ({val: o.value, txt: o.textContent.trim()}))
    """)
    print(f"[게임 옵션] {game_opts}")

    # 2. DK:REBORN 선택
    try:
        hf.select_option("select#search_game", value=DKR_GAME_ID, timeout=5_000)
        selected = hf.evaluate("() => document.querySelector('select#search_game')?.value")
        print(f"[게임] 선택값: {selected} (기대: {DKR_GAME_ID})")
    except Exception as e:
        print(f"[ERROR] 게임 선택 실패: {e}")
        return

    # 3. 상태 필터 "전체" 클릭 처리 (세밀하게)
    print("\n[상태 필터] 전체 버튼 탐색 및 클릭")

    # 현재 페이지 HTML 구조 파악
    status_section_html = hf.evaluate("""
        () => {
            // "상태" 텍스트 근처의 HTML 반환
            var allText = document.body.innerHTML;
            var idx = allText.indexOf('상태');
            if (idx > 0) return allText.substring(Math.max(0, idx-100), idx+500);
            return '상태 섹션 없음';
        }
    """)
    print(f"  상태 섹션 HTML (일부): {status_section_html[:300]}")

    # "전체" 버튼 목록 상세 조회
    all_btn_details = hf.evaluate("""
        () => {
            var result = [];
            var all = Array.from(document.querySelectorAll('*')).filter(el => {
                var txt = (el.innerText || el.textContent || '').trim();
                return txt === '전체' && el.children.length === 0;
            });
            all.forEach(function(el, i) {
                var rect = el.getBoundingClientRect();
                result.push({
                    idx: i,
                    tag: el.tagName,
                    class: el.className,
                    onclick: el.getAttribute('onclick') || '',
                    href: el.getAttribute('href') || '',
                    visible: rect.width > 0 && rect.height > 0,
                    top: Math.round(rect.top),
                    left: Math.round(rect.left)
                });
            });
            return result;
        }
    """)
    print(f"\n  '전체' 요소 전체 목록:")
    for btn in all_btn_details:
        print(f"    [{btn['idx']}] {btn['tag']} class={btn['class']} onclick={btn['onclick']} visible={btn['visible']} pos=({btn['left']},{btn['top']})")

    # 상태 관련 "전체" 버튼 2회 클릭
    # 보통 상태 섹션의 "전체"는 게임 선택 "전체"보다 아래 위치
    for click_no in range(1, 3):
        print(f"\n  [전체 클릭 {click_no}/2]")
        clicked = False

        # onclick에 상태/state 관련 키워드가 있는 버튼 우선
        for btn in all_btn_details:
            onclick = btn.get('onclick', '')
            if any(kw in onclick.lower() for kw in ['status', 'state', 'st_', '_st']):
                try:
                    hf.evaluate(f"""
                        () => {{
                            var all = Array.from(document.querySelectorAll('*')).filter(el => {{
                                var txt = (el.innerText || el.textContent || '').trim();
                                return txt === '전체' && el.children.length === 0;
                            }});
                            if (all[{btn['idx']}]) all[{btn['idx']}].click();
                        }}
                    """)
                    print(f"    onclick 기반 클릭: {onclick}")
                    clicked = True
                    time.sleep(1)
                    break
                except:
                    pass

        if not clicked:
            # 위치 기반: 페이지 아래쪽(top > 300)의 "전체" 버튼
            visible_btns = [b for b in all_btn_details if b['visible'] and b['top'] > 200]
            if visible_btns:
                btn = visible_btns[0]
                try:
                    hf.evaluate(f"""
                        () => {{
                            var all = Array.from(document.querySelectorAll('*')).filter(el => {{
                                var txt = (el.innerText || el.textContent || '').trim();
                                return txt === '전체' && el.children.length === 0;
                            }});
                            if (all[{btn['idx']}]) all[{btn['idx']}].click();
                        }}
                    """)
                    print(f"    위치 기반 클릭: top={btn['top']} left={btn['left']}")
                    clicked = True
                    time.sleep(1)
                except Exception as e:
                    print(f"    위치 기반 클릭 실패: {e}")

        if not clicked:
            print("    [WARN] 전체 버튼 클릭 불가")

    # 클릭 후 체크박스 상태 확인
    time.sleep(1)
    cb_after = hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
                var lbl = cb.id ? document.querySelector('label[for="' + cb.id + '"]') : null;
                result.push({
                    id: cb.id || '',
                    value: cb.value || '',
                    checked: cb.checked,
                    label: lbl ? lbl.textContent.trim() : (cb.parentElement?.textContent.trim().substring(0, 20) || '')
                });
            });
            return result;
        }
    """)
    print(f"\n[전체 클릭 후 체크박스 상태]:")
    for cb in cb_after:
        status_mark = "✓" if cb['checked'] else "✗"
        print(f"  [{status_mark}] id={cb['id']} value={cb['value']} label={cb['label']}")

    all_checked = all(cb['checked'] for cb in cb_after) if cb_after else False
    print(f"\n  → 모든 체크박스 체크됨: {all_checked}")

    # 4. 기간 = 1개월
    try:
        hf.click("a:text('1개월')", timeout=3_000)
        time.sleep(1)
        date_range = hf.evaluate("""
            () => ({
                start: document.querySelector('#start_date, input[name="start_date"]')?.value || '',
                end:   document.querySelector('#end_date, input[name="end_date"]')?.value || ''
            })
        """)
        print(f"\n[기간] 1개월 → {date_range['start']} ~ {date_range['end']}")
    except Exception as e:
        print(f"[WARN] 기간 버튼: {e}")

    # 5. 200개씩
    try:
        hf.select_option("select[name='spc']", value="200", timeout=3_000)
        print("[페이지크기] 200개")
    except:
        pass

    # 6. 검색 실행
    print("\n[검색 실행]")
    hf.click("button#btn_submit", timeout=5_000)
    hf.wait_for_load_state("networkidle", timeout=20_000)
    time.sleep(4)

    # 7. 결과 검증
    print("\n" + "="*50)
    print("[검색 결과 검증]")
    print("="*50)

    body_text = hf.inner_text("body")
    count_match = re.search(r'검색\s*건수\s*:?\s*([\d,]+)', body_text)
    total_count = int(count_match.group(1).replace(',', '')) if count_match else 0
    print(f"검색 건수: {total_count}건")

    # 체크박스 최종 상태
    cb_final = hf.evaluate("""
        () => {
            var result = [];
            document.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
                var lbl = cb.id ? document.querySelector('label[for="' + cb.id + '"]') : null;
                result.push({
                    id: cb.id || '',
                    value: cb.value || '',
                    checked: cb.checked,
                    label: lbl ? lbl.textContent.trim() : (cb.parentElement?.textContent.trim().substring(0, 20) || '')
                });
            });
            return result;
        }
    """)
    print("\n[체크박스 최종 상태]:")
    for cb in cb_final:
        mark = "✓" if cb['checked'] else "✗"
        print(f"  [{mark}] {cb['label'] or cb['value'] or cb['id']}")

    # 테이블 row 수
    row_data = hf.evaluate("""
        () => {
            var rows = document.querySelectorAll('table tbody tr');
            var result = [];
            rows.forEach(function(row) {
                var cells = row.querySelectorAll('td');
                var txts = Array.from(cells).map(c => c.innerText.trim());
                var hasDate = txts.some(t => /\\d{4}-\\d{2}-\\d{2}/.test(t));
                if (hasDate && txts.length >= 8) {
                    result.push(txts);
                }
            });
            return result;
        }
    """)
    print(f"\n테이블 실제 데이터 행 수: {len(row_data)}개")

    # 첫 5개 row 출력
    print("\n[첫 5개 row 상세]:")
    for i, row in enumerate(row_data[:5]):
        print(f"\n  Row {i+1}:")
        print(f"    [1] 번호    : {row[1] if len(row) > 1 else '-'}")
        print(f"    [4] 분류    : {row[4] if len(row) > 4 else '-'}")
        print(f"    [5] 제목    : {row[5] if len(row) > 5 else '-'}")
        print(f"    [7] 접수일  : {row[7] if len(row) > 7 else '-'}")
        print(f"    [8] 완료일  : {row[8] if len(row) > 8 else '-'}")
        print(f"    [9] 상태    : {row[9] if len(row) > 9 else '-'}")

    print(f"\n{'='*50}")
    if total_count <= 1:
        print("[판단] ❌ 건수 1건 이하 — 필터 문제 의심")
        print("  원인 분석:")
        print("  1. 상태 체크박스가 일부만 선택됨")
        print("  2. 기간 설정 오류")
        print("  3. 게임 선택 유지 안됨")
    else:
        print(f"[판단] ✅ 건수 {total_count}건 — 정상 수집 가능")
    print("="*50)

    return total_count, row_data


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

        # 1. HIVEframe 진입
        hf = get_hive_frame(page, ctx, hive_id, hive_pw)
        if not hf:
            print("[ERROR] HIVEframe 진입 실패")
            browser.close()
            sys.exit(1)

        # 2. 상태 필터 완전 검증 + 초기화
        check_and_fix_status_filter(hf)

        # 3. 검색 실행 + 결과 검증
        result = run_search_and_verify(hf)

        browser.close()

    print("\n[완료]")


if __name__ == "__main__":
    main()
