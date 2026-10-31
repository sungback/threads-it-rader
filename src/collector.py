"""Playwright 기반 Threads(스레드) 검색·수집 모듈.

두 가지 전략으로 최신 IT 글을 수집한다.
1) GraphQL 네트워크 인터셉트: 스레드 웹이 로딩 중 호출하는 API 응답 JSON에서
   게시물 구조를 직접 파싱 (가장 안정적).
2) DOM 텍스트 fallback: 인터셉트가 실패하면 화면에 렌더링된 게시물 DOM에서
   작성자/본문/링크를 긁는다.

GUI를 블로킹하지 않도록 수집은 QThread 워커(CollectWorker)에서 실행한다.
Playwright가 설치되어 있지 않으면 안내 오류를 돌려준다.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .filter import classify

# 앱 번들(frozen) 실행 시 PLAYWRIGHT_BROWSERS_PATH가 비어 있으면
# Playwright 드라이버가 읽기 전용 번들 내부 .local-browsers를 탐색하게 된다.
# 시스템별 사용자 캐시 경로를 기본값으로 세팅한다.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if sys.platform == "darwin":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser(
            "~/Library/Caches/ms-playwright"
        )
    elif sys.platform == "win32":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expandvars(
            r"%LOCALAPPDATA%\ms-playwright"
        )

THREADS_BASE = "https://www.threads.net"
SEARCH_URL = THREADS_BASE + "/search?q={query}&serp_type=default"
DEFAULT_QUERIES = ["개발", "프로그래밍", "AI", "코딩"]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class RawPost:
    """수집 원본 1건(정규화 전)."""

    post_id: str
    author: str = ""
    author_handle: str = ""
    content: str = ""
    url: str = ""
    posted_at: str = ""


@dataclass
class CollectedPost:
    """필터를 통과한 정규화된 게시물."""

    post_id: str
    author: str
    author_handle: str
    content: str
    url: str
    tag: str
    posted_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 파서: GraphQL 응답 JSON에서 게시물 후보 추출
# ---------------------------------------------------------------------------
_TEXT_KEYS = ("text", "caption")
_ID_KEYS = ("pk", "id", "code")


def _walk(node: Any) -> Any:
    """JSON 트리를 순회하는 제너레이터."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _extract_image_candidates(obj: dict[str, Any]) -> str:
    text = obj.get("text") or obj.get("caption") or ""
    return text if isinstance(text, str) else ""


def parse_graphql_payload(payload: Any) -> list[RawPost]:
    """스레드 GraphQL 응답 JSON에서 게시물 후보를 뽑아낸다(느슨한 파싱)."""
    found: dict[str, RawPost] = {}

    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        # 게시물 노드 힌트: text + code/pk 를 함께 갖는 dict
        text = node.get("text") if isinstance(node.get("text"), str) else None
        code = node.get("code") or node.get("pk") or node.get("id")
        if not text or not code:
            continue
        pid = str(code)
        if pid in found:
            continue

        # 작성자 후보: node 안의 user / caption 안의 user
        author, handle = "", ""
        user = node.get("user")
        if isinstance(user, dict):
            author = str(user.get("full_name") or user.get("username") or "")
            handle = str(user.get("username") or "")
        cap = node.get("caption")
        if isinstance(cap, dict) and isinstance(cap.get("user"), dict):
            u = cap["user"]
            author = author or str(u.get("full_name") or u.get("username") or "")
            handle = handle or str(u.get("username") or "")

        url = ""
        if node.get("code"):
            url = f"{THREADS_BASE}/@{handle or 'unknown'}/post/{node['code']}"
        taken = node.get("taken_at") or node.get("taken_at_timestamp") or ""
        posted_at = str(taken)

        found[pid] = RawPost(
            post_id=pid, author=author, author_handle=handle,
            content=text, url=url, posted_at=posted_at,
        )
    return list(found.values())


# ---------------------------------------------------------------------------
# 수집기
# ---------------------------------------------------------------------------
class ThreadsCollector:
    """Playwright로 스레드 검색 결과를 수집하는 헤드리스 수집기."""

    def __init__(
        self,
        queries: Optional[list[str]] = None,
        headless: bool = True,
        scroll_rounds: int = 2,
        status_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.queries = queries or list(DEFAULT_QUERIES)
        self.headless = headless
        self.scroll_rounds = scroll_rounds
        self.status_cb = status_cb

    # -- helpers --------------------------------------------------------
    def _status(self, msg: str) -> None:
        if self.status_cb:
            try:
                self.status_cb(msg)
            except Exception:
                pass

    @staticmethod
    def _get_browser_cache_path() -> str:
        """OS별 Playwright 브라우저 캐시 디렉터리 경로 반환."""
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Caches/ms-playwright")
        elif sys.platform == "win32":
            return os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright")
        return os.path.expanduser("~/.cache/ms-playwright")

    def _auto_install_browsers(self) -> None:
        """Playwright 드라이버를 통해 크로미움을 사용자 캐시 폴더에 자동 설치한다."""
        from playwright._impl._driver import compute_driver_executable, get_driver_env

        cache_dir = self._get_browser_cache_path()
        os.makedirs(cache_dir, exist_ok=True)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cache_dir

        driver_exec, driver_env = compute_driver_executable()
        driver_env["PLAYWRIGHT_BROWSERS_PATH"] = cache_dir

        self._status("크로미움 브라우저 다운로드 중... (최초 1회만 진행, 약 30초 소요)")
        res = subprocess.run(
            [driver_exec, "install", "chromium"],
            env=driver_env,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            res2 = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                env=driver_env,
                capture_output=True,
                text=True,
            )
            if res2.returncode != 0:
                raise RuntimeError(
                    f"크로미움 자동 다운로드 실패 (code={res.returncode}):\n{res.stderr or res.stdout}"
                )

    def _launch_browser(self, pw: Any) -> Any:
        """가능한 브라우저를 순서대로 시도해 실행한다.

        ① 시스템 Chrome (다운로드 불필요) ② 시스템 Edge ③ 사용자 캐시 내 크로미움.
        내장 크로미움도 없으면 백그라운드 자동 설치 후 재시도한다.
        """
        args = ["--disable-blink-features=AutomationControlled"]
        cache_dir = self._get_browser_cache_path()
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = cache_dir
        errors: list[str] = []

        for channel in ("chrome", "msedge"):
            try:
                self._status(f"시스템 브라우저({channel}) 감지 시도...")
                return pw.chromium.launch(headless=self.headless, channel=channel, args=args)
            except Exception as e:
                errors.append(f"channel={channel}: {e}")

        try:
            self._status("크로미움 브라우저 실행 중...")
            return pw.chromium.launch(headless=self.headless, args=args)
        except Exception as e:
            if self._is_missing_browser_error(e):
                self._status("초기 엔진이 없어 크로미움 자동 다운로드를 시작합니다...")
                self._auto_install_browsers()
                try:
                    return pw.chromium.launch(headless=self.headless, args=args)
                except Exception as e2:
                    errors.append(f"chromium(auto-installed): {e2}")
            else:
                errors.append(f"chromium: {e}")

        raise RuntimeError(
            "실행 가능한 브라우저를 찾지 못했습니다.\n"
            "Google Chrome을 설치하거나 네트워크 연결을 확인하세요.\n\n시도 로그:\n"
            + "\n".join(errors)
        )

    def collect(self) -> list[CollectedPost]:
        """전체 검색어에 대해 수집하고, IT 관련 글만 정규화해 반환한다."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright가 필요합니다: pip install playwright && playwright install chromium"
            ) from e

        captured: list[RawPost] = []

        with sync_playwright() as pw:
            browser = self._launch_browser(pw)
            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="ko-KR",
            )

            def on_response(resp: Any) -> None:
                try:
                    ctype = resp.headers.get("content-type", "")
                    if "json" not in ctype:
                        return
                    url = resp.url
                    if "/api/graphql" not in url and "graphql" not in url:
                        return
                    body = resp.text()
                    if not body or "text" not in body:
                        return
                    data = json.loads(body)
                    captured.extend(parse_graphql_payload(data))
                except Exception:
                    pass  # 외부 데이터 파싱 실패는 무시

            page = context.new_page()
            page.on("response", on_response)

            seen: dict[str, RawPost] = {}
            for q in self.queries:
                url = SEARCH_URL.format(query=_qenc(q))
                self._status(f"스레드 검색 중: {q}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(3_500)
                except Exception:
                    self._status(f"검색 페이지 로드 실패: {q}")
                    continue

                # 스크롤을 내려 더 로드
                for i in range(self.scroll_rounds):
                    page.mouse.wheel(0, 4_000)
                    page.wait_for_timeout(1_800 + random.randint(0, 900))
                    self._status(f"스크롤 {i + 1}/{self.scroll_rounds} ({q})")

                # 2) DOM fallback: 아직 후보가 부족하면 화면에서 직접 파싱
                dom_posts = self._parse_dom(page)
                for p in dom_posts:
                    seen.setdefault(p.post_id, p)

            # 네트워크 인터셉트 결과 우선
            for p in captured:
                seen.setdefault(p.post_id, p)

            browser.close()

        return self._normalize(list(seen.values()))

    # -- DOM fallback ---------------------------------------------------
    def _parse_dom(self, page: Any) -> list[RawPost]:
        """화면에 렌더링된 게시물 DOM에서 텍스트/작성자/링크를 추출한다."""
        out: list[RawPost] = []
        try:
            articles = page.query_selector_all("div[role='article'], article")
        except Exception:
            return out
        for art in articles:
            try:
                link_el = art.query_selector("a[href*='/post/']")
                href = link_el.get_attribute("href") if link_el else None
                text_el = art.query_selector("div[data-pressable-container=true] span")
                # 본문: 가장 긴 텍스트 덩어리 수집
                spans = art.query_selector_all("span")
                best = ""
                for s in spans:
                    t = (s.inner_text() or "").strip()
                    if len(t) > len(best) and t not in ("•", "·"):
                        best = t
                author = ""
                handle = ""
                a_els = art.query_selector_all("a[href^='/@']")
                if a_els:
                    href0 = a_els[0].get_attribute("href") or ""
                    handle = href0.split("/@")[-1].split("/")[0]
                    author = (a_els[0].inner_text() or "").strip().lstrip("@")
                if not best or len(best) < 20:
                    continue
                url = THREADS_BASE + href if href and href.startswith("/") else (href or "")
                code = ""
                m = re.search(r"/post/([^/?]+)", url or "")
                if m:
                    code = m.group(1)
                else:
                    code = uuid.uuid4().hex[:16]  # 링크 없으면 임시 id
                out.append(
                    RawPost(
                        post_id=code,
                        author=author,
                        author_handle=handle,
                        content=best,
                        url=url,
                    )
                )
            except Exception:
                continue
        return out

    # -- 정규화 + 필터 ----------------------------------------------------
    def _normalize(self, raws: list[RawPost]) -> list[CollectedPost]:
        results: list[CollectedPost] = []
        seen_ids: set[str] = set()
        for r in raws:
            if not r.post_id or r.post_id in seen_ids:
                continue
            seen_ids.add(r.post_id)
            text = re.sub(r"\s+", " ", (r.content or "")).strip()
            if len(text) < 15:  # 노이즈 제거
                continue
            cls = classify(text)
            if not cls.is_it:
                continue
            results.append(
                CollectedPost(
                    post_id=r.post_id,
                    author=r.author or r.author_handle or "알 수 없음",
                    author_handle=r.author_handle,
                    content=text[:500],
                    url=r.url,
                    tag=cls.tag,
                    posted_at=r.posted_at,
                    raw={"text": text},
                )
            )
        return results


def _qenc(q: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(q)


# ---------------------------------------------------------------------------
# QThread 워커 (GUI와 연결)
# ---------------------------------------------------------------------------
def build_worker_class():
    """PyQt6가 있으면 QThread 기반 워커를, 없으면 None을 반환한다."""
    try:
        from PyQt6.QtCore import QThread, pyqtSignal  # noqa
    except ImportError:  # pragma: no cover
        return None

    class CollectWorker(QThread):  # type: ignore[misc]
        """백그라운드에서 수집을 돌리고 결과를 시그널로 내보낸다."""

        posts_ready = pyqtSignal(list, int)   # CollectedPost 리스트, 신규 저장 개수
        progress = pyqtSignal(str)            # 상태 메시지
        failed = pyqtSignal(str)              # 오류 메시지

        def __init__(self, db, queries=None, headless=True, parent=None) -> None:
            super().__init__(parent)
            self._db = db
            self._queries = queries
            self._headless = headless

        def run(self) -> None:
            try:
                collector = ThreadsCollector(
                    queries=self._queries,
                    headless=self._headless,
                    status_cb=lambda m: self.progress.emit(m),
                )
                posts = collector.collect()
                if self._db is not None:
                    added = self._db.add_posts(
                        [
                            {
                                "post_id": p.post_id,
                                "author": p.author,
                                "author_handle": p.author_handle,
                                "content": p.content,
                                "url": p.url,
                                "tag": p.tag,
                                "posted_at": p.posted_at,
                            }
                            for p in posts
                        ]
                    )
                else:
                    added = len(posts)
                self.posts_ready.emit(posts, added)
            except Exception as e:  # pragma: no cover
                self.failed.emit(str(e))

    return CollectWorker


CollectWorker = build_worker_class()
