#!/usr/bin/env python3
"""
export_metrics.py — DKR 지표 BigQuery → metrics JSON 내보내기 v2.0
============================================================
[데이터 소스] — 반드시 아래 두 테이블만 사용
  - call-of-chaos.dkr_analysis.metrics_preset
  - call-of-chaos.dkr_analysis.package_sales_preset

[JSON 저장 경로]
  data/DKR/metrics/YYYY-MM-DD.metrics.json

[스키마]
  metrics_preset       : date, serverid, server_group, dau, nu, pu, npu, total_revenue, user_revenue
  package_sales_preset : period_type(today/period), date, server_group(total/old/hyper/sea),
                         rank_no, productid, productname, sales_quantity, payment_count, pu, revenue_krw

사용법:
  python3 export_metrics.py               # 최신 날짜 자동
  python3 export_metrics.py 2026-05-17    # 특정 날짜 지정
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

# ── BigQuery 테이블 경로 (변경 금지) ─────────────────────────────────────────
BQ_METRICS  = "call-of-chaos.dkr_analysis.metrics_preset"
BQ_PACKAGES = "call-of-chaos.dkr_analysis.package_sales_preset"


def bq_query(sql: str) -> list[dict]:
    """google-cloud-bigquery SDK 사용."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client()
        rows = list(client.query(sql).result())
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[BQ ERROR] {e}")
        sys.exit(1)


def detect_latest_date() -> str:
    """metrics_preset 기준 최신 date 반환."""
    rows = bq_query(f"SELECT MAX(date) AS latest FROM `{BQ_METRICS}`")
    if rows and rows[0].get("latest"):
        v = rows[0]["latest"]
        return v if isinstance(v, str) else str(v)
    return (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_servers(date_str: str) -> list[dict]:
    """당일 serverid 단위 지표 (65건) 반환."""
    rows = bq_query(f"""
        SELECT date, serverid, server_group,
               dau, nu, pu, npu, total_revenue, user_revenue
        FROM `{BQ_METRICS}`
        WHERE date = '{date_str}'
        ORDER BY serverid
    """)
    return [
        {
            "serverid":      int(r["serverid"]),
            "server_group":  r["server_group"],
            "dau":           int(r["dau"] or 0),
            "nu":            int(r["nu"]  or 0),
            "pu":            int(r["pu"]  or 0),
            "npu":           int(r["npu"] or 0),
            "total_revenue": int(r["total_revenue"] or 0),
            "user_revenue":  int(r["user_revenue"]  or 0),
        }
        for r in rows
    ]


def fetch_trend_7d(date_str: str) -> list[dict]:
    """최근 7일(date_str 포함) serverid 단위 trend 반환."""
    dt    = datetime.strptime(date_str, "%Y-%m-%d")
    start = (dt - timedelta(days=6)).strftime("%Y-%m-%d")
    rows  = bq_query(f"""
        SELECT date, serverid, server_group,
               dau, nu, pu, npu, total_revenue, user_revenue
        FROM `{BQ_METRICS}`
        WHERE date BETWEEN '{start}' AND '{date_str}'
        ORDER BY date, serverid
    """)
    from collections import defaultdict
    by_date: dict = defaultdict(list)
    for r in rows:
        d = str(r["date"])
        by_date[d].append({
            "serverid":      int(r["serverid"]),
            "server_group":  r["server_group"],
            "dau":           int(r["dau"] or 0),
            "nu":            int(r["nu"]  or 0),
            "pu":            int(r["pu"]  or 0),
            "npu":           int(r["npu"] or 0),
            "total_revenue": int(r["total_revenue"] or 0),
            "user_revenue":  int(r["user_revenue"]  or 0),
        })
    return [{"date": d, "servers": by_date[d]} for d in sorted(by_date)]


def fetch_packages(date_str: str) -> dict:
    """package_sales_preset → {today:{old/hyper/sea/total:[...]}, period:{...}} 형식."""
    rows = bq_query(f"""
        SELECT period_type, server_group, rank_no,
               productid, productname,
               sales_quantity, payment_count, pu, revenue_krw
        FROM `{BQ_PACKAGES}`
        WHERE date = '{date_str}'
        ORDER BY period_type, server_group, rank_no
    """)
    result: dict = {
        "today":  {"old": [], "hyper": [], "sea": [], "total": []},
        "period": {"old": [], "hyper": [], "sea": [], "total": []},
    }
    for r in rows:
        pt  = r["period_type"]   # 'today' / 'period'
        sg  = r["server_group"]  # 'old' / 'hyper' / 'sea' / 'total'
        if pt not in result or sg not in result[pt]:
            continue
        result[pt][sg].append({
            "rank_no":        int(r["rank_no"]),
            "productid":      r["productid"],
            "productname":    r["productname"],
            "sales_quantity": int(r["sales_quantity"] or 0),
            "payment_count":  int(r["payment_count"]  or 0),
            "pu":             int(r["pu"] or 0),
            "revenue_krw":    int(r["revenue_krw"] or 0),
        })
    return result


def export_date(date_str: str) -> Path:
    """단일 날짜 metrics JSON 생성."""
    print(f"\n[export] {date_str}")
    print(f"  [fetch] servers from {BQ_METRICS}")
    servers = fetch_servers(date_str)
    print(f"  → {len(servers)}개 서버")

    print(f"  [fetch] trend_7d")
    trend_7d = fetch_trend_7d(date_str)
    print(f"  → {len(trend_7d)}일")

    print(f"  [fetch] package_sales from {BQ_PACKAGES}")
    pkg = fetch_packages(date_str)

    out = {
        "date":         date_str,
        "data_source":  f"{BQ_METRICS} / {BQ_PACKAGES}",
        "servers":      servers,
        "trend_7d":     trend_7d,
        "package_sales": pkg,
    }
    path = DATA_DIR / f"{date_str}.metrics.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [saved] {path.name}")
    return path


def main():
    parser = argparse.ArgumentParser(description="DKR metrics JSON export (metrics_preset 기반)")
    parser.add_argument("date", nargs="?", default=None,
                        help="YYYY-MM-DD (기본: 최신 날짜 자동 감지)")
    args = parser.parse_args()

    target = args.date or detect_latest_date()
    export_date(target)
    print("\n[DONE]")


if __name__ == "__main__":
    main()
