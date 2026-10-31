"""로컬 SQLite 데이터베이스 관리 모듈.

threads_posts 테이블로 수집한 스레드 글을 관리한다.
- post_id 고유 제약으로 중복 수집 방지
- 신규 글 삽입 (INSERT OR IGNORE)
- 목록 조회 (태그/검색어/북마크 필터)
- 북마크 토글
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Optional


class Database:
    """SQLite 기반 로컬 저장소. 모든 메서드는 스레드 안전하다."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            # 사용자 홈 디렉터리에 저장 (포터블 실행 파일에서도 동작)
            base = os.environ.get("THREADS_IT_RADAR_HOME")
            if not base:
                base = os.path.join(os.path.expanduser("~"), ".threads_it_radar")
            os.makedirs(base, exist_ok=True)
            db_path = os.path.join(base, "threads_it_radar.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    # ------------------------------------------------------------------
    # 스키마
    # ------------------------------------------------------------------
    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads_posts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id       TEXT    NOT NULL UNIQUE,
                    author        TEXT,
                    author_handle TEXT,
                    content       TEXT,
                    url           TEXT,
                    tag           TEXT    DEFAULT '기타',
                    bookmarked    INTEGER NOT NULL DEFAULT 0,
                    is_new        INTEGER NOT NULL DEFAULT 1,
                    collected_at  TEXT    NOT NULL,
                    posted_at     TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_posts_tag ON threads_posts (tag)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_posts_bookmark ON threads_posts (bookmarked)"
            )

    # ------------------------------------------------------------------
    # 쓰기
    # ------------------------------------------------------------------
    def add_post(
        self,
        post_id: str,
        author: str = "",
        author_handle: str = "",
        content: str = "",
        url: str = "",
        tag: str = "기타",
        posted_at: str = "",
    ) -> bool:
        """신규 글 삽입. 이미 저장된 post_id면 False를 반환한다(중복 방지)."""
        if not post_id:
            return False
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._conn:
                cur = self._conn.execute(
                    """
                    INSERT INTO threads_posts
                        (post_id, author, author_handle, content, url, tag,
                         bookmarked, is_new, collected_at, posted_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (post_id, author, author_handle, content, url, tag, now, posted_at),
                )
                return cur.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def add_posts(self, posts: list[dict[str, Any]]) -> int:
        """여러 글을 한 번에 저장하고, 실제로 새로 들어간 개수를 반환한다."""
        added = 0
        for p in posts:
            if self.add_post(
                post_id=str(p.get("post_id", "")),
                author=p.get("author", "") or "",
                author_handle=p.get("author_handle", "") or "",
                content=p.get("content", "") or "",
                url=p.get("url", "") or "",
                tag=p.get("tag", "기타") or "기타",
                posted_at=p.get("posted_at", "") or "",
            ):
                added += 1
        return added

    def toggle_bookmark(self, post_id: str) -> Optional[bool]:
        """북마크 토글. 토글 후 상태(True=북마크됨)를 반환, 글이 없으면 None."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT bookmarked FROM threads_posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            if row is None:
                return None
            new_val = 0 if row["bookmarked"] else 1
            self._conn.execute(
                "UPDATE threads_posts SET bookmarked = ? WHERE post_id = ?",
                (new_val, post_id),
            )
            return bool(new_val)

    def mark_seen(self, post_ids: list[str]) -> None:
        """읽음 처리(새 글 표시 해제)."""
        if not post_ids:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE threads_posts SET is_new = 0 WHERE post_id = ?",
                [(pid,) for pid in post_ids],
            )

    def clear_all(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM threads_posts")

    # ------------------------------------------------------------------
    # 읽기
    # ------------------------------------------------------------------
    def get_posts(
        self,
        tag: Optional[str] = None,
        search: str = "",
        bookmarked_only: bool = False,
        limit: int = 300,
    ) -> list[dict[str, Any]]:
        """조건에 맞는 글 목록을 최신 수집 순으로 반환한다."""
        where = ["1 = 1"]
        params: list[Any] = []
        if tag and tag != "전체":
            where.append("tag = ?")
            params.append(tag)
        if bookmarked_only:
            where.append("bookmarked = 1")
        if search.strip():
            where.append("(content LIKE ? OR author LIKE ? OR author_handle LIKE ?)")
            like = f"%{search.strip()}%"
            params.extend([like, like, like])
        query = (
            "SELECT * FROM threads_posts WHERE "
            + " AND ".join(where)
            + " ORDER BY bookmarked DESC, collected_at DESC, id DESC LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_new_post_ids(self, limit: int = 50) -> list[str]:
        """아직 읽지 않은 새 글의 post_id 목록."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT post_id FROM threads_posts WHERE is_new = 1 "
                "ORDER BY collected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [r["post_id"] for r in rows]

    def count(self, bookmarked_only: bool = False) -> int:
        with self._lock:
            q = "SELECT COUNT(*) AS c FROM threads_posts"
            if bookmarked_only:
                q += " WHERE bookmarked = 1"
            row = self._conn.execute(q).fetchone()
        return int(row["c"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
