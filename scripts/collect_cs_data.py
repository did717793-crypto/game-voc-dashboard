#!/usr/bin/env python3
"""
DKR CS 데이터 자동 수집 스크립트 v2.0
========================================
변경 (v1→v2):
  [NEW] cs_inquiries 카테고리별 집계 → analyzed.json 업데이트
  [NEW] BROWSER_JS: title, type, subtype 필드 추가 수집
  [NEW] classify_cs_category(): 규칙 기반 카테고리 분류 (Hive 유형 → 보고 카테고리)
  [NEW] build_cs_inquiries(): 당일 records → cs_inquiries 구조 생성

【아키텍처】
  1. collect_cs_browser.py (또는 Claude 브라우저) → Hive JS 실행 → cs_raw_YYYY-MM-DD.json
  2. collect_cs_data.py [날짜] → analyzed.json 업데이트 (cs_week_trend + cs_inquiries)
  3. generate_dashboard.py → CS 섹션 렌더링

【일별 사용법】
  Step 1: Claude에게 → "DKR CS 데이터 수집해줘"  (브라우저 Hive 접속 → raw 저장)
  Step 2: python3 collect_cs_data.py [YYYY-MM-DD]

【직접 실행】
  python3 collect_cs_data.py 2026-04-08 --data /tmp/cs_raw.json

처리 완료 기준:
  [접수완료], [처리중] → 미처리
  그 외 → 처리 완료
"""

import json
import sys
import subprocess
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
DATA_DIR    = SCRIPTS_DIR.parent / "data" / "DKR"
RAW_DIR     = SCRIPTS_DIR / "raw"
RAW_DIR.mkdir(exist_ok=True)

UNPROCESSED = {"접수 완료", "접수완료", "처리 중", "처리중"}

# ── CS 카테고리 정의 ──────────────────────────────────────────────────────────
CS_CATEGORIES = ["결제", "계정", "설치/실행", "오류", "건의", "게임 이용", "이벤트", "기타"]

# Hive 유형 텍스트 → 보고 카테고리 직접 매핑 (긴 것 먼저)
HIVE_TYPE_MAP: dict[str, str] = {
    "결제":       "결제", "과금":       "결제", "구매":       "결제",
    "환불":       "결제", "영수증":     "결제", "인앱":       "결제",
    "계정":       "계정", "로그인":     "계정", "비밀번호":   "계정",
    "아이디":     "계정", "탈퇴":       "계정", "이관":       "계정",
    "설치":       "설치/실행", "실행":   "설치/실행", "다운로드": "설치/실행",
    "업데이트":   "설치/실행", "앱":     "설치/실행", "구동":    "설치/실행",
    "오류":       "오류", "버그":       "오류", "에러":       "오류",
    "crash":      "오류", "충돌":       "오류", "먹통":       "오류",
    "건의":       "건의", "제안":       "건의", "요청":       "건의",
    "이벤트":     "이벤트", "쿠폰":     "이벤트", "보상":     "이벤트",
    "게임":       "게임 이용", "아이템": "게임 이용", "캐릭":   "게임 이용",
    "서버":       "게임 이용", "스킬":   "게임 이용", "이용":   "게임 이용",
}

# 제목 키워드 fallback 분류
TITLE_KEYWORDS: dict[str, list[str]] = {
    "결제":     ["결제", "과금", "구매", "환불", "영수증", "인앱결제"],
    "계정":     ["계정", "로그인", "비밀번호", "아이디", "탈퇴", "연동"],
    "설치/실행": ["설치", "실행", "다운로드", "업데이트", "앱", "구동"],
    "오류":     ["오류", "버그", "에러", "crash", "튕", "먹통", "끊"],
    "건의":     ["건의", "제안", "요청", "추가", "개선"],
    "이벤트":   ["이벤트", "쿠폰", "보상", "혜택"],
    "게임 이용": ["게임", "아이템", "캐릭", "스킬", "서버", "던전", "전투"],
}


# ── Claude가 브라우저에서 실행할 JS 스니펫 (v2: 카테고리/제목 추가) ───────────
BROWSER_JS = r"""
(function() {
  var rows = document.querySelectorAll('table tbody tr');
  var data = [];
  rows.forEach(function(row) {
    var cells = row.querySelectorAll('td');
    if (cells.length < 10) return;
    var title   = cells[1] ? cells[1].textContent.trim() : '';
    var type    = cells[3] ? cells[3].textContent.trim() : '';
    var subtype = cells[4] ? cells[4].textContent.trim() : '';
    var recv    = cells[7].textContent.trim().substring(0, 10);
    var comp    = cells[8].textContent.trim().substring(0, 10);
    var status  = cells[9].textContent.trim();
    if (recv && recv !== '-') {
      data.push({
        title:    title,
        type:     type,
        subtype:  subtype,
        received: recv,
        completed: comp !== '-' ? comp : null,
        status:   status
      });
    }
  });
  return JSON.stringify({
    collected_at: new Date().toISOString(),
    total:        data.length,
    records:      data
  });
})();
"""


# ── 카테고리 분류 ─────────────────────────────────────────────────────────────
def classify_cs_category(record: dict) -> str:
    """단일 CS record → 보고 카테고리 (규칙 기반, LLM 없음).

    우선순위:
      1. Hive type/subtype 직접 매핑
      2. title 키워드 매핑
      3. "기타" fallback
    """
    # 1. Hive 유형 직접 매핑
    for field in ("type", "subtype"):
        val = (record.get(field) or "").strip()
        if val:
            for kw, cat in HIVE_TYPE_MAP.items():
                if kw in val:
                    return cat

    # 2. 제목 키워드 fallback
    title = (record.get("title") or "").lower()
    if title:
        for cat, keywords in TITLE_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                return cat

    return "기타"


# ── cs_inquiries 생성 ─────────────────────────────────────────────────────────
def build_cs_inquiries(records: list, target_date: str) -> list[dict]:
    """당일 records → cs_inquiries (카테고리별 집계).

    반환 구조:
      [{"category": "결제", "count": 5, "pending": 2,
        "representative": [{"title":..., "status":..., "date":...}]}, ...]
    """
    day_records = [r for r in records if r.get("received") == target_date]
    if not day_records:
        return []

    cat_count:   defaultdict[str, int]        = defaultdict(int)
    cat_pending: defaultdict[str, int]        = defaultdict(int)
    cat_reps:    defaultdict[str, list]       = defaultdict(list)

    for r in day_records:
        cat = classify_cs_category(r)
        cat_count[cat]  += 1
        if r.get("status") in UNPROCESSED:
            cat_pending[cat] += 1
        if len(cat_reps[cat]) < 3:          # 대표 티켓 최대 3개
            cat_reps[cat].append({
                "title":  (r.get("title") or "")[:60],
                "body":   (r.get("body") or ""),    # 상세 본문 (재수집 시 채워짐)
                "status": r.get("status", ""),
                "date":   r.get("received", ""),
            })

    result = []
    for cat in CS_CATEGORIES:
        cnt = cat_count.get(cat, 0)
        if cnt == 0:
            continue
        result.append({
            "category":       cat,
            "count":          cnt,
            "pending":        cat_pending.get(cat, 0),
            "representative": cat_reps.get(cat, []),
        })

    return result


# ── 집계 ─────────────────────────────────────────────────────────────────────
def aggregate(records: list, target_dates: list) -> dict:
    """날짜별 인입량(received) / 처리량(processed) 집계"""
    received  = {d: 0 for d in target_dates}
    processed = {d: 0 for d in target_dates}
    for r in records:
        if r.get("received") in received:
            received[r["received"]] += 1
        if (r.get("status") not in UNPROCESSED
                and r.get("completed")
                and r["completed"] in processed):
            processed[r["completed"]] += 1
    return {"received": received, "processed": processed}


# ── analyzed.json 업데이트 ────────────────────────────────────────────────────
def update_analyzed(target_date: str, records: list) -> bool:
    # report_date = target_date - 1일 (전일 기준 리포트)
    report_date = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    json_path = DATA_DIR / f"{report_date}.analyzed.json"
    if not json_path.exists():
        print(f"[ERROR] {json_path} 없음 (target_date={target_date}, report_date={report_date})")
        return False

    print(f"[INFO] target_date={target_date} → report_date={report_date}")

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # ── cs_week_trend 업데이트 ──
    trend = data.get("cs_week_trend", [])
    if not trend:
        print("[WARN] cs_week_trend 없음 → 스킵")
        return False

    target_dates = [t["date"] for t in trend]
    counts = aggregate(records, target_dates)

    for entry in trend:
        d = entry["date"]
        entry["received"]  = counts["received"].get(d, 0)
        entry["processed"] = counts["processed"].get(d, 0)
        entry.pop("dkr", None)

    data["cs_week_trend"] = trend

    # ── cs_daily (report_date 기준 인입/처리) ──
    report_recv = sum(1 for r in records if r.get("received") == report_date)
    report_proc = sum(
        1 for r in records
        if r.get("status") not in UNPROCESSED
        and r.get("completed") == report_date
    )
    data["cs_daily"] = {"received": report_recv, "processed": report_proc}

    # ── cs_status_counts (전체 수집 건 기준 상태별 집계) ──
    status_counts: defaultdict[str, int] = defaultdict(int)
    for r in records:
        status_counts[r.get("status", "")] += 1
    data["cs_status_counts"] = dict(status_counts)

    # ── cs_inquiries (report_date 기준 필터링, 카테고리별 집계) ──
    cs_inqs = build_cs_inquiries(records, report_date)
    data["cs_inquiries"] = cs_inqs

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 출력 요약 ──
    print(f"[OK] {json_path.name} 업데이트 완료")
    print(f"\n  cs_daily (report_date={report_date}):")
    print(f"    인입={report_recv}건, 처리={report_proc}건")
    print(f"\n  cs_status_counts:")
    for st, cnt in sorted(data["cs_status_counts"].items()):
        print(f"    {st}: {cnt}건")
    print(f"\n  cs_week_trend:")
    print(f"  {'날짜':^12} {'인입':>4} {'처리':>4} {'처리율':>6}")
    print("  " + "-" * 32)
    for t in trend:
        r    = t.get("received", 0)
        p    = t.get("processed", 0)
        rate = round(p / r * 100) if r > 0 else 0
        print(f"  {t['date']}  {r:3d}건  {p:3d}건  {rate:3d}%")

    print(f"\n  cs_inquiries ({len(cs_inqs)}개 카테고리):")
    for inq in cs_inqs:
        print(f"    [{inq['category']}] {inq['count']}건  (미처리 {inq['pending']}건)")

    return True


# ── 대시보드 재생성 ───────────────────────────────────────────────────────────
def regenerate_dashboard():
    gen_script = SCRIPTS_DIR / "generate_dashboard.py"
    if not gen_script.exists():
        print("[WARN] generate_dashboard.py 없음 → 스킵")
        return
    result = subprocess.run([sys.executable, str(gen_script)],
                            capture_output=True, text=True)
    if result.returncode == 0:
        print("[OK] 대시보드 재생성 완료")
    else:
        print(f"[ERROR] 대시보드 생성 실패:\n{result.stderr}")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DKR CS 데이터 수집 처리")
    parser.add_argument("date", nargs="?",
                        default=datetime.today().strftime("%Y-%m-%d"),
                        help="대상 analyzed.json 날짜 (기본: 오늘)")
    parser.add_argument("--data", "-d", type=Path, default=None,
                        help="브라우저 JS로 추출한 raw JSON 파일 경로")
    parser.add_argument("--js", action="store_true",
                        help="브라우저에서 실행할 JS 스니펫 출력")
    args = parser.parse_args()

    if args.js:
        print("=" * 60)
        print("아래 JS를 inquiry.withhive.com 탭에서 실행 후 결과를 저장하세요:")
        print("=" * 60)
        print(BROWSER_JS)
        return

    print(f"\n{'='*50}")
    print(f" DKR CS 처리  대상: {args.date}")
    print(f"{'='*50}")

    # 데이터 파일 결정
    data_file = args.data
    if data_file is None:
        # 기본 위치 탐색 (가장 최근 raw 파일)
        raw_files = sorted(RAW_DIR.glob("cs_raw_*.json"), reverse=True)
        if raw_files:
            data_file = raw_files[0]
            print(f"[INFO] 최근 raw 파일 사용: {data_file.name}")
        else:
            print("""[ERROR] 데이터 파일 없음.

다음 순서로 진행하세요:
  1. Claude에게: "DKR CS 데이터 브라우저에서 수집해서 raw 파일로 저장해줘"
  2. python3 collect_cs_data.py""")
            sys.exit(1)

    with open(data_file, encoding="utf-8") as f:
        raw = json.load(f)

    records = raw.get("records", raw) if isinstance(raw, dict) else raw
    print(f"[INFO] {len(records)}건 로드 ({data_file.name})")

    ok = update_analyzed(args.date, records)
    if ok:
        regenerate_dashboard()
        print("\n[DONE] 완료!")
    else:
        print("\n[FAIL]")
        sys.exit(1)


if __name__ == "__main__":
    main()
