"""Threads IT 레이더 실행 진입점.

트레이 아이콘을 만들고, 주기적 수집 타이머를 가동하며, 뷰어 창을 연결한다.
"""

from __future__ import annotations

import os
import sys

# PyInstaller로 빌드했을 때 src 패키지를 찾을 수 있도록 경로 보정
if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if _base not in sys.path:
        sys.path.insert(0, _base)

# Playwright 브라우저 경로 보정: 앱 번들 내부(읽기 전용) 대신
# 사용자별 캐시 디렉터리의 브라우저를 사용하도록 기본값을 세팅한다.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    if sys.platform == "darwin":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser(
            "~/Library/Caches/ms-playwright"
        )
    elif sys.platform == "win32":
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expandvars(
            r"%LOCALAPPDATA%\ms-playwright"
        )


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from src import __version__
    from src.database import Database
    from src.gui import APP_NAME, MainWindow, TrayApp

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    # 마지막 창을 닫아도 트레이에 상주하도록
    app.setQuitOnLastWindowClosed(False)

    try:
        db = Database()
    except Exception as e:
        QMessageBox.critical(None, APP_NAME, f"데이터베이스 초기화 실패:\n{e}")
        return 1

    window = MainWindow(db)
    window.show()  # 첫 실행 시 뷰어를 함께 띄움
    tray = TrayApp(window, interval_minutes=30)

    db.mark_seen([])  # 스키마 웜업 (no-op)
    window.reload()

    rc = app.exec()
    db.close()
    tray.hide()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
