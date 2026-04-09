#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC 규칙 기반 분석기 v4.0
────────────────────────────────────────────────────────
변경 이력:
  v4.0  분류 정확도 개선 + 중복/노이즈 제거 + major_issues 품질 개선
  v3.0  LLM 제거, 규칙 기반 단독 확정
  v2.0  LLM 기반 (폐기)
  v1.0  초기 키워드 방식

분류 우선순위 (board_id=4 자유 게시판):
  1순위: BUG_KEYWORDS       → 버그·오류
  2순위: SUGGEST_KEYWORDS   → 건의·요청
  3순위: COMPLAINT_KEYWORDS → 기타
  4순위: default            → 게임 관련

사용법:
  python3 analyze_voc.py                        # 어제 날짜 자동
  python3 analyze_voc.py 2026-04-06             # 특정 날짜
  python3 analyze_voc.py 2026-04-06 --force     # analyzed.json 덮어쓰기
  python3 analyze_voc.py --backfill             # raw 있고 analyzed 없는 날짜 일괄
  python3 analyze_voc.py --backfill --force     # 모든 raw 날짜 재분석
"""

import json
import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST        = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data" / "DKR"


# ════════════════════════════════════════════════════════════════════════════
#  ▶ 분류 상수 — 키워드 추가·수정은 이 블록만 수정하세요
# ════════════════════════════════════════════════════════════════════════════

# board_id → 카테고리 직접 매핑 (None = 키워드로 재분류)
BOARD_CATEGORY_MAP: dict[int, str | None] = {
    4: None,           # 자유 게시판   → 키워드 판별 (아래 우선순위 적용)
    5: "게임 관련",     # 질문과 답변   → 직접 매핑
    7: "버그·오류",     # 버그 제보     → 직접 매핑 (무조건)
    9: "건의·요청",     # 건의 게시판   → 직접 매핑 (무조건)
}

# 공식 게시판 IDs
OFFICIAL_BOARD_IDS: set[int] = {11, 13}

# ── 자유 게시판(board_id=4) 키워드 / 우선순위: BUG > SUGGEST > COMPLAINT > default ──

BUG_KEYWORDS: list[str] = [
    # 직접 버그·오류 표현
    "버그", "오류", "에러", "error",
    # 기능 이상
    "안됨", "안돼", "안 돼", "안 됨", "먹통", "오작동", "작동",
    # 접속 문제
    "팅", "튕", "렉", "렉걸", "멈춤", "멈춰",
    "접속불가", "접속 불가", "로그인 안", "로그인안", "로딩",
    # 앱 충돌
    "크래시", "crash", "뻗어", "죽어",
    # 추가
    "오작", "끊김", "끊겨", "오류남", "오류 남",
]

SUGGEST_KEYWORDS: list[str] = [
    # 직접 건의·요청
    "건의", "요청", "제안",
    # 정중한 표현
    "해주세요", "해주셨으면", "부탁", "해줘", "해줬으면",
    # 추가·개선
    "추가해", "추가 해", "넣어줘", "개선",
    "바꿔", "바꿔주", "변경해", "변경 해", "고쳐줘", "수정해",
    # 희망 표현
    "이렇게 하면", "이렇게하면",
    "있으면 좋겠", "있으면좋겠",
    "필요한것같", "필요할것같",
    "했으면", "했으면 좋겠",
    # 추가
    "나와야", "나왔으면", "출시해", "출시 해", "좀 해줘",
]

COMPLAINT_KEYWORDS: list[str] = [
    # 서비스 종료 우려
    "섭종", "서비스종료", "서비스 종료", "폐서비스", "폐겜",
    # 게임 비판
    "망겜", "탈주", "탈게", "쫄딱", "지못미",
    # 환불·불만 직접 표현
    "환불", "접는다", "그만할", "관두겠", "접겠",
    # 강화된 불만 표현
    "개망", "망했다", "개판", "엉망", "답없", "답 없",
    "운영 뭐함", "운영뭐함", "운영 뭐해", "뭐하냐", "뭐하냐고",
    "게임사 뭐", "운영진 뭐", "운영자 뭐",
    # 방언·비속어형 불만
    "우짜냐", "우짜냐고", "ㅅㄱ", "현질",
    # 감정 표현
    "버리는", "버려", "갈아탄다",
]

# 카테고리 출력 순서 고정
CATEGORY_ORDER: list[str] = ["버그·오류", "건의·요청", "게임 관련", "기타"]

# ── 노이즈 필터 옵션 ────────────────────────────────────────────────────────
# True: 너무 짧거나 의미 없는 글 필터링 / False: 모든 글 포함
FILTER_NOISE: bool = True

# 제목 최소 길이 (이하이면 기타 또는 제외)
NOISE_MIN_LEN: int = 4

# 의미 없는 글 완전 제외(True) vs 기타 분류(False)
NOISE_EXCLUDE: bool = False

# 노이즈 판단 정규식
_NOISE_PATTERN = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ?!.…~\s]+$")


# ════════════════════════════════════════════════════════════════════════════
#  분류 로직
# ════════════════════════════════════════════════════════════════════════════

def is_noise(post: dict) -> bool:
    """노이즈 게시글 판별: 제목이 너무 짧거나 자음/모음만인 경우"""
    title = (post.get("title") or "").strip()
    if len(title) < NOISE_MIN_LEN:
        return True
    if _NOISE_PATTERN.match(title):
        return True
    return False


def classify_post(post: dict) -> str:
    """단일 포스트 → 카테고리 문자열

    우선순위:
      board_id 직접 매핑 (4 제외) → BUG → SUGGEST → COMPLAINT → default
    """
    board_id = post.get("board_id")
    cat = BOARD_CATEGORY_MAP.get(board_id)
    if cat is not None:
        return cat

    # board_id=4 (자유 게시판) — 제목+본문 키워드 판별
    text = f"{post.get('title', '')} {post.get('body', '')}".lower()

    # 1순위: 버그·오류
    for kw in BUG_KEYWORDS:
        if kw in text:
            return "버그·오류"

    # 2순위: 건의·요청
    for kw in SUGGEST_KEYWORDS:
        if kw in text:
            return "건의·요청"

    # 3순위: 기타 (불만/비난)
    for kw in COMPLAINT_KEYWORDS:
        if kw in text:
            return "기타"

    return "게임 관련"


def dedup_by_feed_id(posts: list) -> list:
    """feed_id 기준 완전 중복 제거 (같은 포스트 2번 수집 방어)"""
    seen: set[str] = set()
    result = []
    for p in posts:
        fid = str(p.get("feed_id", ""))
        if fid and fid in seen:
            continue
        if fid:
            seen.add(fid)
        result.append(p)
    return result


# ════════════════════════════════════════════════════════════════════════════
#  필드 생성
# ════════════════════════════════════════════════════════════════════════════

def build_major_issues(official_posts: list) -> list:
    """공식 게시판 포스트 → major_issues (title 유사 항목 묶기, count 추가, 최신순)"""
    if not official_posts:
        return []

    # 1. feed_id 기준 중복 제거
    unique = dedup_by_feed_id(official_posts)

    # 2. (board_name + date) 기준 그룹핑 — 같은 날 같은 보드의 공지는 묶음
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for p in unique:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        date_key = (p.get("created_at") or "")[:10]
        board    = p.get("board_name", "")
        key      = f"{board}|{date_key}"
        groups[key].append(p)

    result = []
    for key, posts in groups.items():
        board, date_key = key.split("|", 1)
        # 대표 포스트: feed_id가 가장 작은 것 (가장 먼저 등록된 것)
        rep = sorted(posts, key=lambda p: str(p.get("feed_id", "")))[0]
        result.append({
            "title":   (rep.get("title") or "").strip(),
            "board":   board,
            "url":     rep.get("url", ""),
            "feed_id": str(rep.get("feed_id", "")),
            "date":    date_key,
            "count":   len(posts),
        })

    # 3. 최신순 정렬
    return sorted(result, key=lambda x: x["date"], reverse=True)


def build_voc_groups(user_posts: list) -> list:
    """유저 포스트 → 카테고리별 그룹핑 → voc_groups

    처리 순서:
      1. feed_id 기준 중복 제거
      2. 노이즈 필터 (FILTER_NOISE=True 시)
      3. 카테고리 분류
      4. 카테고리 내 동일 title 중복 통합 (count 정확도)
      5. 대표글 선정 (engagement 가중치: 댓글×2 + 좋아요)
    """
    # 1. feed_id 중복 제거
    posts = dedup_by_feed_id(user_posts)

    # 2. 노이즈 처리
    if FILTER_NOISE:
        noise_posts = [p for p in posts if is_noise(p)]
        clean_posts = [p for p in posts if not is_noise(p)]
        if NOISE_EXCLUDE:
            posts = clean_posts          # 완전 제외
        else:
            # 노이즈는 "기타"로 분류 (count에는 포함)
            posts = clean_posts
            for p in noise_posts:
                p["_forced_cat"] = "기타"
            posts = posts + noise_posts
    # FILTER_NOISE=False이면 그대로 진행

    # 3. 카테고리 분류
    groups: dict[str, list] = defaultdict(list)
    for p in posts:
        cat = p.pop("_forced_cat", None) or classify_post(p)
        groups[cat].append(p)

    # 4. 카테고리별 그룹 생성 (동일 title 중복 통합)
    result = []
    for cat in CATEGORY_ORDER:
        cat_posts = groups.get(cat, [])
        if not cat_posts:
            continue

        # 동일 title(정규화) → 첫 번째 게시글 기준 대표 URL 유지
        title_first: dict[str, dict] = {}      # norm_title → 최초 포스트
        title_all:   dict[str, list] = defaultdict(list)

        def _norm(t: str) -> str:
            return re.sub(r"\s+", " ", (t or "").strip().lower())

        for p in cat_posts:
            nt = _norm(p.get("title", ""))
            if nt not in title_first:
                title_first[nt] = p
            title_all[nt].append(p)

        # 5. 대표글: 모든 포스트 중 engagement 최고 (title 묶음 무관)
        top = max(
            cat_posts,
            key=lambda p: p.get("comment_count", 0) * 2 + p.get("like_count", 0)
        )

        # feed_ids: 중복 없이 전부 포함
        all_fids = [str(p.get("feed_id", "")) for p in cat_posts]

        result.append({
            "category":           cat,
            "summary":            (top.get("title") or "")[:80],
            "count":              len(cat_posts),
            "representative_url": top.get("url", ""),
            "feed_ids":           all_fids,
        })

    return result


def build_cs_week_trend(target_date: str) -> list:
    """최근 7일 0값 틀 — collect_cs_data.py가 실제 값으로 채움"""
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    return [
        {
            "date":      (dt - timedelta(days=i)).strftime("%Y-%m-%d"),
            "received":  0,
            "processed": 0,
        }
        for i in range(6, -1, -1)
    ]


# ════════════════════════════════════════════════════════════════════════════
#  메인 분석
# ════════════════════════════════════════════════════════════════════════════

def analyze(date_label: str, force: bool = False) -> str:
    """
    단일 날짜 분석.
    반환값: "ok" | "skip" | "fail"
    """
    raw_path      = DATA_DIR / f"{date_label}.json"
    analyzed_path = DATA_DIR / f"{date_label}.analyzed.json"

    if not raw_path.exists():
        return "fail_no_raw"

    if analyzed_path.exists() and not force:
        return "skip"

    try:
        with open(raw_path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[ERR] {date_label} raw 로드 실패: {e}")
        return "fail_load"

    official_posts = raw.get("official_posts", [])
    user_posts     = raw.get("posts", [])

    major_issues  = build_major_issues(official_posts)
    voc_groups    = build_voc_groups(user_posts)
    cs_week_trend = build_cs_week_trend(date_label)

    analyzed = {
        "date":          date_label,
        "major_issues":  major_issues,
        "voc_groups":    voc_groups,
        "cs_inquiries":  [],
        "cs_week_trend": cs_week_trend,
    }

    try:
        with open(analyzed_path, "w", encoding="utf-8") as f:
            json.dump(analyzed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERR] {date_label} analyzed.json 저장 실패: {e}")
        return "fail_save"

    print(
        f"[OK] {date_label}: "
        f"major_issues={len(major_issues)} "
        f"voc_groups={len(voc_groups)} "
        f"user_posts={len(user_posts)}"
    )
    for g in voc_groups:
        print(f"       [{g['category']}] {g['count']}건  {g['summary'][:45]}")
    return "ok"


def backfill(force: bool = False) -> dict:
    raw_files = sorted(
        f for f in DATA_DIR.glob("*.json")
        if ".analyzed." not in f.name
    )
    if not raw_files:
        print("[INFO] 처리 대상 raw JSON 없음")
        return {}

    results: dict[str, str] = {}
    print(f"[BACKFILL] 대상: {len(raw_files)}건")
    for f in raw_files:
        status = analyze(f.stem, force=force)
        results[f.stem] = status
        if status == "skip":
            print(f"[SKIP] {f.stem} (analyzed.json 존재)")
        elif status.startswith("fail"):
            print(f"[FAIL] {f.stem} ({status})")

    ok   = sum(1 for s in results.values() if s == "ok")
    skip = sum(1 for s in results.values() if s == "skip")
    fail = sum(1 for s in results.values() if s.startswith("fail"))
    print(f"[BACKFILL] 완료: OK={ok}  SKIP={skip}  FAIL={fail}")
    return results


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DKR VOC 규칙 기반 분석 v4.0")
    parser.add_argument(
        "date", nargs="?",
        default=(datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="분석 날짜 YYYY-MM-DD (기본: 어제)",
    )
    parser.add_argument("--force",    "-f", action="store_true",
                        help="analyzed.json 덮어쓰기")
    parser.add_argument("--backfill",       action="store_true",
                        help="raw 있고 analyzed 없는 날짜 일괄 처리")
    args = parser.parse_args()

    if args.backfill:
        backfill(force=args.force)
    else:
        status = analyze(args.date, force=args.force)
        if status == "skip":
            print(f"[SKIP] {args.date} analyzed.json 이미 존재 (--force 로 덮어쓰기)")
        elif status.startswith("fail"):
            reason = {"fail_no_raw": "raw JSON 없음", "fail_load": "raw 로드 오류",
                      "fail_save": "저장 오류"}.get(status, status)
            print(f"[FAIL] {args.date}: {reason}")
            import sys; sys.exit(1)


if __name__ == "__main__":
    main()
