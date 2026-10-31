"""IT/개발 관련성 판별 및 카테고리 분류 모듈.

키워드 기반 휴리스틱으로 스레드 본문을 판별해 (관련 여부, 태그)를 반환한다.
IT/개발 관련성이 낮은 잡담·광고·일상 글은 걸러진다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# 카테고리별 키워드 (대소문자 무시, 부분 일치)
CATEGORIES: dict[str, list[str]] = {
    "AI/ML": [
        "AI", "LLM", "GPT", "ChatGPT", "Claude", "Gemini", "Copilot",
        "클로드", "앤트로픽", "소네트", "오픈AI", "OpenAI", "코덱스", "codex",
        "머신러닝", "딥러닝", "기계학습", "인공지능", "신경망", "랭체인", "RAG",
        "MLOps", "텍스트마이닝", "임베딩", "파인튜닝", "gpu", "cuda",
        "pytorch", "tensorflow", "huggingface", "transformer", "에이전트",
    ],
    "Backend": [
        "백엔드", "backend", "서버", "API", "REST", "gRPC", "GraphQL",
        "데이터베이스", "DB", "SQL", "NoSQL", "Redis", "MongoDB", "MySQL",
        "PostgreSQL", "Django", "FastAPI", "Flask", "Spring", "Java",
        "Node.js", "Express", "NestJS", "PHP", "Laravel", "Rails",
        "마이크로서비스", "MSA", "캐시", "큐", "Kafka", "RabbitMQ",
    ],
    "Frontend": [
        "프론트엔드", "frontend", "React", "Vue", "Svelte", "Next.js",
        "Nuxt", "Angular", "JavaScript", "TypeScript", "CSS", "HTML",
        "tailwind", "webpack", "vite", "번들러", "UI/UX", "반응형",
        "웹디자인", "웹 퍼블리싱", "브라우저",
    ],
    "Cloud/DevOps": [
        "클라우드", "cloud", "AWS", "GCP", "Azure", "kubernetes", "k8s",
        "도커", "docker", "컨테이너", "CI/CD", "젠킨스", "jenkins",
        "terraform", "앤서블", "ansible", "리눅스", "linux", "nginx",
        "배포", "인프라", "infra", "모니터링", "grafana", "prometheus",
        "serverless", "람다", "lambda", "devops",
    ],
    "Data": [
        "빅데이터", "데이터분석", "데이터 엔지니어링", "데이터 엔지니어",
        "data engineering", "pandas", "numpy", "spark", "하둡", "hadoop",
        "ETL", "데이터 웨어하우스", "warehouse", "시각화", "태블로",
        "tableau", " Power BI", "R", "통계",
    ],
    "Career": [
        "채용", "공고", "이직", "면접", "커리어", "career", "취업",
        "신입", "경력", "이력서", "자기소개서", "연봉", "코딩테스트",
        "코테", "해외 취업", "주니어", "시니어", "포트폴리오",
    ],
    "Dev": [
        "개발", "코딩", "프로그래밍", "coding", "programming", "python",
        "git", "github", "오픈소스", "버그", "리팩토링",
        "테스트", "알고리즘", "자료구조", "IDE", "vscode", "에디터",
        "앱개발", "안드로이드", "android", "ios", "swift", "kotlin",
        "flutter", "rust", "golang", "c++", "c#", "라이브러리", "프레임워크",
        "SDK", "버전업", "릴리스", "release", "기술블로그", "기술 블로그",
    ],
}

# IT/개발과 무관한 글을 걸러내는 배제 힌트(과도한 필터 방지용 최소 세트)
NON_IT_HINTS = [
    "맛집", "여행", "다이어트", "운동", "드라마", "예능", "최애",
    "세일", "이벤트 당첨", "팔로우 환영", "맞팔", "출첵",
]


@dataclass
class Classification:
    """분류 결과."""

    is_it: bool
    tag: str  # 관련 없으면 "기타"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def classify(text: str, threshold: int = 1) -> Classification:
    """본문을 분류해 (IT 관련 여부, 태그)를 반환한다.

    threshold: 한 카테고리에서 몇 개 이상의 키워드가 매칭되어야 그
    카테고리로 인정할지의 최소 개수. 기본 1개.
    """
    lowered = _normalize(text).lower()
    if not lowered:
        return Classification(False, "기타")

    scores: dict[str, int] = {}
    for category, keywords in CATEGORIES.items():
        hits = 0
        for kw in keywords:
            k = kw.lower().strip()
            if k and k in lowered:
                hits += 1
        if hits >= threshold:
            scores[category] = hits

    if not scores:
        # 카테고리 키워드 미달이라도 개발 관련 단어가 강하면 Dev로 본다
        generic = ["개발자", "개발", "코드", "프로그램", "dev", "개발환경"]
        if any(g in lowered for g in generic):
            return Classification(True, "Dev")
        return Classification(False, "기타")

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return Classification(True, best)


def is_relevant(text: str) -> bool:
    """IT/개발 관련 글인지 여부."""
    return classify(text).is_it


def tags_list() -> list[str]:
    """UI 카테고리 필터 버튼에 쓸 태그 목록."""
    return ["전체"] + list(CATEGORIES.keys()) + ["북마크"]


def pick_tag(text: str) -> Optional[str]:
    """관련 글이면 태그를, 아니면 None을 반환."""
    c = classify(text)
    return c.tag if c.is_it else None
