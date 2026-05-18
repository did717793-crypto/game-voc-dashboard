#!/usr/bin/env python3
"""
export_metrics.py — DKR 지표 BigQuery → metrics JSON 내보내기
============================================================
저장 경로: data/DKR/metrics/YYYY-MM-DD.metrics.json

[데이터 소스]
  - dkr_analysis.daily_gross  : 총 매출 (serverGroup 기준)
  - dkr_analysis.daily_net    : 유저 매출 + PU 수 (serverGroup 기준)
  - dkr_analysis.daily_pkg    : 패키지 판매 (serverGroup 기준)

[서버 그룹 매핑]
  - 구서버  (old)  : serverid 1 ~ 45  (BigQuery: '구서버')
  - 하이퍼  (hyper): serverid 46 ~ 55 (BigQuery: '하이퍼서버')
  - 동남아  (sea)  : serverid 56 ~ 65 (BigQuery: 미오픈, 데이터 없음)

[참고]
  metrics_preset / package_sales_preset 테이블은 현재 프로젝트에 미존재.
  위 원천 테이블을 직접 사용하여 동일한 스키마를 구성합니다.
  DAU/NU/NPU는 daily_dau_by_server 최신화 이후 반영됩니다.

사용법:
  python3 export_metrics.py               # 최신 날짜 자동
  python3 export_metrics.py 2026-04-29    # 특정 날짜
  python3 export_metrics.py --backfill    # 미저장 날짜 일괄 처리
"""

import json
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 경로 ──────────────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).parent
DATA_DIR     = SCRIPTS_DIR.parent / "data" / "DKR" / "metrics"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KST          = timezone(timedelta(hours=9))

# ── 서버 그룹 정의 ─────────────────────────────────────────────────────────────
SERVER_GROUPS = {
    "old":   {"label": "구서버",   "bq_name": "구서버",   "range": (1,  45)},
    "hyper": {"label": "하이퍼서버", "bq_name": "하이퍼서버", "range": (46, 55)},
    "sea":   {"label": "동남아서버", "bq_name": "동남아서버", "range": (56, 65)},
}


# ── BigQuery 조회 ──────────────────────────────────────────────────────────────
def bq_query(sql: str) -> list[dict]:
    """ntrance-bigquery MCP 대신 google-cloud-bigquery SDK 직접 사용."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client()
        rows = list(client.query(sql).result())
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[BQ ERROR] {e}")
        return []


def fetch_revenue(date_str: str) -> dict[str, dict]:
    """총매출 / 유저매출 / PU 수 → {group_key: {total_revenue, user_revenue, pu}}"""
    result = {k: {"total_revenue": 0, "user_revenue": 0, "pu": 0}
              for k in SERVER_GROUPS}

    # 총 매출
    gross_rows = bq_query(f"""
        SELECT serverGroup, price_krw
        FROM `dkr_analysis.daily_gross`
        WHERE purchaseDate = '{date_str}'
    """)
    for row in gross_rows:
        grp = _map_group(row["serverGroup"])
        if grp:
            result[grp]["total_revenue"] = int(row["price_krw"] or 0)

    # 유저 매출 + PU
    net_rows = bq_query(f"""
        SELECT serverGroup, price_krw, pu_count
        FROM `dkr_analysis.daily_net`
        WHERE purchaseDate = '{date_str}'
    """)
    for row in net_rows:
        grp = _map_group(row["serverGroup"])
        if grp:
            result[grp]["user_revenue"] = int(row["price_krw"] or 0)
            result[grp]["pu"]           = int(row["pu_count"] or 0)

    return result


def fetch_dau(date_str: str) -> dict[str, int]:
    """DAU → {group_key: dau}  (daily_dau_by_server)"""
    result = {k: 0 for k in SERVER_GROUPS}
    rows = bq_query(f"""
        SELECT server_group, dau
        FROM `dkr_analysis.daily_dau_by_server`
        WHERE login_date = '{date_str}'
    """)
    for row in rows:
        # daily_dau_by_server의 server_group은 'old'/'hyper' 형식
        grp = row["server_group"] if row["server_group"] in SERVER_GROUPS else None
        if grp:
            result[grp] = int(row["dau"] or 0)
    return result


def fetch_packages(date_str: str, period_type: str = "today") -> dict[str, list]:
    """패키지 판매 TOP10 → {group_key: [...]}

    period_type:
      'today'  : 당일 데이터
      'period' : 전체 기간 (가용 최신 날짜 기준 누적 TOP10 근사)
    """
    result: dict[str, list] = {k: [] for k in list(SERVER_GROUPS.keys()) + ["total"]}

    if period_type == "today":
        rows = bq_query(f"""
            SELECT serverGroup, productname,
                   SUM(total_quantity) AS sales_quantity,
                   SUM(unique_pu)      AS pu,
                   unit_price_krw
            FROM `dkr_analysis.daily_pkg`
            WHERE purchase_date = '{date_str}'
            GROUP BY serverGroup, productname, unit_price_krw
            ORDER BY serverGroup, sales_quantity DESC
        """)
    else:
        # 최근 30일 누적
        dt_from = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d")
        rows = bq_query(f"""
            SELECT serverGroup, productname,
                   SUM(total_quantity) AS sales_quantity,
                   SUM(unique_pu)      AS pu,
                   MAX(unit_price_krw) AS unit_price_krw
            FROM `dkr_analysis.daily_pkg`
            WHERE purchase_date BETWEEN '{dt_from}' AND '{date_str}'
            GROUP BY serverGroup, productname
            ORDER BY serverGroup, sales_quantity DESC
        """)

    # 그룹별 TOP10 구성
    tmp: dict[str, list] = {k: [] for k in list(SERVER_GROUPS.keys()) + ["total"]}
    all_products: dict[str, dict] = {}   # productname → aggregated

    for rank_local, row in enumerate(rows, 1):
        grp = _map_group(row["serverGroup"])
        if not grp:
            continue
        entry = {
            "rank_no":        len(tmp[grp]) + 1,
            "productname":    row["productname"],
            "sales_quantity": int(row["sales_quantity"] or 0),
            "pu":             int(row["pu"] or 0),
            "revenue_krw":    int(row["sales_quantity"] or 0) * int(row["unit_price_krw"] or 0),
        }
        if len(tmp[grp]) < 10:
            tmp[grp].append(entry)

        # 전체 집계
        pn = row["productname"]
        if pn not in all_products:
            all_products[pn] = {"sales_quantity": 0, "pu": 0, "revenue_krw": 0}
        all_products[pn]["sales_quantity"] += entry["sales_quantity"]
        all_products[pn]["pu"]             += entry["pu"]
        all_products[pn]["revenue_krw"]    += entry["revenue_krw"]

    # 전체 TOP10
    sorted_total = sorted(all_products.items(), key=lambda x: -x[1]["sales_quantity"])
    for i, (pn, vals) in enumerate(sorted_total[:10], 1):
        tmp["total"].append({"rank_no": i, "productname": pn, **vals})

    return tmp


# ── 그룹 매핑 헬퍼 ────────────────────────────────────────────────────────────
def _map_group(bq_name: str) -> str | None:
    """BigQuery serverGroup 한글명 → 내부 key (old/hyper/sea)"""
    MAP = {"구서버": "old", "하이퍼서버": "hyper", "동남아서버": "sea"}
    return MAP.get(bq_name)


# ── JSON 구조 생성 ─────────────────────────────────────────────────────────────
def build_server_entry(group_key: str, revenue: dict, dau_val: int) -> dict:
    """그룹 집계값 → servers[] 항목 (그룹 대표 집계 1건)

    serverid는 그룹 범위 중앙값 사용 (식별용, 실제 개별 서버 데이터 아님).
    개별 서버 데이터는 metrics_preset 테이블 구축 후 업그레이드 필요.
    """
    grp_def = SERVER_GROUPS[group_key]
    lo, hi  = grp_def["range"]
    mid_id  = (lo + hi) // 2          # 범위 중앙 (e.g. old → 23)

    rev   = revenue.get(group_key, {})
    tot_rev  = rev.get("total_revenue", 0)
    user_rev = rev.get("user_revenue", 0)
    pu       = rev.get("pu", 0)
    dau      = dau_val

    pur   = round(pu / dau, 4) if dau > 0 else 0
    arpu  = round(user_rev / dau)  if dau > 0 else 0
    arppu = round(user_rev / pu)   if pu  > 0 else 0

    return {
        "serverid":      mid_id,
        "server_name":   f"{grp_def['label']} ({lo}~{hi}번 서버 합산)",
        "server_group":  group_key,
        "dau":           dau,
        "nu":            0,   # 미제공 (metrics_preset 구축 시 업데이트)
        "pu":            pu,
        "npu":           0,   # 미제공
        "total_revenue": tot_rev,
        "user_revenue":  user_rev,
        "pur":           pur,
        "arpu":          arpu,
        "arppu":         arppu,
    }


def build_metrics_json(date_str: str) -> dict:
    """지정 날짜 → metrics JSON 완성본"""
    print(f"  [fetch] revenue  {date_str}")
    revenue = fetch_revenue(date_str)
    print(f"  [fetch] dau      {date_str}")
    dau_map = fetch_dau(date_str)
    print(f"  [fetch] packages today  {date_str}")
    pkg_today  = fetch_packages(date_str, "today")
    print(f"  [fetch] packages period {date_str}")
    pkg_period = fetch_packages(date_str, "period")

    servers = []
    for grp_key in ["old", "hyper", "sea"]:
        entry = build_server_entry(grp_key, revenue, dau_map.get(grp_key, 0))
        servers.append(entry)

    return {
        "date":    date_str,
        "servers": servers,
        # trend_7d는 export_with_trend() 에서 채움
        "trend_7d": [],
        "package_sales": {
            "today":  {
                "old":   pkg_today.get("old",   []),
                "hyper": pkg_today.get("hyper", []),
                "sea":   pkg_today.get("sea",   []),
                "total": pkg_today.get("total", []),
            },
            "period": {
                "old":   pkg_period.get("old",   []),
                "hyper": pkg_period.get("hyper", []),
                "sea":   pkg_period.get("sea",   []),
                "total": pkg_period.get("total", []),
            },
        },
    }


def build_trend_7d(latest_date: str) -> list[dict]:
    """최근 7일 trend_7d 리스트 생성"""
    dt = datetime.strptime(latest_date, "%Y-%m-%d")
    trend = []
    for i in range(6, -1, -1):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"  [trend] {d}")
        rev     = fetch_revenue(d)
        dau_map = fetch_dau(d)
        day_servers = []
        for grp_key in ["old", "hyper", "sea"]:
            r = rev.get(grp_key, {})
            day_servers.append({
                "serverid":     SERVER_GROUPS[grp_key]["range"][0],
                "server_group": grp_key,
                "dau":          dau_map.get(grp_key, 0),
                "nu":           0,
                "pu":           r.get("pu", 0),
                "npu":          0,
                "total_revenue": r.get("total_revenue", 0),
                "user_revenue":  r.get("user_revenue", 0),
            })
        trend.append({"date": d, "servers": day_servers})
    return trend


# ── 최신 날짜 감지 ────────────────────────────────────────────────────────────
def detect_latest_date() -> str:
    """BigQuery daily_gross 기준 최신 날짜 반환"""
    rows = bq_query("SELECT MAX(purchaseDate) AS latest FROM `dkr_analysis.daily_gross`")
    if rows and rows[0].get("latest"):
        v = rows[0]["latest"]
        return v if isinstance(v, str) else str(v)
    # fallback: 어제 KST
    return (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")


def get_missing_dates(from_date: str = "2026-04-18") -> list[str]:
    """from_date ~ 최신 날짜 중 JSON 미생성 날짜 목록"""
    latest  = detect_latest_date()
    existing = {f.stem.replace(".metrics", "") for f in DATA_DIR.glob("*.metrics.json")}
    dt = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(latest, "%Y-%m-%d")
    result = []
    while dt <= end:
        ds = dt.strftime("%Y-%m-%d")
        if ds not in existing:
            result.append(ds)
        dt += timedelta(days=1)
    return result


# ── 저장 ─────────────────────────────────────────────────────────────────────
def export_date(date_str: str, with_trend: bool = True) -> Path:
    """단일 날짜 metrics JSON 생성 및 저장"""
    print(f"\n[export] {date_str}")
    data = build_metrics_json(date_str)

    if with_trend:
        print(f"  [trend_7d] 최근 7일 데이터 수집...")
        data["trend_7d"] = build_trend_7d(date_str)

    out = DATA_DIR / f"{date_str}.metrics.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [saved] {out.name}")
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DKR metrics JSON 내보내기")
    parser.add_argument("date", nargs="?", default=None,
                        help="대상 날짜 YYYY-MM-DD (기본: 최신 날짜 자동 감지)")
    parser.add_argument("--backfill", action="store_true",
                        help="미저장 날짜 일괄 처리")
    parser.add_argument("--no-trend", action="store_true",
                        help="trend_7d 생성 생략")
    args = parser.parse_args()

    if args.backfill:
        missing = get_missing_dates()
        print(f"[backfill] 미저장 날짜: {len(missing)}건")
        for d in missing:
            try:
                export_date(d, with_trend=(d == missing[-1]))  # 마지막만 trend
            except Exception as e:
                print(f"  [ERROR] {d}: {e}")
    else:
        target = args.date or detect_latest_date()
        export_date(target, with_trend=not args.no_trend)

    print("\n[DONE]")


if __name__ == "__main__":
    main()
