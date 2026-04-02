#!/usr/bin/env python3
"""
DKR (DK모바일:리본) 네이버 라운지 VOC 크롤러 v2.0
- 수집 방식: 순수 API (Playwright 불필요)
  · 게시물 목록: comm-api.game.naver.com/nng_main/v1/community/lounge/{lounge}/feed
  · 댓글: apis.naver.com/nng_main/nng_comment_api/v1/...
- 수집 범위: 기준 시각 기준 전날 09:00 ~ 당일 08:59 (24시간)
- 대상 게시판: 자유/건의/버그제보/질문답변
- 출력: data/DKR/YYYY-MM-DD.json
"""

import json
import re
import sys
import time
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "DKR"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOUNGE = "DK_Mobile_REBORN"

# VOC 수집 대상 게시판 (boardId: 이름)
VOC_BOARDS = {
    4:  "자유 게시판",
    9:  "건의 게시판",
    7:  "버그 제보",
    5:  "질문과 답변",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://game.naver.com/",
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

FEED_LIST_URL = "https://comm-api.game.naver.com/nng_main/v1/community/lounge/{lounge}/feed"
COMMENT_URL   = "https://apis.naver.com/nng_main/nng_comment_api/v1/type/FEED/id/{feedId}/comments"
REPLY_URL     = "https://apis.naver.com/nng_main/nng_comment_api/v1/type/FEED/id/{feedId}/comments/{commentId}/replyComments"


# ─── 유틸 ───────────────────────────────────────────────

def parse_date(date_str: str) -> datetime | None:
    """'YYYYMMDDHHMMSS' → datetime(KST)"""
    try:
        return datetime.strptime(date_str, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except Exception:
        return None


def extract_text_from_contents(contents_json: str) -> str:
    """네이버 스마트에디터 JSON에서 텍스트 추출"""
    if not contents_json:
        return ""
    try:
        data = json.loads(contents_json) if isinstance(contents_json, str) else contents_json
        texts = []
        # 재귀적으로 'value' 문자열 추출
        def walk(obj):
            if isinstance(obj, str):
                texts.append(obj)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("value", "text", "data"):
                        walk(v)
                    elif isinstance(v, (dict, list)):
                        walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)
        walk(data)
        return " ".join(t.strip() for t in texts if t.strip())[:2000]
    except Exception:
        return str(contents_json)[:500]


# ─── 게시물 수집 ─────────────────────────────────────────

def fetch_board_posts(
    board_id: int,
    board_name: str,
    window_start: datetime,
    window_end: datetime,
    max_per_board: int = 500,
) -> list[dict]:
    """특정 게시판의 게시물을 시간 범위 내에서 수집"""
    posts = []
    offset = 0
    limit = 30
    stop = False

    while not stop:
        url = FEED_LIST_URL.format(lounge=LOUNGE)
        params = {
            "boardId": board_id,
            "limit": limit,
            "offset": offset,
        }
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code != 200:
                print(f"  [WARN] boardId={board_id} HTTP {r.status_code}")
                break

            data = r.json()
            feeds = data.get("content", {}).get("feeds", [])
            if not feeds:
                break

            for item in feeds:
                feed   = item.get("feed", {})
                user   = item.get("user", {})
                comment = item.get("comment", {})

                created_str = feed.get("createdDate", "")
                post_dt = parse_date(created_str)

                # 범위 초과(너무 오래된 것) → 중단
                if post_dt and post_dt < window_start:
                    stop = True
                    break

                # 범위 미달(너무 최신) → 스킵
                if post_dt and post_dt > window_end:
                    continue

                feed_id = str(feed.get("feedId", ""))
                title   = feed.get("title", "").strip()
                body    = extract_text_from_contents(feed.get("contents", ""))

                posts.append({
                    "feed_id":       feed_id,
                    "board_id":      board_id,
                    "board_name":    board_name,
                    "title":         title,
                    "body":          body,
                    "author":        user.get("nickname", "Unknown"),
                    "author_level":  user.get("level", 0),
                    "created_at":    post_dt.isoformat() if post_dt else created_str,
                    "view_count":    item.get("readCount", 0),
                    "comment_count": comment.get("totalCount", 0),
                    "like_count":    feed.get("buff", 0),
                    "url": f"https://game.naver.com/lounge/{LOUNGE}/board/detail/{feed_id}",
                    "comments": [],
                })

                if len(posts) >= max_per_board:
                    stop = True
                    break

            offset += limit
            time.sleep(0.4)

        except Exception as e:
            print(f"  [ERR] 게시물 수집 오류 (boardId={board_id}): {e}")
            break

    return posts


# ─── 댓글 수집 ───────────────────────────────────────────

def fetch_comments(feed_id: str, max_comments: int = 200) -> list[dict]:
    """댓글 + 대댓글 수집"""
    comments = []
    offset = 0
    limit  = 30

    while len(comments) < max_comments:
        url = COMMENT_URL.format(feedId=feed_id)
        params = {
            "originalLoungeId": LOUNGE,
            "limit": limit,
            "offset": offset,
            "orderType": "ASC",
            "pagingType": "PAGE",
        }
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=10)
            if r.status_code != 200:
                break

            items = r.json().get("content", {}).get("comments", {}).get("data", [])
            if not items:
                break

            for item in items:
                c = item.get("comment", {})
                u = item.get("user", {})

                comment = {
                    "comment_id": str(c.get("commentId", "")),
                    "parent_id":  str(c.get("parentCommentId", 0)),
                    "depth":      2 if c.get("parentCommentId") else 1,
                    "author":     u.get("userNickname", "Unknown"),
                    "text":       c.get("content", "").strip(),
                    "created_at": c.get("createTime", ""),
                    "likes":      c.get("sympathyCount", 0),
                    "reply_count": c.get("replyCount", 0),
                }
                comments.append(comment)

                # 대댓글 수집
                if comment["reply_count"] > 0:
                    reply_url = REPLY_URL.format(
                        feedId=feed_id,
                        commentId=comment["comment_id"],
                    )
                    rp = {
                        "originalLoungeId": LOUNGE,
                        "offset": 0,
                    }
                    try:
                        r2 = requests.get(reply_url, headers=HEADERS, params=rp, timeout=10)
                        if r2.status_code == 200:
                            replies = r2.json().get("content", {}).get("comments", {}).get("data", [])
                            for ri in replies:
                                rc = ri.get("comment", {})
                                ru = ri.get("user", {})
                                comments.append({
                                    "comment_id": str(rc.get("commentId", "")),
                                    "parent_id":  comment["comment_id"],
                                    "depth":      2,
                                    "author":     ru.get("userNickname", "Unknown"),
                                    "text":       rc.get("content", "").strip(),
                                    "created_at": rc.get("createTime", ""),
                                    "likes":      rc.get("sympathyCount", 0),
                                    "reply_count": 0,
                                })
                    except Exception:
                        pass
                    time.sleep(0.2)

            offset += limit
            if len(items) < limit:
                break
            time.sleep(0.3)

        except Exception as e:
            print(f"  [WARN] 댓글 API 오류 (feedId={feed_id}): {e}")
            break

    return comments


# ─── 메인 ────────────────────────────────────────────────

def get_time_window(run_dt: datetime = None):
    if run_dt is None:
        run_dt = datetime.now(KST)
    today_9am  = run_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    window_end = today_9am
    window_start = window_end - timedelta(hours=24)
    return window_start, window_end


def run_crawl(date_label: str = None, dry_run: bool = False):
    now_kst = datetime.now(KST)
    window_start, window_end = get_time_window(now_kst)

    if date_label is None:
        date_label = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")

    output_file = DATA_DIR / f"{date_label}.json"
    print(f"[INFO] ========== DKR VOC 크롤링 시작 ==========")
    print(f"[INFO] 기준일: {date_label}")
    print(f"[INFO] 수집 범위: {window_start.strftime('%m/%d %H:%M')} ~ {window_end.strftime('%m/%d %H:%M')} KST")
    print(f"[INFO] 대상 게시판: {list(VOC_BOARDS.values())}")

    all_posts = []

    for board_id, board_name in VOC_BOARDS.items():
        print(f"\n[INFO] [{board_name}] 수집 중...")
        posts = fetch_board_posts(board_id, board_name, window_start, window_end)
        print(f"  → {len(posts)}건 수집")

        if not dry_run:
            for i, post in enumerate(posts, 1):
                if post["comment_count"] > 0:
                    post["comments"] = fetch_comments(post["feed_id"])
                    if i % 10 == 0:
                        print(f"  댓글 수집 진행중: {i}/{len(posts)}")
                    time.sleep(0.5)

        all_posts.extend(posts)

    # 결과 저장
    result = {
        "meta": {
            "date": date_label,
            "lounge": LOUNGE,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "crawled_at": now_kst.isoformat(),
            "total_posts": len(all_posts),
            "total_comments": sum(len(p.get("comments", [])) for p in all_posts),
            "boards": {
                str(bid): {
                    "name": bname,
                    "count": sum(1 for p in all_posts if p["board_id"] == bid),
                }
                for bid, bname in VOC_BOARDS.items()
            },
        },
        "posts": all_posts,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    m = result["meta"]
    print(f"\n[DONE] ========== 완료 ==========")
    print(f"  저장: {output_file}")
    print(f"  게시물: {m['total_posts']}건 / 댓글: {m['total_comments']}건")
    for bid, info in m["boards"].items():
        print(f"  - {info['name']}: {info['count']}건")

    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DKR 네이버 라운지 VOC 크롤러 v2.0")
    parser.add_argument("--date", help="수집 기준일 YYYY-MM-DD (미입력 시 어제)")
    parser.add_argument("--dry-run", action="store_true", help="댓글 제외 (빠른 테스트용)")
    args = parser.parse_args()
    run_crawl(date_label=args.date, dry_run=args.dry_run)
