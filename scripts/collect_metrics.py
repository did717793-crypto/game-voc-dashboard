#!/usr/bin/env python3
"""
DKR 지표 데이터 수집 저장 스크립트 (반자동화)

[사용 흐름]
1. Claude가 ntrance-bigquery MCP로 각 쿼리 실행
2. 결과를 딕셔너리 형태로 이 스크립트에 전달
3. collect_and_save() 호출 → data/metrics/YYYY-MM-DD.json 저장
4. generate_dashboard.py 실행 → push

[JSON 스키마]  data/metrics/YYYY-MM-DD.json
{
  "date": "2026-04-07",
  "is_week_start": false,   // 목요일이면 True
  "is_month_start": false,  // 1일이면 True
  "old":   { rev_total, rev_pure, platform:{}, dau, nu, pu, npu, pur, arpu, arppu },
  "hyper": { ... },
  "global": null,           // 미오픈
  "week":  null | {         // 목요일에만 저장
    week_start, week_end,
    old: {wau, wnu, wpu, wnpu, wpur, rev_total, rev_pure, warpu, warppu},
    hyper: {...}, global: null
  },
  "month": null | {         // 1일에만 저장
    month,
    old: {mau, mnu, mpu, mnpu, mpur, rev_total, rev_pure, marpu, marppu},
    hyper: {...}, global: null
  },
  "pkg_old":   [ {name, qty}, ... ],   // TOP20
  "pkg_hyper": [ {name, qty}, ... ],
  "pkg_global": null
}
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

GIT_DIR     = Path(__file__).parent.parent
METRICS_DIR = GIT_DIR / "data" / "metrics"
KST_OFFSET  = timedelta(hours=9)


# ─────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────

def is_thursday(d_str: str) -> bool:
    return datetime.strptime(d_str, "%Y-%m-%d").weekday() == 3  # 목=3

def is_first_of_month(d_str: str) -> bool:
    return d_str.endswith("-01")

def get_week_range(d_str: str) -> tuple[str, str]:
    """목~수 기준 주 범위 반환"""
    d = datetime.strptime(d_str, "%Y-%m-%d")
    days_since_thu = (d.weekday() - 3) % 7
    ws = d - timedelta(days=days_since_thu)
    we = ws + timedelta(days=6)
    return ws.strftime("%Y-%m-%d"), we.strftime("%Y-%m-%d")

def yesterday_kst() -> str:
    return (datetime.utcnow() + KST_OFFSET - timedelta(days=1)).strftime("%Y-%m-%d")

def existing_metric_dates() -> set[str]:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    return {f.stem for f in METRICS_DIR.glob("*.json")}

def missing_dates(from_date: str = "2026-04-18") -> list[str]:
    """from_date부터 어제까지 metrics JSON이 없는 날짜 목록"""
    existing = existing_metric_dates()
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end   = datetime.strptime(yesterday_kst(), "%Y-%m-%d")
    result = []
    cur = start
    while cur <= end:
        ds = cur.strftime("%Y-%m-%d")
        if ds not in existing:
            result.append(ds)
        cur += timedelta(days=1)
    return result

def load_metrics(d: str) -> Optional[dict]:
    p = METRICS_DIR / f"{d}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ─────────────────────────────────────────────────────────────────
# 결과 처리
# ─────────────────────────────────────────────────────────────────

def _build_server_daily(rev_total: int, rev_pure: int,
                         platform: dict,
                         dau: int, nu: int, pu: int, npu: int) -> dict:
    pur   = round(pu / dau, 4)   if dau > 0 else 0.0
    arpu  = int(rev_total / dau) if dau > 0 else 0
    arppu = int(rev_total / pu)  if pu  > 0 else 0
    return dict(
        rev_total=rev_total, rev_pure=rev_pure,
        platform=platform,
        dau=dau, nu=nu, pu=pu, npu=npu,
        pur=pur, arpu=arpu, arppu=arppu
    )

def _build_server_weekly(wau: int, wnu: int, wpu: int, wnpu: int,
                          week_rev_total: int, week_rev_pure: int) -> dict:
    wpur   = round(wpu / wau, 4)       if wau > 0 else 0.0
    warpu  = int(week_rev_total / wau) if wau > 0 else 0
    warppu = int(week_rev_total / wpu) if wpu > 0 else 0
    return dict(
        wau=wau, wnu=wnu, wpu=wpu, wnpu=wnpu, wpur=wpur,
        rev_total=week_rev_total, rev_pure=week_rev_pure,
        warpu=warpu, warppu=warppu
    )

def _build_server_monthly(mau: int, mnu: int, mpu: int, mnpu: int,
                           month_rev_total: int, month_rev_pure: int) -> dict:
    mpur   = round(mpu / mau, 4)        if mau > 0 else 0.0
    marpu  = int(month_rev_total / mau) if mau > 0 else 0
    marppu = int(month_rev_total / mpu) if mpu > 0 else 0
    return dict(
        mau=mau, mnu=mnu, mpu=mpu, mnpu=mnpu, mpur=mpur,
        rev_total=month_rev_total, rev_pure=month_rev_pure,
        marpu=marpu, marppu=marppu
    )


# ─────────────────────────────────────────────────────────────────
# 메인 저장 함수
# ─────────────────────────────────────────────────────────────────

def collect_and_save(
    date_str: str,

    # 일별 매출 (당일)
    rev_total_old: int,   rev_total_hyper: int,
    rev_pure_old: int,    rev_pure_hyper: int,

    # 플랫폼 비중 (당일)
    platform_old: dict,   platform_hyper: dict,

    # 일별 유저 지표 (당일)
    dau_old: int, nu_old: int, pu_old: int, npu_old: int,
    dau_hyper: int, nu_hyper: int, pu_hyper: int, npu_hyper: int,

    # 패키지 (당일 TOP)
    packages_old: list,   packages_hyper: list,

    # 주간 지표 (목요일에만, 나머지는 None)
    week_rev_total_old: int = None,  week_rev_pure_old: int = None,
    week_rev_total_hyper: int = None, week_rev_pure_hyper: int = None,
    wau_old: int = None, wnu_old: int = None, wpu_old: int = None, wnpu_old: int = None,
    wau_hyper: int = None, wnu_hyper: int = None, wpu_hyper: int = None, wnpu_hyper: int = None,

    # 월간 지표 (1일에만, 나머지는 None)
    month_rev_total_old: int = None,  month_rev_pure_old: int = None,
    month_rev_total_hyper: int = None, month_rev_pure_hyper: int = None,
    mau_old: int = None, mnu_old: int = None, mpu_old: int = None, mnpu_old: int = None,
    mau_hyper: int = None, mnu_hyper: int = None, mpu_hyper: int = None, mnpu_hyper: int = None,
) -> dict:
    """
    하루치 지표를 받아 JSON 파일로 저장하고 저장된 딕셔너리를 반환
    """
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    is_thu = is_thursday(date_str)
    is_1st = is_first_of_month(date_str)
    ws, we = get_week_range(date_str)

    doc: dict = {
        "date": date_str,
        "is_week_start": is_thu,
        "is_month_start": is_1st,

        "old": _build_server_daily(
            rev_total_old, rev_pure_old, platform_old,
            dau_old, nu_old, pu_old, npu_old
        ),
        "hyper": _build_server_daily(
            rev_total_hyper, rev_pure_hyper, platform_hyper,
            dau_hyper, nu_hyper, pu_hyper, npu_hyper
        ),
        "global": None,  # 미오픈

        # 주간 데이터 (목요일에만)
        "week": {
            "week_start": ws,
            "week_end":   we,
            "old":   _build_server_weekly(
                wau_old or 0, wnu_old or 0, wpu_old or 0, wnpu_old or 0,
                week_rev_total_old or 0, week_rev_pure_old or 0
            ),
            "hyper": _build_server_weekly(
                wau_hyper or 0, wnu_hyper or 0, wpu_hyper or 0, wnpu_hyper or 0,
                week_rev_total_hyper or 0, week_rev_pure_hyper or 0
            ),
            "global": None,
        } if is_thu and wau_old is not None else None,

        # 월간 데이터 (1일에만)
        "month": {
            "month": date_str[:7],
            "old":   _build_server_monthly(
                mau_old or 0, mnu_old or 0, mpu_old or 0, mnpu_old or 0,
                month_rev_total_old or 0, month_rev_pure_old or 0
            ),
            "hyper": _build_server_monthly(
                mau_hyper or 0, mnu_hyper or 0, mpu_hyper or 0, mnpu_hyper or 0,
                month_rev_total_hyper or 0, month_rev_pure_hyper or 0
            ),
            "global": None,
        } if is_1st and mau_old is not None else None,

        # 패키지 TOP20
        "pkg_old":    packages_old[:20],
        "pkg_hyper":  packages_hyper[:20],
        "pkg_global": None,
    }

    out = METRICS_DIR / f"{date_str}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {out}")
    return doc


def aggregate_pkg_totals() -> dict:
    """전체 기간 패키지 누적 집계 (generate_dashboard에서 호출)"""
    totals_old:   dict[str, int] = {}
    totals_hyper: dict[str, int] = {}
    for f in sorted(METRICS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in d.get("pkg_old", []):
            totals_old[item["name"]] = totals_old.get(item["name"], 0) + item.get("qty", 0)
        for item in d.get("pkg_hyper", []):
            totals_hyper[item["name"]] = totals_hyper.get(item["name"], 0) + item.get("qty", 0)

    top_old   = sorted(totals_old.items(),   key=lambda x: -x[1])[:10]
    top_hyper = sorted(totals_hyper.items(), key=lambda x: -x[1])[:10]
    return {
        "old":   [{"name": n, "qty": q} for n, q in top_old],
        "hyper": [{"name": n, "qty": q} for n, q in top_hyper],
        "global": [],
    }


if __name__ == "__main__":
    missing = missing_dates()
    if missing:
        print(f"업데이트 필요한 날짜 ({len(missing)}일): {missing[0]} ~ {missing[-1]}")
    else:
        print("모든 날짜 최신 상태")
