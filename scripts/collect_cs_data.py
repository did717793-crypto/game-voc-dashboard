#!/usr/bin/env python3
"""
DKR CS 데이터 자동 수집 스크립트
==================================
【아키텍처】
  1. Claude가 브라우저에서 JS 실행 → 문의 데이터 JSON 추출
  2. 이 스크립트가 JSON 처리 → analyzed.json 업데이트 → 대시보드 재생성

【일별 사용법】
  Step 1: Claude에게 요청 → "DKR CS 데이터 수집해줘" (Claude가 브라우저 JS 실행)
  Step 2: python3 collect_cs_data.py [YYYY-MM-DD]

【직접 실행 (데이터 파일 지정)】
  python3 collect_cs_data.py 2026-04-07 --data /tmp/cs_raw.json

처리 완료 기준:
  [접수완료], [처리중] → 미처리 (인입량에만 포함)
  그 외 전체 → 처리 완료 (처리량 집계)
"""

import json
import sys
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
DATA_DIR    = SCRIPTS_DIR.parent / "data" / "DKR"
RAW_DIR     = SCRIPTS_DIR / "raw"          # 브라우저에서 추출한 raw JSON 임시 저장
RAW_DIR.mkdir(exist_ok=True)

UNPROCESSED = {"접수 완료", "접수완료", "처리 중", "처리중"}

# ── Claude가 브라우저에서 실행할 JS 스니펫 ────────────────────────────────────
BROWSER_JS = r"""
(function() {
  var rows = document.querySelectorAll('table tbody tr');
  var data = [];
  rows.forEach(function(row) {
    var cells = row.querySelectorAll('td');
    if (cells.length < 10) return;
    var recv = cells[7].textContent.trim().substring(0, 10);
    var comp = cells[8].textContent.trim().substring(0, 10);
    var status = cells[9].textContent.trim();
    if (recv && recv !== '-') {
      data.push({received: recv, completed: comp !== '-' ? comp : null, status: status});
    }
  });
  return JSON.stringify({collected_at: new Date().toISOString(), total: data.length, records: data});
})();
"""

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
    json_path = DATA_DIR / f"{target_date}.analyzed.json"
    if not json_path.exists():
        print(f"[ERROR] {json_path} 없음")
        return False

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

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
        entry.pop("dkr", None)  # 구 필드 제거

    data["cs_week_trend"] = trend
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[OK] {json_path.name} cs_week_trend 업데이트 완료")
    print(f"{'날짜':^12} {'인입':>4} {'처리':>4} {'처리율':>6}")
    print("-" * 32)
    for t in trend:
        r    = t.get("received", 0)
        p    = t.get("processed", 0)
        rate = round(p / r * 100) if r > 0 else 0
        print(f"  {t['date']}  {r:3d}건  {p:3d}건  {rate:3d}%")
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
