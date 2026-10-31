# 🛰️ Threads IT 레이더

> **스레드(Threads)에서 IT/개발 콘텐츠만 선별 수집하는 데스크톱 레이더 앱 (PyQt6)**

스레드는 요즘 개발자 커뮤니티로서도 상당히 활발하지만, 타임라인에는 일상·잡담도 섞여 있습니다.
**Threads IT 레이더**는 스레드 검색을 주기적으로 돌려 **IT/개발 관련 글만 걸러서** 로컬에 모아
데스크톱 트레이에서 확인할 수 있는 가벼운 레이더 앱입니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
| --- | --- |
| 🛰️ **트레이 상주** | Windows 작업표시줄 / macOS 메뉴바 트레이에 상주하며 백그라운드에서 주기적(기본 30분) 수집 |
| 🔔 **데스크톱 알림** | 새 IT 글이 발견되면 시스템 알림으로 바로 알려줍니다 |
| 🧠 **IT 필터링** | 키워드 휴리스틱으로 AI/ML, Backend, Frontend, Cloud/DevOps, Data, Career 등 카테고리 자동 분류 |
| 🗂️ **카드 피드 뷰어** | 깔끔한 카드형 UI, 상단 검색창과 카테고리 필터 버튼 제공 |
| 🔗 **원문 보기** | 카드의 [원문 보기] 클릭 시 기본 웹 브라우저로 해당 스레드 포스트를 엽니다 |
| ⭐ **북마크** | 나중에 읽고 싶은 글을 북마크하고 [북마크] 필터로 모아 보기 |
| 💾 **로컬 SQLite 저장** | 모든 글은 `~/.threads_it_radar/threads_it_radar.db`에 로컬 저장 (post_id 고유 제약으로 중복 수집 없음) |

## 🖥️ 스크린샷

스크린샷은 `docs/` 폴더에 추가해 이 README에 붙일 수 있습니다.

```
docs/
  screenshot-main.png     # 메인 카드 피드
  screenshot-tray.png     # 트레이 메뉴
```

## 🚀 로컬 실행 방법

사전 요구 사항: **Python 3.10 이상**

```bash
# 1) 클론
git clone https://github.com/sungback/threads-it-radar.git
cd threads-it-radar

# 2) 가상환경 및 의존성 설치
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3) Playwright 브라우저 설치 (최초 1회)
python -m playwright install chromium

# 4) 실행
python main.py
```

실행하면 트레이 아이콘과 함께 뷰어 창이 열리고, 3초 후 첫 수집이 시작됩니다.
이후 30분마다 자동 수집합니다. 트레이 우클릭 → **지금 수집**으로 즉시 수집할 수도 있습니다.

### 수집 대상 검색어 바꾸기

`src/collector.py`의 `DEFAULT_QUERIES`를 수정하세요.

```python
DEFAULT_QUERIES = ["개발", "프로그래밍", "AI", "코딩"]
```

## 📦 빌드 방법 (Windows / macOS)

PyInstaller로 단일 실행 파일(.exe / .app)로 빌드할 수 있습니다.

```bash
pip install pyinstaller playwright PyQt6
python -m playwright install chromium

# Windows
pyinstaller --noconfirm --clean --onedir --windowed --name ThreadsITRadar main.py
# → dist/ThreadsITRadar/ThreadsITRadar.exe

# macOS
pyinstaller --noconfirm --clean --windowed --name ThreadsITRadar main.py
# → dist/ThreadsITRadar.app
```

## ⚙️ GitHub Actions 릴리스 자동화

태그를 푸시하면 Windows / macOS 두 플랫폼에서 자동 빌드 후 GitHub Releases에 업로드됩니다.

```bash
git tag v0.1.0
git push origin v0.1.0
```

- 워크플로: [`.github/workflows/release.yml`](.github/workflows/release.yml)
- 트리거: `v*` 태그 푸시, 또는 Actions 탭의 **Run workflow** (workflow_dispatch)
- 산출물: `ThreadsITRadar-Windows.zip`, `ThreadsITRadar-macOS.zip`

## 🗂️ 프로젝트 구조

```
threads-it-radar/
├── main.py                     # 실행 진입점 (트레이 생성, 타이머, 창 연결)
├── src/
│   ├── __init__.py
│   ├── database.py             # SQLite 저장소 (중복 방지, 목록 조회, 북마크 토글)
│   ├── filter.py               # IT/개발 관련성 판별 + 카테고리 분류
│   ├── collector.py            # Playwright 수집기 (GraphQL 인터셉트 + DOM fallback, QThread 워커)
│   └── gui.py                  # PyQt6 트레이 + 카드 피드 뷰어
├── requirements.txt
├── .github/workflows/release.yml
└── README.md
```

## 📄 라이선스

MIT
