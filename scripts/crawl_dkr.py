#!/usr/bin/env python3
"""
DKR (DK모바일:리본) 네이버 라운지 VOC 크롤러 v2.1
- 수집 방식: 순수 API (Playwright 불필요)
- 수집 범위: 전날 09:00 ~ 당일 08:59 (24시간)
- 대상 게시판:
    공식: 공지사항(11), 업데이트(13)
    유저: 자유(4), 건의(9), 버그제보(7), 질문답변(5)
"""

import json, re, sys, time, argparse, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data" / "DKR"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOUNGE = "DK_Mobile_REBORN"

# 공식 게시판 (주요 이슈용)
OFFICIAL_BOARDS = {
    11: "공지사항",
    13: "업데이트",
}

# 유저 VOC 게시판
VOC_BOARDS = {
    4:  "자유 게시판",
    9:  "건의 게시판",
    7:  "버그 제보",
    5:  "질문과 답변",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://game.naver.com/",
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

FEED_LIST_URL = "https://comm-api.game.naver.com/nng_main/v1/community/lounge/{lounge}/feed"
COMMENT_URL   = "https://apis.naver.com/nng_main/nng_comment_api/v1/type/FEED/id/{feedId}/comments"
REPLY_URL     = "https://apis.naver.com/nng_main/nng_comment_api/v1/type/FEED/id/{feedId}/comments/{commentId}/replyComments"


def parse_date(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except Exception:
        return None


def extract_text(contents_json: str) -> str:
    if not contents_json:
        return ""
    try:
        data = json.loads(contents_json) if isinstance(contents_json, str) else contents_json
        texts = []
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


def fetch_posts(board_id: int, board_name: str,
                window_start: datetime, window_end: datetime,
                max_posts: int = 500) -> list[dict]:
    posts = []
    offset, limit, stop = 0, 30, False
    while not stop:
        try:
            r = requests.get(
                FEED_LIST_URL.format(lounge=LOUNGE),
                headers=HEADERS,
                params={"boardId": board_id, "limit": limit, "offset": offset},
                timeout=15,
            )
            if r.status_code != 200:
                break
            feeds = r.json().get("content", {}).get("feeds", [])
            if not feeds:
                break
            for item in feeds:
                feed    = item.get("feed", {})
                user    = item.get("user", {})
                comment = item.get("comment", {})
                post_dt = parse_date(feed.get("createdDate", ""))
                if post_dt and post_dt < window_start:
                    stop = True
                    break
                if post_dt and post_dt > window_end:
                    continue
                feed_id = str(feed.get("feedId", ""))
                posts.append({
                    "feed_id":       feed_id,
                    "board_id":      board_id,
                    "board_name":    board_name,
                    "title":         feed.get("title", "").strip(),
                    "body":          extract_text(feed.get("contents", "")),
                    "author":        user.get("nickname", "Unknown"),
                    "created_at":    post_dt.isoformat() if post_dt else feed.get("createdDate",""),
                    "view_count":    item.get("readCount", 0),
                    "comment_count": comment.get("totalCount", 0),
                    "like_count":    feed.get("buff", 0),
                    "url": f"https://game.naver.com/lounge/{LOUNGE}/board/detail/{feed_id}",
                    "comments": [],
                })
                if len(posts) >= max_posts:
                    stop = True
                    break
            offset += limit
            time.sleep(0.4)
        except Exception as e:
            print(f"  [ERR] boardId={board_id}: {e}")
            break
    return posts


def fetch_comments(feed_id: str, max_comments: int = 200) -> list[dict]:
    comments, offset, limit = [], 0, 30
    while len(comments) < max_comments:
        try:
            r = requests.get(
                COMMENT_URL.format(feedId=feed_id),
                headers=HEADERS,
                params={"originalLoungeId": LOUNGE, "limit": limit, "offset": offset,
                        "orderType": "ASC", "pagingType": "PAGE"},
                timeout=10,
            )
            if r.status_code != 200:
                break
            items = r.json().get("content", {}).get("comments", {}).get("data", [])
            if not items:
                break
            for item in items:
                c, u = item.get("comment", {}), item.get("user", {})
                comment = {
                    "comment_id":  str(c.get("commentId", "")),
                    "parent_id":   str(c.get("parentCommentId", 0)),
                    "depth":       2 if c.get("parentCommentId") else 1,
                    "author":      u.get("userNickname", "Unknown"),
                    "text":        c.get("content", "").strip(),
                    "created_at":  c.get("createTime", ""),
                    "likes":       c.get("sympathyCount", 0),
                    "reply_count": c.get("replyCount", 0),
                }
                comments.append(comment)
                if comment["reply_count"] > 0:
                    try:
                        r2 = requests.get(
                            REPLY_URL.format(feedId=feed_id, commentId=comment["comment_id"]),
                            headers=HEADERS,
                            params={"originalLoungeId": LOUNGE, "offset": 0},
                            timeout=10,
                        )
                        if r2.status_code == 200:
                            for ri in r2.json().get("content", {}).get("comments", {}).get("data", []):
                                rc, ru = ri.get("comment", {}), ri.get("user", {})
                                comments.append({
                                    "comment_id": str(rc.get("commentId","")),
                                    "parent_id":  comment["comment_id"],
                                    "depth": 2,
                                    "author": ru.get("userNickname","Unknown"),
                                    "text": rc.get("content","").strip(),
                                    "created_at": rc.get("createTime",""),
                                    "likes": rc.get("sympathyCount",0),
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
            print(f"  [WARN] 댓글 오류 feedId={feed_id}: {e}")
            break
    return comments


def get_time_window(run_dt=None):
    if run_dt is None:
        run_dt = datetime.now(KST)
    today_9am = run_dt.replace(hour=9, minute=0, second=0, microsecond=0)
    return today_9am - timedelta(hours=24), today_9am


def run_crawl(date_label=None, dry_run=False):
    now_kst = datetime.now(KST)
    window_start, window_end = get_time_window(now_kst)
    if date_label is None:
        date_label = (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")

    output_file = DATA_DIR / f"{date_label}.json"
    print(f"[INFO] DKR VOC 크롤링 시작: {date_label}")
    print(f"[INFO] 범위: {window_start.strftime('%m/%d %H:%M')} ~ {window_end.strftime('%m/%d %H:%M')} KST")

    official_posts, user_posts = [], []

    # 공식 게시판 (주요 이슈)
    for bid, bname in OFFICIAL_BOARDS.items():
        print(f"\n[공식] [{bname}] 수집...")
        posts = fetch_posts(bid, bname, window_start, window_end, max_posts=20)
        print(f"  → {len(posts)}건")
        official_posts.extend(posts)

    # 유저 VOC 게시판
    for bid, bname in VOC_BOARDS.items():
        print(f"\n[유저] [{bname}] 수집...")
        posts = fetch_posts(bid, bname, window_start, window_end)
        print(f"  → {len(posts)}건")
        if not dry_run:
            for i, p in enumerate(posts, 1):
                if p["comment_count"] > 0:
                    p["comments"] = fetch_comments(p["feed_id"])
                    if i % 10 == 0:
                        print(f"  댓글 수집: {i}/{len(posts)}")
                    time.sleep(0.5)
        user_posts.extend(posts)

    all_posts = official_posts + user_posts
    result = {
        "meta": {
            "date": date_label,
            "lounge": LOUNGE,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "crawled_at": now_kst.isoformat(),
            "total_posts": len(all_posts),
            "total_comments": sum(len(p.get("comments",[])) for p in all_posts),
            "boards": {
                str(bid): {"name": bname, "count": sum(1 for p in all_posts if p["board_id"]==bid)}
                for bid, bname in {**OFFICIAL_BOARDS, **VOC_BOARDS}.items()
            },
        },
        "official_posts": official_posts,
        "posts": user_posts,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    m = result["meta"]
    print(f"\n[DONE] 저장: {output_file}")
    print(f"  공식 {len(official_posts)}건 / 유저 {len(user_posts)}건 / 댓글 {m['total_comments']}건")
    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_crawl(date_label=args.date, dry_run=args.dry_run)
