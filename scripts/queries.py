#!/usr/bin/env python3
"""
DKR 지표 BigQuery 쿼리 레퍼런스
- 수정 내역:
  ① 총매출 하이퍼서버: serverid 46~55로 교정
  ② 순수유저매출 구서버/하이퍼서버 serverid 교정
  ③ 하이퍼서버 플랫폼 비중: market 집계 형태로 교정
  ④ 지표 쿼리: 구서버/하이퍼서버 분리 + 목요일 기준 주 정의 적용
  ⑤ 패키지 쿼리: 날짜 파라미터화

서버 구분:
  구서버  : serverid 1 ~ 45 (활성: 1~38, 99999)
  하이퍼  : serverid 46 ~ 55
  글로벌  : serverid 56 ~ 65 (미오픈)
"""

# ─────────────────────────────────────────────────────────────────
# 공통 서버 ID 목록
# ─────────────────────────────────────────────────────────────────
OLD_SERVER_IDS = ",".join(f"'{i}'" for i in list(range(1, 39)) + [99999])
HYPER_SERVER_IDS = ",".join(f"'{i}'" for i in range(46, 56))
GLOBAL_SERVER_IDS = ",".join(f"'{i}'" for i in range(56, 66))

OLD_VID_EXCL = "10143104663,10143099579,10143106399,10146716135,10146783921"
HYPER_VID_EXCL = "10154102860,10154099894,10154119282,10154136362,10154702857"
HYPER_PURE_VID_EXCL = "10161003379,10160939796,10160699281"

# ─────────────────────────────────────────────────────────────────
# 총매출 쿼리  (start_date ~ end_date 범위로 실행)
# ─────────────────────────────────────────────────────────────────

REVENUE_TOTAL_OLD = f"""
-- 총매출 구서버 (serverid 1~38, 99999)
SELECT
  DATE(t.datetime, "Asia/Seoul") AS purchaseDate,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM (
  SELECT datetime, productprice, currency, guid, bigqueryregisttimestamp
  FROM fluted-airline-109810.analytics_342_live.t_hive_purchase_log
  WHERE
    DATE(datetime, "Asia/Seoul") >= @start_date
    AND DATE(datetime, "Asia/Seoul") <= @end_date
    AND env <> "TEST"
    AND isException IS NULL
    AND appidgroup = 'DKR'
    AND serverid IN ({OLD_SERVER_IDS})
  QUALIFY ROW_NUMBER() OVER(PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
) AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
GROUP BY purchaseDate
ORDER BY purchaseDate DESC
"""

REVENUE_TOTAL_HYPER = f"""
-- 총매출 하이퍼서버 (serverid 46~55) ← 수정: 구서버 ID 오기재 교정
SELECT
  DATE(t.datetime, "Asia/Seoul") AS purchaseDate,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM (
  SELECT datetime, productprice, currency, guid, bigqueryregisttimestamp
  FROM fluted-airline-109810.analytics_342_live.t_hive_purchase_log
  WHERE
    DATE(datetime, "Asia/Seoul") >= @start_date
    AND DATE(datetime, "Asia/Seoul") <= @end_date
    AND env <> "TEST"
    AND isException IS NULL
    AND appidgroup = 'DKR'
    AND vid NOT IN ({HYPER_VID_EXCL})
    AND serverid IN ({HYPER_SERVER_IDS})
  QUALIFY ROW_NUMBER() OVER(PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
) AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
GROUP BY purchaseDate
ORDER BY purchaseDate DESC
"""

# ─────────────────────────────────────────────────────────────────
# 순수 유저 매출 쿼리 (환율 적용, verifyDateTimeKst 기준)
# ─────────────────────────────────────────────────────────────────

REVENUE_PURE_OLD = f"""
-- 순수유저매출 구서버 (serverid 1~38, 99999) ← 수정: 이전 쿼리에서 serverid 잘못 기재됨
SELECT
  FORMAT_DATETIME("%F", t.verifyDateTimeKst) AS purchaseDate,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM (
  SELECT *
  FROM `fluted-airline-109810.analytics_342_live.t_hive_purchase_log`
  WHERE
    DATE(datetime, "Asia/Seoul") >= @start_date
    AND DATE(datetime, "Asia/Seoul") <= @end_date
    AND appidgroup = 'DKR'
    AND env <> "TEST"
    AND isException IS NULL
    AND serverid IN ({OLD_SERVER_IDS})
  QUALIFY ROW_NUMBER() OVER (PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
) AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
GROUP BY purchaseDate
ORDER BY purchaseDate
"""

REVENUE_PURE_HYPER = f"""
-- 순수유저매출 하이퍼서버 (serverid 46~55)
SELECT
  FORMAT_DATETIME("%F", t.verifyDateTimeKst) AS purchaseDate,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM `fluted-airline-109810.analytics_342_live.t_hive_purchase_log` AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
WHERE
  DATE(t.datetime, "Asia/Seoul") >= @start_date
  AND DATE(t.datetime, "Asia/Seoul") <= @end_date
  AND t.appidgroup = 'DKR'
  AND t.env <> "TEST"
  AND t.isException IS NULL
  AND t.vid NOT IN ({HYPER_PURE_VID_EXCL})
  AND t.serverid IN ({HYPER_SERVER_IDS})
GROUP BY purchaseDate
ORDER BY purchaseDate
"""

# ─────────────────────────────────────────────────────────────────
# 플랫폼별 매출 비중 (당일 기준)
# ─────────────────────────────────────────────────────────────────

PLATFORM_SHARE_OLD = f"""
-- 구서버 플랫폼별 매출 비중 (당일)
SELECT
  t.market,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM (
  SELECT *
  FROM fluted-airline-109810.analytics_342_live.t_hive_purchase_log
  WHERE
    DATE(datetime, "Asia/Seoul") = @date
    AND env <> "TEST"
    AND isException IS NULL
    AND appidgroup = 'DKR'
    AND vid NOT IN ({OLD_VID_EXCL})
    AND serverid IN ({OLD_SERVER_IDS})
  QUALIFY ROW_NUMBER() OVER (PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
) AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
GROUP BY t.market
ORDER BY price_krw DESC
"""

PLATFORM_SHARE_HYPER = f"""
-- 하이퍼서버 플랫폼별 매출 비중 (당일) ← 수정: 이전 쿼리 구조 오류 교정
SELECT
  t.market,
  CAST(SUM(t.productprice * IFNULL(fx.ChangePrice, 1)) AS INT64) AS price_krw
FROM (
  SELECT *
  FROM fluted-airline-109810.analytics_342_live.t_hive_purchase_log
  WHERE
    DATE(datetime, "Asia/Seoul") = @date
    AND env <> "TEST"
    AND isException IS NULL
    AND appidgroup = 'DKR'
    AND vid NOT IN ({HYPER_PURE_VID_EXCL})
    AND serverid IN ({HYPER_SERVER_IDS})
  QUALIFY ROW_NUMBER() OVER (PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
) AS t
LEFT JOIN `dkr-bigquery.dkr_analysis.Currency to KRW` AS fx ON t.currency = fx.Currency
GROUP BY t.market
ORDER BY price_krw DESC
"""

# ─────────────────────────────────────────────────────────────────
# 지표 쿼리 (DAU/NU/PU/NPU/PUR + 주간/월간)
# 수정: ① 목요일 기준 주 정의 적용  ② 서버별 분리 (구서버/하이퍼서버)
#
# week_epoch = 2025-04-17 (서비스 출시 2025-04-18 직전 목요일)
# → 매 목요일 week_start, 수요일 week_end
# ─────────────────────────────────────────────────────────────────

def _build_metrics_query(server_label: str, server_ids_str: str) -> str:
    return f"""
-- 지표 쿼리: {server_label}
-- 주 기준: 목요일~수요일 (week_epoch = 2025-04-17)
WITH
base_date AS (
  SELECT
    DATE(TIMESTAMP '2025-04-18 00:00:00+09:00', 'Asia/Seoul') AS start_date,
    DATE '2025-04-17' AS week_epoch
),
date_range AS (
  SELECT
    week_index,
    DATE_ADD((SELECT week_epoch FROM base_date LIMIT 1),
             INTERVAL CAST(7 * week_index AS INT64) DAY) AS week_start,
    DATE_ADD((SELECT week_epoch FROM base_date LIMIT 1),
             INTERVAL CAST(7 * week_index + 6 AS INT64) DAY) AS week_end
  FROM UNNEST(GENERATE_ARRAY(
    0,
    CAST(CEIL(
      DATE_DIFF(DATE_SUB(CURRENT_DATE("Asia/Seoul"), INTERVAL 1 DAY),
                (SELECT week_epoch FROM base_date LIMIT 1), DAY) / 7
    ) AS INT64)
  )) AS week_index
),
month_range AS (
  SELECT
    FORMAT_DATE('%Y-%m', month) AS month_index,
    CASE
      WHEN FORMAT_DATE('%Y-%m', month) = '2025-04'
        THEN (SELECT start_date FROM base_date LIMIT 1)
      ELSE DATE_TRUNC(month, MONTH)
    END AS month_start,
    LAST_DAY(month) AS month_end
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE '2025-04-01',
    DATE_SUB(CURRENT_DATE("Asia/Seoul"), INTERVAL 1 DAY),
    INTERVAL 1 MONTH
  )) AS month
),
base_login AS (
  SELECT
    DATE(datetime, "Asia/Seoul") AS log_date,
    FLOOR(DATE_DIFF(DATE(datetime, "Asia/Seoul"),
          (SELECT week_epoch FROM base_date LIMIT 1), DAY) / 7) AS week_index,
    FORMAT_DATE('%Y-%m', DATE(datetime, "Asia/Seoul")) AS month_index,
    vid,
    newuser
  FROM `fluted-airline-109810.analytics_342_live.t_hive_login_log`
  WHERE DATE(datetime, "Asia/Seoul") >= (SELECT start_date FROM base_date LIMIT 1)
    AND DATE(datetime, "Asia/Seoul") < CURRENT_DATE("Asia/Seoul")
    AND appidgroup = 'DKR'
    AND serverid IN ({server_ids_str})
  GROUP BY log_date, week_index, month_index, vid, newuser
),
base_purchase AS (
  SELECT
    DATE(datetime, "Asia/Seoul") AS purchase_date,
    FLOOR(DATE_DIFF(DATE(datetime, "Asia/Seoul"),
          (SELECT week_epoch FROM base_date LIMIT 1), DAY) / 7) AS week_index,
    FORMAT_DATE('%Y-%m', DATE(datetime, "Asia/Seoul")) AS month_index,
    vid,
    ROW_NUMBER() OVER (PARTITION BY vid ORDER BY datetime) AS rn
  FROM `fluted-airline-109810.analytics_342_live.t_hive_purchase_log`
  WHERE DATE(datetime, "Asia/Seoul") >= (SELECT start_date FROM base_date LIMIT 1)
    AND DATE(datetime, "Asia/Seoul") < CURRENT_DATE("Asia/Seoul")
    AND appidgroup = 'DKR'
    AND env != "TEST"
    AND isException IS NULL
    AND serverid IN ({server_ids_str})
),
daily_metrics AS (
  SELECT week_index, month_index, log_date,
    COUNT(DISTINCT vid) AS dau,
    COUNT(DISTINCT IF(newuser = "Y", vid, NULL)) AS nu
  FROM base_login
  GROUP BY week_index, month_index, log_date
),
daily_purchases AS (
  SELECT week_index, month_index, purchase_date,
    COUNT(DISTINCT vid) AS pu,
    COUNT(DISTINCT IF(rn = 1, vid, NULL)) AS npu
  FROM base_purchase
  GROUP BY week_index, month_index, purchase_date
),
weekly_agg AS (
  SELECT
    l.week_index,
    COUNT(DISTINCT l.vid) AS wau,
    COUNT(DISTINCT IF(l.newuser = "Y", l.vid, NULL)) AS wnu,
    COUNT(DISTINCT p.vid) AS wpu,
    COUNT(DISTINCT IF(p.rn = 1, p.vid, NULL)) AS wnpu
  FROM base_login l
  LEFT JOIN base_purchase p ON l.week_index = p.week_index AND l.vid = p.vid
  GROUP BY l.week_index
),
monthly_agg AS (
  SELECT
    l.month_index,
    COUNT(DISTINCT l.vid) AS mau,
    COUNT(DISTINCT IF(l.newuser = "Y", l.vid, NULL)) AS mnu,
    COUNT(DISTINCT p.vid) AS mpu,
    COUNT(DISTINCT IF(p.rn = 1, p.vid, NULL)) AS mnpu
  FROM base_login l
  LEFT JOIN base_purchase p ON l.month_index = p.month_index AND l.vid = p.vid
  GROUP BY l.month_index
)
SELECT
  d.log_date,
  d.dau, d.nu,
  dp.pu, dp.npu,
  SAFE_DIVIDE(dp.pu, d.dau) AS pur,
  -- 주간 (목요일에만 표시)
  CASE WHEN d.log_date = r.week_start THEN w.wau  ELSE NULL END AS wau,
  CASE WHEN d.log_date = r.week_start THEN w.wnu  ELSE NULL END AS wnu,
  CASE WHEN d.log_date = r.week_start THEN w.wpu  ELSE NULL END AS wpu,
  CASE WHEN d.log_date = r.week_start THEN w.wnpu ELSE NULL END AS wnpu,
  CASE WHEN d.log_date = r.week_start THEN SAFE_DIVIDE(w.wpu, w.wau) ELSE NULL END AS wpur,
  -- 월간 (1일에만 표시)
  CASE WHEN d.log_date = m.month_start THEN ma.mau  ELSE NULL END AS mau,
  CASE WHEN d.log_date = m.month_start THEN ma.mnu  ELSE NULL END AS mnu,
  CASE WHEN d.log_date = m.month_start THEN ma.mpu  ELSE NULL END AS mpu,
  CASE WHEN d.log_date = m.month_start THEN ma.mnpu ELSE NULL END AS mnpu,
  CASE WHEN d.log_date = m.month_start THEN SAFE_DIVIDE(ma.mpu, ma.mau) ELSE NULL END AS mpur
FROM daily_metrics d
LEFT JOIN daily_purchases dp
  ON d.week_index = dp.week_index AND d.log_date = dp.purchase_date
LEFT JOIN weekly_agg w ON d.week_index = w.week_index
LEFT JOIN date_range r ON d.week_index = r.week_index
LEFT JOIN month_range m ON d.month_index = FORMAT_DATE('%Y-%m', m.month_start)
LEFT JOIN monthly_agg ma ON d.month_index = ma.month_index
ORDER BY d.log_date
"""


METRICS_OLD   = _build_metrics_query("구서버", OLD_SERVER_IDS)
METRICS_HYPER = _build_metrics_query("하이퍼서버", HYPER_SERVER_IDS)
METRICS_GLOBAL = _build_metrics_query("글로벌서버 (미오픈)", GLOBAL_SERVER_IDS)

# ─────────────────────────────────────────────────────────────────
# 패키지 쿼리 (날짜 파라미터화)
# ─────────────────────────────────────────────────────────────────

def _build_package_query(server_label: str, server_ids_str: str) -> str:
    return f"""
-- 패키지 판매량: {server_label} (@date 기준)
SELECT
  productname,
  SUM(quantity) AS qty
FROM (
  SELECT productname, quantity, guid, bigqueryregisttimestamp
  FROM fluted-airline-109810.analytics_342_live.t_hive_purchase_log
  WHERE
    DATE(datetime, "Asia/Seoul") = @date
    AND appidgroup = 'DKR'
    AND env <> 'TEST'
    AND serverid IN ({server_ids_str})
  QUALIFY ROW_NUMBER() OVER(PARTITION BY guid ORDER BY bigqueryregisttimestamp ASC) = 1
)
GROUP BY productname
ORDER BY qty DESC
"""


PACKAGES_OLD   = _build_package_query("구서버", OLD_SERVER_IDS)
PACKAGES_HYPER = _build_package_query("하이퍼서버", HYPER_SERVER_IDS)
PACKAGES_GLOBAL = _build_package_query("글로벌서버 (미오픈)", GLOBAL_SERVER_IDS)


# ─────────────────────────────────────────────────────────────────
# 전체 쿼리 목록 (반자동화 실행 순서)
# ─────────────────────────────────────────────────────────────────
ALL_QUERIES = {
    "revenue_total_old":    REVENUE_TOTAL_OLD,
    "revenue_total_hyper":  REVENUE_TOTAL_HYPER,
    "revenue_pure_old":     REVENUE_PURE_OLD,
    "revenue_pure_hyper":   REVENUE_PURE_HYPER,
    "platform_old":         PLATFORM_SHARE_OLD,
    "platform_hyper":       PLATFORM_SHARE_HYPER,
    "metrics_old":          METRICS_OLD,
    "metrics_hyper":        METRICS_HYPER,
    "packages_old":         PACKAGES_OLD,
    "packages_hyper":       PACKAGES_HYPER,
}


if __name__ == "__main__":
    for name, q in ALL_QUERIES.items():
        print(f"\n{'='*60}")
        print(f"[{name}]")
        print(q[:300] + "..." if len(q) > 300 else q)
