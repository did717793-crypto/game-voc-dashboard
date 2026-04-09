#!/usr/bin/env python3
"""
analyze_voc.py — DKR 커뮤니티 VOC 규칙 기반 분석기 v3.0
────────────────────────────────────────────────────────
입력:  data/DKR/YYYY-MM-DD.json       (crawl_dkr.py 출력)
출력:  data/DKR/YYYY-MM-DD.analyzed.json

생성 필드:
  1. major_issues   — official_posts (공지/업데이트) 원문 그대로
  2. voc_groups     — user posts 규칙 기반 카테고리 분류 + 그룹핑
  3. cs_inquiries   — [] (CS 자동화 2차에서 구현)
  4. cs_week_trend  — 최근 7일 0값 기본 틀 (collect_cs_data.py가 채움)

분류 우선순위 (board_id=4 자유 게시판):
  COMPLAINT_KEYWORDS → 기타
  BUG_KEYWORDS       → 버그·오류
  SUGGEST_KEYWORDS   → 건의·요청
  default            → 게임 관련

사용법:
  python3 analyze_voc.py                        # 어제 날짜 자동
  python3 analyze_voc.py 2026-04-06             # 특정 날짜
  python3 analyze_voc.py 2026-04-06 --force     # analyzed.json 덮어쓰기
  python3 analyze_voc.py --backfill             # raw 있고 analyzed 없는 날짜 일괄 처리
  python3 analyze_voc.py --backfill --force     # 모든 raw 날짜 재분석
"""

import json
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST        = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data" / "DKR"

# ════════════════════════════════════════════════════════════════════════════
#  분류 상수 — 키워드 추가·수정은 여기만 건드리면 됩니다
# ════════════════════════════════════════════════════════════════════════════

# board_id → 카테고리 직접 매핑 (None = 키워드로 재분류)
BOARD_CATEGORY_MAP: dict[int, str | None] = {
    4: None,           # 자유 게시판   → 키워드 판별
    5: "게임 관련",     # 질문과 답변
    7: "버그·오류",     # 버그 제보
    9: "건의·요청",     # 건의 게시판
}

# 공식 게시판 IDs (major_issues 수집 대상)
OFFICIAL_BOARD_IDS: set[int] = {11, 13}

# ── 자유 게시판 키워드 (우선순위: COMPLAINT > BUG > SUGGEST > default) ────

COMPLAINT_KEYWORDS: list[str] = [
    # 서비스 종료 우려
    "섭종", "서비스종료", "서비스 종료", "폐서비스", "폐겜",
    # 게임 비판
    "망겜", "탈주", "탈게", "쫄딱", "현질",
    # 감정적 불만 표현
    "지못미", "버리는", "버려",
]

BUG_KEYWORDS: list[str] = [
    # 직접적 버그/오류
    "버그", "오류", "에러", "error",
    # 기능 이상
    "안됨", "안돼", "안 돼", "안 됨", "먹통", "오작동", "작동",
    # 접속 문제
    "팅", "튕", "렉", "렉걸", "멈춤", "멈춰",
    "접속불가", "접속 불가", "로그인 안", "로그인안", "로딩",
    # 앱 충돌
    "크래시", "crash", "뻗어", "죽어",
]

SUGGEST_KEYWORDS: list[str] = [
    # 직접적 건의·요청
    "건의", "요청", "제안",
    # 정중한 표현
    "해주세요", "해주셨으면", "부탁", "해줘", "해줬으면",
    # 추가·개선 요청
    "추가해", "추가 해", "넣어줘", "개선",
    "바꿔", "바꿔주", "변경해", "변경 해", "고쳐줘", "수정해",
    # 희망 표현
    "이렇게 하면", "이렇게하면",
    "있으면 좋겠", "있으면좋겠",
    "필요한것같", "필요할것같",
    "했으면", "했으면 좋겠",
]

# 카테고리 출력 순서
CATEGORY_ORDER: list[str] = ["버그·오류", "건의·요청", "게임 관련", "기타"]


# ════════════════════════════════════════════════════════════════════════════
#  분류 로직
# ════════════════════════════════════════════════════════════════════════════

def classify_post(post: dict) -> str:
    """단일 포스트 → 카테고리 문자열"""
    board_id = post.get("board_id")
    cat = BOARD_CATEGORY_MAP.get(board_id)
    if cat is not None:
        return cat

    # board_id=4 (자유 게시판) — 본문+제목 키워드 판별
    text = f"{post.get('title', '')} {post.get('body', '')}".lower()

    for kw in COMPLAINT_KEYWORDS:
        if kw in text:
            return "기타"
    for kw in BUG_KEYWORDS:
        if kw in text:
            return "버그·오류"
    for kw in SUGGEST_KEYWORDS:
        if kw in text:
            return "건의·요청"

    return "게임 관련"


# ════════════════════════════════════════════════════════════════════════════
#  필드 생성
# ════════════════════════════════════════════════════════════════════════════

def build_major_issues(official_posts: list) -> list:
    """공식 게시판 포스트 → major_issues"""
    result = []
    for p in official_posts:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        result.append({
            "title":   title,
            "board":   p.get("board_name", ""),
            "url":     p.get("url", ""),
            "feed_id": str(p.get("feed_id", "")),
            "date":    (p.get("created_at") or "")[:10],
        })
    return result


def build_voc_groups(user_posts: list) -> list:
    """유저 포스트 → 카테고리별 그룹핑 → voc_groups"""
    groups: dict[str, list] = defaultdict(list)
    for p in user_posts:
        cat = classify_post(p)
        groups[cat].append(p)

    result = []
    for cat in CATEGORY_ORDER:
        posts = groups.get(cat, [])
        if not posts:
            continue

        # 대표글: 댓글×2 + 좋아요 가중치 최고
        top = max(
            posts,
            key=lambda p: p.get("comment_count", 0) * 2 + p.get("like_count", 0)
        )
        result.append({
            "category":           cat,
            "summary":            (top.get("title") or "")[:80],
            "count":              len(posts),
            "representative_url": top.get("url", ""),
            "feed_ids":           [str(p.get("feed_id", "")) for p in posts],
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

def analyze(date_label: str, force: bool = False) -> bool:
    """
    단일 날짜 analyzed.json 생성.
    반환값: True(생성/스킵 성공) / False(raw 없음 등 실패)
    """
    raw_path      = DATA_DIR / f"{date_label}.json"
    analyzed_path = DATA_DIR / f"{date_label}.analyzed.json"

    if not raw_path.exists():
        print(f"[SKIP] raw 없음: {raw_path.name}")
        return False

    if analyzed_path.exists() and not force:
        print(f"[SKIP] analyzed 존재: {analyzed_path.name}")
        return True

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

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

    with open(analyzed_path, "w", encoding="utf-8") as f:
        json.dump(analyzed, f, ensure_ascii=False, indent=2)

    print(f"[OK] {analyzed_path.name} 생성")
    print(f"     공식 이슈: {len(major_issues)}건 | VOC 그룹: {len(voc_groups)}개 | 유저 포스트: {len(user_posts)}건")
    for g in voc_groups:
        print(f"       [{g['category']}] {g['count']}건  {g['summary'][:45]}")
    return True


def backfill(force: bool = False) -> tuple[int, int]:
    """raw 있고 analyzed 없는(또는 force) 날짜 일괄 처리"""
    raw_files = sorted(
        f for f in DATA_DIR.glob("*.json")
        if ".analyzed." not in f.name
    )
    if not raw_files:
        print("[INFO] 처리 대상 raw JSON 없음")
        return 0, 0

    total = len(raw_files)
    ok    = 0
    print(f"[BACKFILL] 대상: {total}건")
    for f in raw_files:
        if analyze(f.stem, force=force):
            ok += 1
    print(f"[BACKFILL] 완료: {ok}/{total}")
    return ok, total


# ════════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="DKR VOC 규칙 기반 분석 v3.0")
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
        ok = analyze(args.date, force=args.force)
        if not ok:
            import sys; sys.exit(1)


if __name__ == "__main__":
    main()
