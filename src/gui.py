"""PyQt6 기반 모던 데스크톱 UI.

- QSystemTrayIcon 트레이 상주(열기 / 지금 수집 / 종료) + 새 글 데스크톱 알림
- 카드형 피드 뷰어: 검색창, 카테고리 필터 버튼, [원문 보기], 북마크
"""

from __future__ import annotations

import webbrowser
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .collector import CollectWorker
from .database import Database
from .filter import CATEGORIES

APP_NAME = "Threads IT 레이더"

ACCENT = "#1d9bf0"          # Threads 블루
BG = "#f5f7fa"
CARD_BG = "#ffffff"
TEXT = "#111827"
SUBTLE = "#6b7280"


def _paint_badge(color: str) -> QIcon:
    """트레이용 간단한 레이더 아이콘(원 + 점)을 생성한다."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(color))
    p.setBrush(QColor(color))
    p.drawEllipse(8, 8, 48, 48)
    p.setBrush(QColor("white"))
    p.drawEllipse(24, 24, 16, 16)
    p.end()
    return QIcon(pm)


class PostCard(QFrame):
    """피드의 게시물 카드 한 장."""

    def __init__(self, post: dict[str, Any], db: Database, on_changed: Any) -> None:
        super().__init__()
        self.post = post
        self.db = db
        self.on_changed = on_changed

        self.setObjectName("postCard")
        self.setStyleSheet(
            f"""
            QFrame#postCard {{
                background: {CARD_BG};
                border: 1px solid #e5e7eb;
                border-radius: 14px;
            }}
            QFrame#postCard:hover {{ border: 1px solid {ACCENT}; }}
            QLabel[aria-role="author"] {{
                color: {TEXT}; font-weight: 700; font-size: 14px; background: transparent;
                border: none;
            }}
            QLabel[aria-role="body"] {{
                color: {TEXT}; font-size: 13px; background: transparent; border: none;
            }}
            QLabel[aria-role="meta"] {{
                color: {SUBTLE}; font-size: 11px; background: transparent; border: none;
            }}
            QPushButton {{
                border: none; border-radius: 8px; padding: 6px 12px;
                font-size: 12px; font-weight: 600;
            }}
            QPushButton#openBtn {{ background: {ACCENT}; color: white; }}
            QPushButton#markBtn {{ background: #eef2f7; color: {TEXT}; }}
            QPushButton#markBtn:checked {{ background: #fde68a; }}
            """
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        author = f"{post.get('author') or '알 수 없음'}"
        if post.get("author_handle"):
            author += f" @{post['author_handle'].lstrip('@')}"

        head = QHBoxLayout()
        author_label = QLabel(author)
        author_label.setProperty("aria-role", "author")
        tag_label = QLabel(f"  #{post.get('tag', '기타')}")
        tag_label.setProperty("aria-role", "meta")
        tag_label.setStyleSheet(
            f"color:{ACCENT}; background:transparent; font-weight:700; border:none;"
        )
        new_label = QLabel("🆕 NEW") if post.get("is_new") else QLabel("")
        new_label.setProperty("aria-role", "meta")
        new_label.setStyleSheet("color:#dc2626; font-weight:800; border:none; background:transparent;")
        head.addWidget(author_label)
        head.addWidget(tag_label)
        head.addStretch(1)
        head.addWidget(new_label)
        layout.addLayout(head)

        body = QLabel(post.get("content", ""))
        body.setProperty("aria-role", "body")
        body.setWordWrap(True)
        layout.addWidget(body)

        foot = QHBoxLayout()
        open_btn = QPushButton("🔗 원문 보기")
        open_btn.setObjectName("openBtn")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_link)
        mark_btn = QPushButton("⭐ 북마크" if not post.get("bookmarked") else "⭐ 북마크됨")
        mark_btn.setObjectName("markBtn")
        mark_btn.setCheckable(True)
        mark_btn.setChecked(bool(post.get("bookmarked")))
        mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mark_btn.clicked.connect(self._toggle_bookmark)
        collected = QLabel(f"수집: {str(post.get('collected_at', ''))[:16]}")
        collected.setProperty("aria-role", "meta")
        foot.addWidget(open_btn)
        foot.addWidget(mark_btn)
        foot.addStretch(1)
        foot.addWidget(collected)
        layout.addLayout(foot)

    def _open_link(self) -> None:
        url = self.post.get("url") or ""
        if url.startswith("http"):
            webbrowser.open(url)

    def _toggle_bookmark(self) -> None:
        state = self.db.toggle_bookmark(self.post["post_id"])
        self.post["bookmarked"] = 1 if state else 0
        if self.on_changed:
            self.on_changed()


class MainWindow(QMainWindow):
    """메인 카드 피드 뷰어."""

    refresh_requested = pyqtSignal()

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.current_tag = "전체"
        self.worker: Optional[CollectWorker] = None

        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(560, 760)
        self.setStyleSheet(f"QMainWindow {{ background: {BG}; }}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        # ── 상단바: 타이틀 + 검색 ───────────────────────────
        title_row = QHBoxLayout()
        title = QLabel(f"🛰️ {APP_NAME}")
        f = QFont()
        f.setBold(True)
        f.setPointSize(14)
        title.setFont(f)
        title.setStyleSheet(f"color:{TEXT}; background:transparent; border:none;")
        self.count_label = QLabel("")
        self.count_label.setProperty("aria-role", "meta")
        self.count_label.setStyleSheet(
            f"color:{SUBTLE}; background:transparent; border:none;"
        )
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.count_label)
        root.addLayout(title_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 검색어 입력 후 Enter로 스레드 실시간 수집…")
        self.search_box.setFixedHeight(36)
        self.search_box.setStyleSheet(
            "QLineEdit { background:#fff; border:1px solid #e5e7eb; border-radius:10px;"
            " padding: 0 10px; font-size: 13px; }"
            f"QLineEdit:focus {{ border:1px solid {ACCENT}; }}"
        )
        self.search_box.textChanged.connect(self.reload)
        self.search_box.returnPressed.connect(self._on_search_submitted)
        search_row.addWidget(self.search_box, 1)

        self.search_btn = QPushButton("스레드 수집")
        self.search_btn.setFixedHeight(36)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.setStyleSheet(
            f"QPushButton {{ background:{ACCENT}; color:white; font-weight:bold; border-radius:10px;"
            " padding: 0 14px; font-size: 13px; border:none; }"
            "QPushButton:hover { opacity: 0.9; }"
        )
        self.search_btn.clicked.connect(self._on_search_submitted)
        search_row.addWidget(self.search_btn)
        root.addLayout(search_row)

        # ── 카테고리 필터 버튼 ─────────────────────────────
        cat_row = QHBoxLayout()
        cat_row.setSpacing(6)
        self.cat_buttons: dict[str, QPushButton] = {}
        for tag in ["전체"] + list(CATEGORIES.keys()) + ["북마크"]:
            btn = QPushButton(tag)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { border:1px solid #e5e7eb; border-radius: 12px;"
                " padding: 4px 12px; font-size: 12px; background:#fff; color:#374151; }"
                f"QPushButton:checked {{ background:{ACCENT}; color:white; border-color:{ACCENT}; }}"
            )
            btn.clicked.connect(lambda _=False, t=tag: self._select_tag(t))
            self.cat_buttons[tag] = btn
            cat_row.addWidget(btn)
        cat_row.addStretch(1)
        root.addLayout(cat_row)
        self.cat_buttons["전체"].setChecked(True)

        # ── 피드 (스크롤 영역) ─────────────────────────────
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.feed_holder = QWidget()
        self.feed_holder.setStyleSheet("background: transparent;")
        self.feed = QVBoxLayout(self.feed_holder)
        self.feed.setContentsMargins(0, 0, 6, 0)
        self.feed.setSpacing(10)
        self.feed.addStretch(1)
        self.scroll.setWidget(self.feed_holder)
        root.addWidget(self.scroll, 1)

        # ── 하단 상태바 ────────────────────────────────
        self.status = QLabel("준비됨")
        self.status.setProperty("aria-role", "meta")
        self.status.setStyleSheet(f"color:{SUBTLE}; background:transparent; border:none;")
        root.addWidget(self.status)

    # ------------------------------------------------------------------
    # 필터 / 로드
    # ------------------------------------------------------------------
    def _select_tag(self, tag: str) -> None:
        if self.current_tag == tag:
            return
        self.current_tag = tag
        for t, b in self.cat_buttons.items():
            b.setChecked(t == tag)
        self.reload()

    @pyqtSlot()
    def reload(self) -> None:
        bookmarked_only = self.current_tag == "북마크"
        tag = None if self.current_tag in ("전체", "북마크") else self.current_tag
        posts = self.db.get_posts(
            tag=tag,
            search=self.search_box.text(),
            bookmarked_only=bookmarked_only,
            limit=300,
        )
        self.count_label.setText(f"총 {self.db.count()}글 · 표시 {len(posts)}건")

        # 피드 다시 그리기
        while self.feed.count() > 1:
            item = self.feed.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not posts:
            empty = QLabel("아직 글이 없습니다. 트레이 메뉴의 '지금 수집'을 눌러 보세요.")
            empty.setStyleSheet(
                f"color:{SUBTLE}; background:transparent; border:none; font-size:13px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.feed.insertWidget(0, empty)
            return
        for i, p in enumerate(posts):
            self.feed.insertWidget(i, PostCard(p, self.db, self.reload))

    def show_new_posts_toast(self, added: int) -> None:
        self.status.setText(f"수집 완료 — 새 IT 글 {added}건 추가")

    # ------------------------------------------------------------------
    # 수집 워커
    # ------------------------------------------------------------------
    def _on_search_submitted(self) -> None:
        q = self.search_box.text().strip()
        queries = [q] if q else None
        self.start_collection(queries=queries)

    def start_collection(self, queries: Optional[list[str]] = None) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("이미 수집이 진행 중입니다…")
            return
        q_label = f"'{queries[0]}'" if queries else "기본 IT 키워드"
        self.status.setText(f"스레드에서 {q_label} 수집 중… (브라우저 기동)")
        worker = CollectWorker(self.db, queries=queries)
        self.worker = worker
        worker.progress.connect(self.status.setText)
        worker.failed.connect(self._on_collect_failed)
        worker.posts_ready.connect(self._on_collect_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_collect_done(self, posts: list, added: int) -> None:
        self.reload()
        tray = getattr(self, "tray", None)
        if added > 0 and tray is not None:
            top = posts[0] if posts else None
            title = f"{APP_NAME}: 새 IT 글 {added}건"
            msg = (top.content[:80] + "…") if top and len(top.content) > 80 else (
                top.content if top else "새로운 IT/개발 글이 도착했습니다."
            )
            tray.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 6_000)
        elif tray is not None and added == 0:
            tray.showMessage(
                APP_NAME, "새로운 IT 글이 없습니다.", QSystemTrayIcon.MessageIcon.Information, 3_000
            )
        self.status.setText(f"수집 완료 — 새 글 {added}건 (총 {self.db.count()}글)")

    def _on_collect_failed(self, msg: str) -> None:
        self.status.setText(f"수집 실패: {msg[:120]}")
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.showMessage(
                f"{APP_NAME}: 수집 실패",
                msg[:200],
                QSystemTrayIcon.MessageIcon.Warning,
                6_000,
            )
        QMessageBox.warning(self, "수집 실패", f"스레드 수집 중 오류가 발생했습니다:\n{msg}")


class TrayApp(QSystemTrayIcon):
    """트레이 아이콘 + 주기적 수집 타이머를 담당하는 앱 셸."""

    def __init__(self, window: MainWindow, interval_minutes: int = 30) -> None:
        self.window = window
        self.db = window.db
        icon = _paint_badge(ACCENT)
        window.setWindowIcon(icon)

        super().__init__(icon, window)
        self.setToolTip(APP_NAME)
        window.tray = self

        menu = QMenu()
        act_open = QAction("열기", menu)
        act_open.triggered.connect(self._open_window)
        act_collect = QAction("지금 수집", menu)
        act_collect.triggered.connect(self.collect_now)
        act_quit = QAction("종료", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_open)
        menu.addAction(act_collect)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

        # 주기 수집 타이머
        self.timer = QTimer()
        self.timer.setInterval(interval_minutes * 60 * 1_000)
        self.timer.timeout.connect(self.collect_now)
        self.timer.start()

        # 시작 3초 후 첫 수집
        QTimer.singleShot(3_000, self.collect_now)

    # ------------------------------------------------------------------
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_window()

    def _open_window(self) -> None:
        w = self.window
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def collect_now(self) -> None:
        self.window.start_collection()

    def _quit(self) -> None:
        self.timer.stop()
        self.hide()
        QApplication.quit()
