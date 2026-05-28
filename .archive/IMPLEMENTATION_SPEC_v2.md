# 재사용 프로그램 스위트 v2 — Claude Code 구현 스펙

> **v2 변경사항**: 벤치마킹 결과 반영. 4개 독립 모듈 → 2개 판매 상품 + 1개 공유 엔진으로 재편.
> PyCaret 열화판 문제 해결, DL 트레이너 통합, 크롤러를 리뷰 분석 상품으로 패키징.
>
> **작성자**: 박진영 (AI 엔지니어 / 프리랜서 개발자)
> **기술 스택**: Python 3.11+, Streamlit, PyCaret, Selenium, Kiwi
> **코딩 컨벤션**: 타입힌트 필수, Black 포매터, docstring 필수

---

## 벤치마킹 요약 (왜 구조를 바꿨는가)

### 경쟁 분석 결과
| 원래 모듈 | 경쟁자 | 문제점 | 해결 |
|---|---|---|---|
| ML 빌더 | PyCaret (코드 3줄로 동일 기능) | 바퀴 재발명 | PyCaret 래핑으로 전환 |
| DL 트레이너 | AutoKeras, Ludwig | 우리가 더 못함 | ML 빌더에 옵션 통합 |
| 크롤러 | 크몽 셀러 다수 | 단순 크롤링은 레드오션 | 리뷰 분석 상품으로 패키징 |
| 전처리기 | pandas-profiling, dataprep | EDA 자체는 기존 도구 충분 | 한국어 NLP에 집중 |

### 차별점 = 한국어 + 납품 패키지 + Streamlit UI
- PyCaret/AutoKeras는 영어 중심, UI 없음 → **한국어 Streamlit UI**
- 크몽 크롤링 셀러는 데이터만 납품 → **AI 분석 + PDF 리포트까지**
- 기존 도구는 개발자 대상 → **비개발자도 CSV 넣으면 결과 나오는 프로그램**

---

## 최종 프로젝트 구조

```
jinyoung-toolkit/
├── README.md
├── pyproject.toml
├── .env.example
├── shared/                         # 공유 엔진 (한국어 NLP + 리포트 + 내보내기)
│   ├── __init__.py
│   ├── config.py                   # YAML 설정 로더 (pydantic-settings)
│   ├── logger.py                   # structlog 기반 로깅
│   ├── korean_nlp.py               # ⭐ 핵심 차별점: Kiwi 형태소 + 감성분석
│   ├── report_generator.py         # PDF 리포트 자동 생성 (fpdf2)
│   ├── exporters.py                # CSV(BOM)/JSON/Excel/Parquet 내보내기
│   ├── delivery.py                 # 납품 폴더 자동 구성 (01_raw/02_clean/03_report)
│   └── ui_components.py            # Streamlit 공통 컴포넌트
├── review_analyzer/                # 상품 1: 리뷰 분석 프로그램
│   ├── __init__.py
│   ├── crawler/                    # 크롤링 서브모듈
│   │   ├── engine.py               # 크롤링 엔진 (Selenium/httpx/API)
│   │   ├── drivers.py              # 드라이버 추상화
│   │   └── rate_limiter.py         # 속도 제한
│   ├── presets/                    # 사이트별 프리셋 (YAML)
│   │   ├── naver_shopping.yaml
│   │   ├── coupang_reviews.yaml
│   │   ├── google_play.yaml
│   │   └── custom_template.yaml
│   ├── preset_loader.py
│   ├── analyzer.py                 # ⭐ 감성분석 + 키워드 트렌드 + 워드클라우드
│   ├── cli.py                      # CLI: python -m review_analyzer
│   ├── app.py                      # Streamlit UI (메인 상품 화면)
│   └── tests/
│       ├── test_engine.py
│       ├── test_analyzer.py
│       └── test_presets.py
├── automl_reporter/                # 상품 2: AutoML 리포트 생성기
│   ├── __init__.py
│   ├── runner.py                   # ⭐ PyCaret 래핑 (setup→compare→tune→save)
│   ├── feature_inspector.py        # 자동 데이터 프로파일링
│   ├── report_builder.py           # 모델 비교 PDF 리포트
│   ├── visualizer.py               # 차트 생성 (confusion matrix, feature importance 등)
│   ├── dl_option.py                # 딥러닝 옵션 (AutoKeras 래핑, 선택적)
│   ├── cli.py
│   ├── app.py                      # Streamlit UI
│   └── tests/
│       ├── test_runner.py
│       ├── test_report_builder.py
│       └── test_dl_option.py
├── tests/                          # 통합 테스트 + fixture
│   └── fixtures/
│       ├── sample_reviews_50.csv   # 리뷰 샘플 50건 (한국어)
│       ├── sample_tabular.csv      # 정형 데이터 100행×10열
│       └── sample_text_class.csv   # 텍스트 분류용 샘플
├── scripts/
│   ├── run_review_analyzer.sh
│   └── run_automl_reporter.sh
├── Dockerfile                      # Docker 배포용
├── .streamlit/config.toml          # Streamlit Cloud 설정
├── .env.example                    # 환경변수 템플릿
└── Procfile                        # 클라우드 배포용
```

### 환경변수 (.env.example)

```env
# 공통
LOG_LEVEL=INFO
OUTPUT_DIR=./output
REPORT_AUTHOR=박진영

# 크롤러
CHROME_DRIVER_PATH=auto
CRAWL_DELAY_SECONDS=1.5
MAX_RETRIES=3
REQUEST_TIMEOUT=30

# 감성 분석 (Level 3 — LLM API 사용 시)
OPENAI_API_KEY=
SENTIMENT_MODEL=gpt-4o-mini
SENTIMENT_BATCH_SIZE=10

# ML/DL
RANDOM_SEED=42
TEST_SIZE=0.3

# 배포
GCP_PROJECT_ID=
GCP_REGION=asia-northeast3
```

### 테스트 fixture 생성 가이드

```python
# tests/fixtures/ — Claude Code가 Phase 1에서 자동 생성할 것

# sample_reviews_50.csv 구조:
# reviewer,rating,date,content,product_option
# "user1",5,"2024.03.15","배송 빠르고 품질 좋아요. 가성비 최고!","블랙 L"
# "user2",1,"2024.03.14","사이즈가 너무 작아요. 교환 요청했는데 느림","화이트 M"
# ... (한국어 리뷰 50건, 긍정 30 / 부정 10 / 중립 10)

# sample_tabular.csv: sklearn.datasets.make_classification(100, 10) 사용
# sample_text_class.csv: 한국어 문장 50개 + 라벨 (긍정/부정)
```

**변경 전 vs 후:**
- 파일 수: 현재 56개 (배포 파일, 테스트, YAML 프리셋 포함)
- 직접 구현량: ML 엔진 전체 → PyCaret/AutoKeras 래핑 (코드량 70% 감소)
- 차별점 집중: 한국어 NLP + Streamlit UI + PDF 리포트

---

## 공유 의존성 (pyproject.toml)

```toml
[project]
name = "jinyoung-toolkit"
version = "2.0.0"
description = "한국어 리뷰 분석 + AutoML 리포트 생성기"
requires-python = ">=3.11"

[tool.black]
line-length = 88

[tool.pytest.ini_options]
testpaths = ["tests", "review_analyzer/tests", "automl_reporter/tests"]
asyncio_mode = "auto"
```

> 의존성 목록은 `requirements.txt` 참조. pyproject.toml은 PEP 517 표준 포맷 (`[project]`)을 사용하며 Poetry 포맷(`[tool.poetry]`)이 아님.

---

## 상품 1: 리뷰 분석 프로그램 (review_analyzer)

### 포지셔닝
- **크몽 카피**: "리뷰 수집만 하지 마세요. AI가 고객 심리까지 분석해드립니다."
- **가격**: DELUXE 25만원 / PREMIUM 50만원 (Streamlit 대시보드 포함)
- **경쟁 우위**: 크몽에 "수집 + AI 감성분석 + 자동 리포트" 서비스 거의 없음 (블루오션)
- **기술 기반**: CX 프로젝트(23K건 크롤링 + NLP 파이프라인) 코드 재활용

### crawler/engine.py — 크롤링 엔진

```python
"""범용 크롤링 엔진.

CX 프로젝트의 맘카페/블로그/뉴스 크롤러를 범용화.
YAML 프리셋 기반으로 새 사이트 추가 = 설정 파일 1개 작성.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator

import pandas as pd
from pydantic import BaseModel, HttpUrl


class DriverType(str, Enum):
    SELENIUM = "selenium"
    HTTPX = "httpx"
    API = "api"


class CrawlConfig(BaseModel):
    """크롤링 설정."""
    preset_name: str
    target_urls: list[str]
    max_pages: int = 100
    delay_seconds: float = 1.5
    max_retries: int = 3
    timeout_seconds: int = 30
    output_dir: Path = Path("./output")
    driver_type: DriverType = DriverType.HTTPX
    respect_robots_txt: bool = True         # ⚠️ 법적 리스크 방지: 기본 True
    filter_pii: bool = True                 # 개인정보 자동 마스킹


class LegalComplianceChecker:
    """크롤링 법적 준수 검사기.

    ⚠️ 크몽 정책 + 개인정보보호법 준수 필수.
    이를 수행하지 않으면 크몽 계정 정지 및 법적 문제가 발생할 수 있음.

    검사 항목:
      1. robots.txt 파싱 → 크롤링 허용 여부 확인
      2. 요청 헤더에 User-Agent 명시 (봇 식별)
      3. 수집 데이터에서 PII 자동 마스킹 (이메일, 전화번호, 주민번호 패턴)
      4. 크롤링 시작 전 법적 고지 로그 출력
    """

    @staticmethod
    def check_robots_txt(url: str, user_agent: str = "JinyoungToolkit/1.0") -> bool:
        """robots.txt에서 크롤링 허용 여부 확인.

        Returns:
            True면 크롤링 허용, False면 차단
        """
        ...

    @staticmethod
    def mask_pii(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """개인정보 자동 마스킹.

        패턴:
          - 이메일: user@domain.com → u***@d***.com
          - 전화번호: 010-1234-5678 → 010-****-5678
          - 주민번호: 901231-1234567 → 901231-*******
        """
        ...

    @staticmethod
    def get_legal_disclaimer() -> str:
        """크몽 납품 시 포함할 법적 고지문 반환.

        Returns:
            "본 데이터는 공개된 웹페이지에서 합법적 절차로 수집되었으며..."
        """
        ...


@dataclass
class CrawlResult:
    """크롤링 결과."""
    total_collected: int
    total_failed: int
    data: pd.DataFrame          # ⚠️ 필드명 data (dataframe 아님). app.py에서 .dataframe 접근은 버그.
    errors: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class CrawlerEngine:
    """범용 크롤링 엔진.

    Usage:
        engine = CrawlerEngine(config)
        result = await engine.run()
    """

    def __init__(self, config: CrawlConfig) -> None: ...
    async def run(self) -> CrawlResult: ...

    async def run_with_progress(self) -> AsyncGenerator[dict[str, Any], None]:
        """Streamlit UI용 진행률 포함 크롤링.

        Yields:
            {"progress": 0.5, "collected": 50, "current_url": "...", "status": "running"}
        """
        ...

    def pause(self) -> None: ...
    def resume(self) -> None: ...
```

### analyzer.py — ⭐ 핵심 차별점: 분석 엔진

```python
"""리뷰 분석 엔진 — 크롤링 결과를 분석하고 인사이트를 생성.

이것이 크몽 단순 크롤링 셀러와의 차별점.
크롤링만 하면 10~30만원, 분석까지 하면 25~50만원.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class AnalysisResult:
    """분석 결과."""
    sentiment_distribution: dict[str, int]    # {"positive": 320, "negative": 80, "neutral": 100}
    keywords_positive: list[tuple[str, float]]  # [(키워드, TF-IDF 점수), ...]
    keywords_negative: list[tuple[str, float]]
    rating_distribution: dict[int, int]         # {5: 200, 4: 150, ...}
    total_reviews: int
    avg_rating: float
    wordcloud_path: Path | None
    insights: list[str] = field(default_factory=list)  # 규칙 기반 인사이트 3줄


class ReviewAnalyzer:
    """리뷰 분석기.

    크롤링 → 전처리 → 감성분석 → 키워드 추출 → 시각화 → PDF 리포트
    전체 파이프라인을 하나의 run() 호출로 실행.

    Usage:
        analyzer = ReviewAnalyzer(text_column="content", rating_column="rating")
        result = analyzer.run(crawled_df)
        analyzer.generate_report(result, output_path=Path("report.pdf"))
        analyzer.save_delivery_package(raw_df=crawled_df, result=result, output_dir=Path("output"))
    """

    def __init__(self, text_column: str = "content", rating_column: str | None = "rating") -> None:
        """초기화.

        Args:
            text_column: 리뷰 텍스트 컬럼명
            rating_column: 평점 컬럼명 (없으면 None)
        """
        ...

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """전처리: 중복제거 + 결측처리 + 한국어 형태소 분석.

        내부적으로 shared/korean_nlp.py의 KoreanTextProcessor 사용.
        """
        ...

    def analyze_sentiment(self, df: pd.DataFrame) -> pd.DataFrame:
        """감성 분석: 3단계 정확도 옵션.

        Level 1 (무료, 정확도 ~85%):
          - 평점 있으면: 4-5점=긍정, 3점=중립, 1-2점=부정
          - 가장 빠르고 안정적. 대부분의 크몽 납품에 충분.

        Level 2 (무료, 정확도 ~70%):
          - 평점 없을 때: 긍/부정 키워드 사전 기반 분류
          - 키워드 사전은 CX 프로젝트에서 검증된 목록 사용
          - 한계: 반어법, 문맥 의존 표현 처리 어려움

        Level 3 (유료, 정확도 ~95%):
          - OpenAI/Anthropic API 호출로 문맥 기반 분류
          - 비용: ~$0.01/리뷰 (GPT-4o-mini 기준, 1000건 = ~$10)
          - .env에 OPENAI_API_KEY 설정 필요
          - 배치 처리: 10건씩 묶어서 1회 API 호출 (비용 절감)

        Returns:
            sentiment 컬럼이 추가된 DataFrame ("positive"/"negative"/"neutral")
        """
        ...

    def extract_keywords(self, df: pd.DataFrame, top_k: int = 20) -> dict[str, list[tuple[str, float]]]:
        """감성별 키워드 추출 (TF-IDF).

        Returns:
            {"positive": [(kw, score), ...], "negative": [(kw, score), ...]}
        """
        ...

    def generate_wordcloud(self, df: pd.DataFrame, output_dir: Path) -> dict[str, Path]:
        """워드클라우드 생성.

        Returns:
            {"all": Path, "positive": Path, "negative": Path}
        """
        ...

    def generate_insights(self, result: AnalysisResult) -> list[str]:
        """인사이트 3줄 자동 생성.

        규칙 기반:
          - "전체 리뷰 중 긍정 비율이 X%로, 대체로 만족도가 높습니다."
          - "가장 많이 언급된 긍정 키워드는 X, Y, Z 입니다."
          - "부정 리뷰에서 X 관련 불만이 두드러집니다."
        """
        ...

    def run(self, df: pd.DataFrame) -> AnalysisResult:
        """전체 분석 파이프라인 실행.

        preprocess → analyze_sentiment → extract_keywords → generate_wordcloud → generate_insights
        """
        ...

    def generate_report(self, result: AnalysisResult, output_path: Path) -> Path:
        """1페이지 PDF 리포트 생성.

        구성:
          1. 데이터 개요 (수집 대상, 기간, 총 리뷰 수, 평균 평점)
          2. 감성 분포 (긍정/부정/중립 비율 — 파이차트)
          3. 평점 분포 (1~5점 히스토그램)
          4. 키워드 Top 10 (긍정 vs 부정 대비표)
          5. 워드클라우드 (전체/긍정/부정)
          6. 인사이트 3줄
        """
        ...

    def save_delivery_package(self, raw_df: pd.DataFrame, result: AnalysisResult, output_dir: Path, project_name: str = "review_analysis") -> Path:
        """크몽 납품 패키지 생성.

        생성 구조:
            output/
            ├── 01_raw/reviews_raw.csv
            ├── 02_clean/reviews_clean.csv
            ├── 03_analysis/
            │   ├── sentiment_summary.csv
            │   ├── keyword_trend.csv
            │   └── wordcloud.png
            ├── 04_report/report.pdf
            ├── 05_dashboard/app.py        ← PREMIUM 전용
            └── README.md
        """
        ...
```

### 프리셋 YAML (naver_shopping.yaml)

```yaml
name: naver_shopping
display_name: "네이버 쇼핑 리뷰"
description: "네이버 쇼핑 상품 리뷰 수집 + AI 분석"

driver:
  type: selenium
  headless: true
  wait_seconds: 3
  scroll_to_bottom: true

pagination:
  type: click
  next_button_selector: "a.pagination__next"
  max_pages: 50

selectors:
  container: "div.reviewItems_review__container"
  fields:
    reviewer: "span.reviewItems_reviewer"
    rating: "span.reviewItems_average"
    date: "span.reviewItems_date"
    content: "div.reviewItems_review__text"
    product_option: "span.reviewItems_option"

analysis:
  text_column: content
  rating_column: rating
  sentiment_method: rating_based  # rating_based | keyword_based
  # ⚠️ hybrid는 현재 미구현. analyzer.py는 rating_column 유무로 Level 1/2 자동 선택.

rate_limit:
  requests_per_minute: 30
  delay_between_pages: 2.0
```

### preset_loader.py — 셀렉터 검증 + fallback

```python
"""프리셋 로더 — YAML 로드 + 셀렉터 유효성 검증.

⚠️ 실무에서 가장 흔한 장애: 사이트 HTML 변경 → 셀렉터 무효화.
프리셋 로드 시 자동 검증 + 실패 시 fallback 전략 필요.
"""

from pathlib import Path
from typing import Any


class PresetLoader:
    """YAML 프리셋 로더.

    Args:
        presets_dir: 프리셋 YAML 디렉토리. None이면 review_analyzer/presets/ 사용.

    필수 스키마 키: name, display_name, selectors (container + fields 필수).
    """

    def __init__(self, presets_dir: Path | None = None) -> None: ...

    def load(self, preset_name: str) -> dict[str, Any]:
        """프리셋 로드 + 스키마 검증.

        Raises:
            FileNotFoundError: 파일 없을 때.
            ValueError: 필수 키 누락 등 스키마 검증 실패 시.
        """
        ...

    def validate_selectors(self, preset: dict[str, Any], sample_url: str) -> dict[str, bool]:
        """CSS 셀렉터 유효성 검증.

        실제 페이지를 1회 요청해서 각 셀렉터가 요소를 찾는지 확인.

        Returns:
            {"container": True, "reviewer": True, "rating": False, ...}
            False인 셀렉터가 있으면 경고 로그 출력.
        """
        ...

    def get_fallback_selectors(self, preset_name: str) -> dict[str, str] | None:
        """히스토리 기반 fallback 셀렉터 반환.

        presets/ 폴더에 {preset_name}.fallback.yaml이 있으면 로드.
        이전 버전의 셀렉터를 순차 시도.
        """
        ...

    def list_presets(self) -> list[dict[str, str]]:
        """사용 가능한 프리셋 목록."""
        ...
```

### async 크롤러 + Streamlit 연동 가이드

```python
"""⚠️ Streamlit은 동기 실행이므로 async CrawlerEngine을 직접 호출하면 에러.
아래 패턴으로 래핑해야 함.

# 실제 app.py에서 사용하는 패턴 (CrawlResult.data 필드 접근):
#   crawl_result = asyncio.run(engine.run())
#   df = crawl_result.data   # .dataframe이 아님 — .data

# app.py에서 사용하는 패턴:
import asyncio
from concurrent.futures import ThreadPoolExecutor

def run_crawler_sync(config: CrawlConfig) -> CrawlResult:
    '''async 크롤러를 동기로 래핑.'''
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(CrawlerEngine(config).run())
    finally:
        loop.close()

# Streamlit에서의 사용:
# asyncio.run(engine.run()) + st.spinner() 조합.
# run_with_progress()는 이중 실행 버그가 있어 사용하지 않음.
# 진행률 표시는 향후 Phase에서 WebSocket/SSE 기반으로 개선 예정.
"""
```

### Streamlit UI (app.py) — 화면 구성

```
┌─────────────────────────────────────────────────┐
│  🔍 리뷰 분석 프로그램                           │
│  "리뷰 수집만 하지 마세요. AI가 분석합니다."      │
├─────────────────────────────────────────────────┤
│                                                 │
│  📌 Step 1: 데이터 입력                          │
│  ○ 사이트에서 수집  ● CSV 파일 업로드             │
│                                                 │
│  [프리셋 선택 ▼] 네이버 쇼핑                     │
│  URL: [_________________________________]       │
│  최대 페이지: [10]                               │
│                                                 │
│  📌 Step 2: 분석 설정                            │
│  텍스트 컬럼: [content ▼]  평점 컬럼: [rating ▼] │
│  💡 감성 분석: 평점 컬럼 유무에 따라 자동 선택     │
│                                                 │
│  [🚀 분석 시작]                                  │
│                                                 │
│  ═══════════════════════════════════════════     │
│  📊 분석 결과                                    │
│  ┌──────────────┬──────────────────────┐        │
│  │ 😊 긍정 72%  │  [파이차트]           │        │
│  │ 😐 중립 15%  │                      │        │
│  │ 😞 부정 13%  │                      │        │
│  └──────────────┴──────────────────────┘        │
│                                                 │
│  🔑 키워드 Top 10                                │
│  긍정: 배송, 품질, 가성비, ...                    │
│  부정: 포장, 사이즈, 교환, ...                    │
│                                                 │
│  ☁️ 워드클라우드                                  │
│  [전체] [긍정] [부정]  ← 탭 전환                  │
│                                                 │
│  💡 인사이트                                      │
│  1. 전체 리뷰 중 긍정 비율 72%로 만족도 높음      │
│  2. "배송" "가성비" 키워드가 가장 빈번            │
│  3. 부정 리뷰에서 "사이즈" 관련 불만 두드러짐     │
│                                                 │
│  [📥 납품 패키지 다운로드]  [📄 PDF 리포트]       │
└─────────────────────────────────────────────────┘
```

### 테스트 케이스

```python
class TestCrawlerEngine:
    async def test_crawl_with_preset_returns_dataframe(self): ...
    async def test_crawl_respects_max_pages(self): ...
    async def test_crawl_handles_network_error(self): ...
    async def test_rate_limiter_enforces_delay(self): ...

class TestReviewAnalyzer:
    def test_preprocess_removes_duplicates(self): ...
    def test_sentiment_by_rating(self): ...
    def test_sentiment_by_keywords(self): ...
    def test_keyword_extraction_top_k(self): ...
    def test_wordcloud_generates_png(self): ...
    def test_insights_generates_3_lines(self): ...
    def test_pdf_report_generated(self): ...
    def test_delivery_package_structure(self): ...
    def test_handles_empty_reviews(self): ...
    def test_handles_no_rating_column(self): ...
```

---

## 상품 2: AutoML 리포트 생성기 (automl_reporter)

### 포지셔닝
- **핵심**: PyCaret을 내부 엔진으로 래핑. "CSV 넣으면 모델 비교 리포트 나오는 프로그램"
- **경쟁 우위**: PyCaret 자체는 코드 필요 → 우리는 Streamlit UI + 한국어 리포트 + 납품 패키지
- **DX 프로젝트**: 데이터 분석 단계에서 바로 투입 가능
- **크몽 가격**: 30~50만원/건

### runner.py — ⭐ PyCaret 래핑 (직접 구현 NO)

```python
"""AutoML 실행기 — PyCaret 래핑.

⚠️ 벤치마킹 결과: ML 엔진을 직접 구현하면 PyCaret 열화판이 됨.
PyCaret을 내부 엔진으로 사용하되, 한국어 UI + PDF 리포트 + 납품 패키지가 차별점.

PyCaret이 이미 하는 것:
  - setup(): 전처리 자동화 (인코딩, 스케일링, 결측 처리)
  - compare_models(): 15+ 모델 자동 비교
  - tune_model(): Optuna 하이퍼파라미터 최적화
  - save_model(): 모델 저장

우리가 추가하는 것:
  - 한국어 Streamlit UI (비개발자도 사용 가능)
  - 자동 PDF 리포트 (모델 비교 차트 + 추천 + 이유)
  - 납품 패키지 (model.pkl + report.pdf + README.md)
  - 자동 문제 유형 감지 (분류/회귀/클러스터링)
  - 한국어 데이터 특화 전처리 (Kiwi NLP 연동)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel


class TaskType(str, Enum):
    BINARY_CLASSIFICATION = "binary_classification"
    MULTICLASS_CLASSIFICATION = "multiclass_classification"
    REGRESSION = "regression"
    CLUSTERING = "clustering"


class AutoMLConfig(BaseModel):
    """AutoML 설정."""
    input_path: Path
    target_column: str | None = None         # None → 클러스터링
    task_type: TaskType | None = None        # None → 자동 감지
    top_n_models: int = 5                    # 비교할 상위 모델 수
    optimize_metric: str | None = None       # None → 자동 선택 (Accuracy/RMSE)
    tune_top_n: int = 3                      # 튜닝할 상위 모델 수
    cv_folds: int = 5
    test_size: float = 0.3
    random_seed: int = 42
    include_text_features: bool = False      # True → Kiwi NLP 전처리 연동
    text_columns: list[str] = []
    output_dir: Path = Path("./output")


@dataclass
class ModelResult:
    """개별 모델 결과."""
    name: str
    metrics: dict[str, float]
    is_tuned: bool
    training_time_seconds: float


@dataclass
class AutoMLResult:
    """전체 AutoML 결과."""
    task_type: TaskType
    model_results: list[ModelResult]
    best_model_name: str
    best_metrics: dict[str, float]
    feature_importance: dict[str, float] | None
    data_summary: dict[str, Any]   # {rows, columns, dtypes, missing_pct}


class AutoMLRunner:
    """PyCaret 래핑 AutoML 실행기.

    Usage:
        runner = AutoMLRunner(config)
        result = runner.run()
        runner.save_best_model(Path("model.pkl"))

        # 납품 패키지 조립 (shared/delivery.py)
        pkg = DeliveryPackage(output_dir=Path("output"), project_name="automl")
        pkg.add_raw(df)
        pkg.add_report(AutoMLReportBuilder(result).build(Path("report.pdf")))
        pkg.add_model(Path("model.pkl"), {"model_name": result.best_model_name})
        pkg.build()
    """

    def __init__(self, config: AutoMLConfig) -> None: ...

    def detect_task_type(self, df: pd.DataFrame) -> TaskType:
        """타겟 분석 → 문제 유형 자동 감지."""
        ...

    def run(self) -> AutoMLResult:
        """전체 파이프라인 실행.

        내부 흐름:
          1. CSV 로드 + 데이터 요약
          2. 문제 유형 감지
          3. (옵션) 텍스트 컬럼 Kiwi NLP 전처리
          4. pycaret.setup() → 전처리 자동화
          5. pycaret.compare_models(n_select=top_n) → 모델 비교
          6. pycaret.tune_model() × tune_top_n → 하이퍼파라미터 최적화
          7. 최적 모델 선택 + feature importance 추출
          8. AutoMLResult 반환
        """
        ...

    # run_with_progress()는 미구현. st.spinner("AutoML 분석 중...") 사용.

    def save_best_model(self, output_path: Path) -> Path:
        """최적 모델 저장 (joblib pickle).

        run() 실행 후 호출 가능. _best_model이 None이면 RuntimeError.

        Returns:
            저장된 .pkl 파일의 절대 Path.
        """
        ...

    # 납품 패키지 조립은 위 Usage 예시 참고. shared/delivery.py 사용.


class AutoMLReportBuilder:
    """모델 비교 PDF 리포트 빌더.

    리포트 구성 (2페이지):
      Page 1:
        - 데이터 요약 (행/열, 타겟 분포, 결측률)
        - 문제 유형 + 선택 이유
        - 모델 비교 차트 (bar chart)
        - 최적 모델 추천 + 이유

      Page 2:
        - Feature Importance Top 10 (bar chart)
        - Confusion Matrix (분류) / Residual Plot (회귀)
        - 하이퍼파라미터 요약 테이블
        - 다음 단계 제안
    """

    def __init__(self, result: AutoMLResult) -> None: ...
    def build(self, output_path: Path) -> Path: ...
```

### dl_option.py — 딥러닝 옵션 (선택적)

```python
"""딥러닝 옵션 — AutoKeras 래핑 (선택적 설치).

⚠️ 벤치마킹 결과: DL 트레이너를 독립 모듈로 만들 필요 없음.
AutoKeras가 이미 NAS 기반 아키텍처 탐색을 더 잘함.
우리는 래핑만 하고, 한국어 리포트 + 납품 패키지를 붙이는 것이 가치.

설치: pip install jinyoung-toolkit[dl]
"""

from pathlib import Path
from typing import Any

import pandas as pd


class DeepLearningOption:
    """AutoKeras 기반 딥러닝 옵션.

    ML 빌더에서 "딥러닝도 시도해볼까요?" 옵션으로 제공.
    독립 실행도 가능하지만, 주로 AutoMLRunner와 연동.

    지원 데이터 타입:
      - tabular (StructuredDataClassifier/Regressor)
      - text (TextClassifier) — Kiwi 전처리 연동
      - image (ImageClassifier)
    """

    def __init__(self, data_type: str = "tabular", max_trials: int = 10) -> None: ...

    def is_available(self) -> bool:
        """autokeras/tensorflow 설치 여부 확인."""
        ...

    def run(self, X_train: Any, y_train: Any, X_test: Any, y_test: Any) -> dict[str, Any]:
        """AutoKeras 학습 실행.

        Returns:
            {"model_name": "...", "metrics": {...}, "model_path": Path, "history": {...}}
        """
        ...

    def export_model(self, output_path: Path, format: str = "keras") -> Path:
        """모델 내보내기 (keras/onnx/tflite)."""
        ...
```

### Streamlit UI (app.py) — 화면 구성

```
┌─────────────────────────────────────────────────┐
│  🤖 AutoML 리포트 생성기                         │
│  "CSV 넣으면 최적 모델 + 리포트가 나옵니다"       │
├─────────────────────────────────────────────────┤
│                                                 │
│  📌 Step 1: 데이터 업로드                        │
│  [CSV 파일 드래그 & 드롭]                        │
│                                                 │
│  📊 데이터 미리보기 (5행)                         │
│  ┌──────┬──────┬──────┬──────┐                  │
│  │ col1 │ col2 │ col3 │ 타겟 │                  │
│  └──────┴──────┴──────┴──────┘                  │
│                                                 │
│  📌 Step 2: 설정                                 │
│  타겟 컬럼: [target ▼]                           │
│  감지된 문제 유형: 🏷️ 이진 분류                   │
│  ☑ 한국어 텍스트 컬럼 NLP 전처리                  │
│  ☐ 딥러닝도 시도 (시간 오래 걸림)                 │
│                                                 │
│  [🚀 모델 학습 시작]                              │
│                                                 │
│  ═══════════════════════════════════════════     │
│  📈 모델 비교 결과                                │
│  1. 🥇 XGBoost        Accuracy: 0.94           │
│  2. 🥈 LightGBM       Accuracy: 0.93           │
│  3. 🥉 Random Forest  Accuracy: 0.91           │
│  4.    Logistic Reg.   Accuracy: 0.87           │
│  5.    SVM             Accuracy: 0.85           │
│                                                 │
│  [bar chart 시각화]                              │
│                                                 │
│  🔑 Feature Importance Top 10                   │
│  [horizontal bar chart]                         │
│                                                 │
│  [📥 납품 패키지 다운로드]  [📄 PDF 리포트]       │
└─────────────────────────────────────────────────┘
```

### 테스트 케이스

```python
class TestAutoMLRunner:
    def test_detect_binary_classification(self): ...
    def test_detect_regression(self): ...
    def test_detect_clustering_when_no_target(self): ...
    def test_run_uses_pycaret_internally(self): ...
    def test_compare_models_returns_top_n(self): ...
    def test_tune_improves_baseline(self): ...
    def test_save_delivery_package_structure(self): ...
    def test_pdf_report_2_pages(self): ...
    def test_text_features_with_kiwi(self): ...
    def test_handles_missing_values(self): ...

class TestDLOption:
    def test_is_available_without_install(self): ...
    def test_tabular_classification(self): ...
    def test_text_classification_with_kiwi(self): ...
    def test_export_keras_model(self): ...
```

---

## 공유 엔진: 한국어 NLP (shared/korean_nlp.py)

```python
"""한국어 NLP 처리 엔진 — Kiwi 기반.

⭐ 이것이 전체 프로젝트의 핵심 차별점.
pandas-profiling, PyCaret, AutoKeras 모두 한국어 형태소 분석을 못함.
이 모듈이 두 상품 모두에서 사용됨.

CX 프로젝트 검증 완료:
  - Kiwi 형태소 분석 → SBERT 임베딩 → K-means 클러스터링 → LDA 토픽 모델링
  - 23,000건 → 15,638건 정제 파이프라인 실전 검증
"""

from pathlib import Path
from typing import Any

import pandas as pd


# 기본 불용어 사전 (CX 프로젝트에서 검증)
DEFAULT_STOPWORDS: frozenset[str] = frozenset([
    "하다", "되다", "있다", "없다", "이다", "아니다",
    "것", "수", "등", "더", "좀", "잘", "안", "못",
    "저", "제", "나", "내", "너", "네", "그", "이",
    # ... 확장 예정
])


class KoreanTextProcessor:
    """한국어 텍스트 전처리기.

    두 상품 모두에서 사용:
      - review_analyzer: 리뷰 텍스트 분석
      - automl_reporter: 텍스트 피처 전처리
    """

    def __init__(self, stopwords: set[str] | None = None, custom_dict_path: Path | None = None) -> None:
        """초기화.

        Args:
            stopwords: 커스텀 불용어 (None이면 DEFAULT_STOPWORDS)
            custom_dict_path: Kiwi 사용자 사전 경로
        """
        ...

    def tokenize(self, texts: pd.Series, pos_filter: list[str] | None = None) -> pd.Series:
        """형태소 분석 후 토큰 추출.

        Args:
            texts: 원본 텍스트
            pos_filter: 추출할 품사 태그 (기본: ["NNG", "NNP", "VA", "VV"])
                NNG=일반명사, NNP=고유명사, VA=형용사, VV=동사

        Returns:
            공백 구분 토큰 문자열 시리즈
        """
        ...

    def remove_stopwords(self, tokens: pd.Series) -> pd.Series: ...

    def extract_keywords_tfidf(self, texts: pd.Series, top_k: int = 20) -> list[tuple[str, float]]:
        """TF-IDF 키워드 추출."""
        ...

    def extract_keywords_by_group(
        self, texts: pd.Series, labels: pd.Series, top_k: int = 10
    ) -> dict[str, list[tuple[str, float]]]:
        """그룹별 키워드 추출 (감성별, 클러스터별 등).

        Returns:
            {"positive": [(kw, score)], "negative": [(kw, score)], ...}
        """
        ...

    def to_tfidf_features(self, texts: pd.Series, max_features: int = 500) -> pd.DataFrame:
        """TF-IDF 피처 벡터로 변환 (ML 모델 입력용).

        automl_reporter에서 텍스트 컬럼을 수치 피처로 변환할 때 사용.
        """
        ...

    def generate_wordcloud(self, texts: pd.Series, output_path: Path, **kwargs: Any) -> Path:
        """워드클라우드 이미지 생성.

        ⚠️ 한글 폰트 없으면 글자가 □□□□로 깨짐. 자동 감지 로직 필수.

        폰트 탐색 순서:
          1. kwargs["font_path"]가 지정되면 그대로 사용
          2. 시스템에서 NanumGothic 자동 탐색
             - Linux: /usr/share/fonts/truetype/nanum/NanumGothic.ttf
             - macOS: ~/Library/Fonts/NanumGothic.ttf
             - Windows: C:/Windows/Fonts/NanumGothic.ttf
          3. 프로젝트 번들 폰트: shared/fonts/NanumGothic.ttf
          4. 모두 없으면 RuntimeError("한글 폰트를 찾을 수 없습니다")

        kwargs: width=800, height=400, background_color="white", colormap="viridis"
        """
        ...

    @staticmethod
    def find_korean_font() -> Path:
        """시스템에서 한글 폰트 경로 자동 탐색.

        Returns:
            폰트 파일 경로

        Raises:
            RuntimeError: 한글 폰트를 찾을 수 없을 때
        """
        ...
```

---

## 공유 엔진: PDF 리포트 생성기 (shared/report_generator.py)

```python
"""PDF 리포트 생성기 — fpdf2 기반.

모든 상품이 공유. 크몽 납품 표준 1~2페이지 PDF 생성.
"""

from pathlib import Path
from typing import Any


class ReportGenerator:
    """범용 PDF 리포트 생성기.

    Usage:
        report = ReportGenerator(title="네이버 쇼핑 리뷰 분석", author="박진영")
        report.add_section("데이터 개요", "총 500건, 평균 평점 4.2")
        report.add_table(["항목", "값"], [["총 리뷰", "500건"], ["평균 평점", "4.2"]])
        report.add_chart(Path("wordcloud.png"), "워드클라우드")
        report.add_insight("긍정 비율 72%로 만족도 높음")
        report.save(Path("report.pdf"))
    """

    def __init__(self, title: str, author: str = "박진영", font_path: Path | None = None) -> None:
        """초기화.

        ⚠️ fpdf2에서 한글 출력하려면 NanumGothic 폰트 등록 필수.
        font_path가 None이면 KoreanTextProcessor.find_korean_font() 사용.
        """
        ...

    def add_section(self, heading: str, content: str) -> None: ...
    def add_table(self, headers: list[str], rows: list[list[str]]) -> None: ...
    def add_chart(self, image_path: Path, caption: str = "") -> None: ...
    def add_insight(self, text: str) -> None: ...
    def save(self, output_path: Path) -> Path: ...
```

---

## 공유 엔진: 납품 패키지 (shared/delivery.py)

```python
"""납품 폴더 자동 구성.

크몽 납품 표준:
  output/
  ├── 01_raw/          ← 원본 데이터
  ├── 02_clean/        ← 정제 데이터
  ├── 03_analysis/     ← 분석 결과 (선택)
  ├── 04_report/       ← PDF 리포트
  └── README.md        ← 실행 방법 + 컬럼 설명
"""

from pathlib import Path
from typing import Any

import pandas as pd


class DeliveryPackage:
    """납품 패키지 빌더."""

    def __init__(self, output_dir: Path, project_name: str = "delivery") -> None: ...

    def add_raw(self, df: pd.DataFrame, filename: str = "raw.csv") -> None: ...
    def add_clean(self, df: pd.DataFrame, filename: str = "clean.csv") -> None: ...
    def add_analysis(self, files: dict[str, Any]) -> None: ...
    def add_report(self, pdf_path: Path) -> None: ...
    def add_model(self, model_path: Path, config: dict[str, Any]) -> None: ...
    def add_dashboard(self, app_code: str) -> None: ...

    def generate_readme(self, context: dict[str, Any]) -> None:
        """README.md 자동 생성.

        context: {
            "project": "네이버 쇼핑 리뷰 분석",
            "total_rows": 500,
            "columns": ["reviewer", "rating", "content"],
            "run_command": "streamlit run app.py",
        }
        """
        ...

    def build(self) -> Path:
        """최종 패키지 빌드 (ZIP 압축 옵션)."""
        ...
```

---

## 공유 엔진: 설정 관리 (shared/config.py)

```python
"""공유 설정 관리 — pydantic-settings BaseSettings 기반.

.env 파일 및 환경변수에서 값을 자동으로 로드한다.
get_settings()로 싱글턴 인스턴스에 접근한다.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """애플리케이션 전체 설정. 환경변수가 .env보다 우선순위 높음."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # 로깅
    log_level: str = Field(default="INFO")
    # 경로
    output_dir: Path = Field(default=Path("output"))
    chrome_driver_path: Path = Field(default=Path("/usr/local/bin/chromedriver"))
    # 리포트
    report_author: str = Field(default="jinyoung-toolkit")
    # 크롤링
    crawl_delay_seconds: float = Field(default=1.0, ge=0.0)
    max_retries: int = Field(default=3, ge=0)
    request_timeout: int = Field(default=30, gt=0)
    # OpenAI
    openai_api_key: Optional[str] = Field(default=None)
    # 감성 분석
    sentiment_model: str = Field(default="snunlp/KR-FinBert-SC")
    sentiment_batch_size: int = Field(default=32, gt=0)
    # ML
    random_seed: int = Field(default=42)
    test_size: float = Field(default=0.2, gt=0.0, lt=1.0)
    # GCP
    gcp_project_id: Optional[str] = Field(default=None)
    gcp_region: str = Field(default="asia-northeast3")


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """AppSettings 싱글턴 반환 (lru_cache로 최초 1회만 생성)."""
    return AppSettings()
```

---

## 공유 엔진: 데이터 내보내기 (shared/exporters.py)

```python
"""데이터 내보내기 — CSV(BOM) / JSON / Excel / Parquet 지원."""

from pathlib import Path
import pandas as pd


def export_csv(df: pd.DataFrame, output_path: Path, encoding: str = "utf-8-sig") -> Path:
    """DataFrame → CSV. 기본 인코딩 utf-8-sig (엑셀 BOM 호환)."""
    ...

def export_json(df: pd.DataFrame, output_path: Path, orient: str = "records") -> Path:
    """DataFrame → JSON (force_ascii=False, indent=2)."""
    ...

def export_excel(df: pd.DataFrame, output_path: Path, sheet_name: str = "Sheet1") -> Path:
    """DataFrame → Excel (.xlsx, openpyxl 엔진)."""
    ...

def export_parquet(df: pd.DataFrame, output_path: Path) -> Path:
    """DataFrame → Parquet (pyarrow 엔진)."""
    ...
```

---

## 공유 엔진: 시각화 (automl_reporter/visualizer.py)

```python
"""AutoML 결과 시각화 — matplotlib/seaborn 기반 (Agg 백엔드, 서버용).

한글 폰트 자동 설정. output_path=None이면 임시 디렉토리에 저장.
"""

from pathlib import Path
from typing import Any


class Visualizer:
    """AutoML 결과 시각화 클래스."""

    def __init__(self) -> None:
        """한글 폰트를 matplotlib에 자동 등록."""
        ...

    def confusion_matrix(
        self,
        y_true: Any,
        y_pred: Any,
        labels: list[str] | None = None,
        output_path: Path | None = None,
        title: str = "혼동 행렬",
    ) -> Path:
        """혼동 행렬 히트맵 (seaborn.heatmap). 저장된 이미지 Path 반환."""
        ...

    def feature_importance(
        self,
        importances: dict[str, float],
        top_k: int = 10,
        output_path: Path | None = None,
        title: str = "피처 중요도 Top 10",
    ) -> Path:
        """수평 막대 그래프 (상위 top_k 피처, 내림차순 정렬)."""
        ...

    def model_comparison_bar(
        self,
        model_names: list[str],
        scores: list[float],
        metric_name: str = "Accuracy",
        output_path: Path | None = None,
        title: str = "모델 비교",
    ) -> Path:
        """수직 막대 그래프 (최고 성능 모델 색상 강조)."""
        ...

    def residual_plot(
        self,
        y_true: Any,
        y_pred: Any,
        output_path: Path | None = None,
        title: str = "잔차 분포",
    ) -> Path:
        """잔차 산점도 (회귀용). x=예측값, y=잔차(실제-예측), 기준선 0 표시."""
        ...

    def target_distribution(
        self,
        series: Any,
        output_path: Path | None = None,
        title: str = "타겟 분포",
    ) -> Path:
        """타겟 분포 차트. 범주형 → 막대 그래프, 연속형 → 히스토그램."""
        ...
```

---

## 배포 전략 (exe 아님)

### 왜 exe가 아닌가
- Streamlit + Selenium + PyCaret을 exe로 묶으면 500MB+ → 안티바이러스 차단 빈번
- PyInstaller로 Streamlit 내장 가능하지만 불안정
- **크몽 의뢰의 80%는 "분석 결과 납품"이지 "프로그램 납품"이 아님**

### 납품 형태별 배포 방식

| 납품 형태 | 대상 | 배포 방식 | 의뢰인이 할 일 |
|---|---|---|---|
| A. 데이터 납품 (80%) | 크몽 일반 의뢰 | ZIP 파일 전달 | 파일 열기만 |
| B. 대시보드 납품 (15%) | PREMIUM 패키지 | Streamlit Cloud URL | 브라우저 접속 |
| C. 프로그램 납품 (5%) | 개발자 의뢰인 | Docker 또는 소스코드+README | docker run 또는 pip install |
| D. DX 프로젝트 / 내부 | 본인 | CLI / Streamlit 직접 실행 | python -m ... |

### Streamlit Cloud 배포 설정 (PREMIUM용)

⚠️ **Streamlit Cloud 무료 플랜 제한**: RAM 1GB, CPU 공유.
PyCaret 모델 비교(15+ 모델)나 대량 크롤링 시 메모리 부족 가능.

**권장 배포 우선순위:**
1. **Streamlit Cloud** — 소규모 분석 (리뷰 1000건 이하) → 무료
2. **GCP Cloud Run** — 대규모 분석 (GCP 경험 활용) → $0.00002/초
3. **Railway/Render** — 중간 규모 → $5/월~

프로젝트 루트에 아래 파일 추가:

```
# .streamlit/config.toml
[server]
headless = true
port = 8501
enableCORS = false

[theme]
primaryColor = "#4A90D9"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
```

```
# Procfile (Streamlit Cloud / Railway 배포용)
web: streamlit run review_analyzer/app.py --server.port $PORT
```

### Docker 지원 (기업 납품용)

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Chrome + ChromeDriver + 한글 폰트 설치
RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
    fonts-nanum fonts-nanum-coding \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# ⚠️ 한글 폰트 경로 확인 (워드클라우드용)
# /usr/share/fonts/truetype/nanum/NanumGothic.ttf

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
CMD ["streamlit", "run", "review_analyzer/app.py", "--server.port=8501"]
```

```bash
# 의뢰인 실행 (한 줄)
docker run -p 8501:8501 jinyoung/review-analyzer
# 브라우저에서 http://localhost:8501 접속
```

### GCP Cloud Run 배포 (대규모 분석용, 추천)

GCP Cloud Run은 자동 스케일링, 사용량 기반 과금, 커스텀 도메인을 지원하는 현실적인 유료 배포 옵션이다.
자동 스케일링 + 사용한 만큼만 과금 + 커스텀 도메인.

```bash
# 1. Docker 이미지 빌드 + GCR 푸시
gcloud builds submit --tag gcr.io/PROJECT_ID/review-analyzer

# 2. Cloud Run 배포 (메모리 2GB, 콜드스타트 허용)
gcloud run deploy review-analyzer \
  --image gcr.io/PROJECT_ID/review-analyzer \
  --platform managed \
  --region asia-northeast3 \
  --memory 2Gi \
  --port 8501 \
  --allow-unauthenticated

# 3. 커스텀 도메인 연결 (선택)
gcloud run domain-mappings create \
  --service review-analyzer \
  --domain analyzer.jinyoung.dev
```

비용 추정:
- 의뢰 1건(5분 실행): ~$0.006 (거의 무료)
- 월 50건 의뢰: ~$0.30
- 유휴(idle) 시 자동 0으로 스케일 → 미사용 시 무과금

### exe 옵션 (선택적, Phase 4에서 검토)

```python
# build_exe.py — PyInstaller 빌드 스크립트 (필요 시만)
# ⚠️ 안정성 이슈로 기본 제공하지 않음
# 의뢰인이 강하게 요청할 경우에만 별도 견적

import PyInstaller.__main__

PyInstaller.__main__.run([
    "review_analyzer/app.py",
    "--onefile",
    "--name=ReviewAnalyzer",
    "--add-data=presets:presets",
    "--hidden-import=streamlit",
    "--hidden-import=pycaret",
])
```

---

## 납품 체크리스트 (모든 모듈 공통)

```
[ ] 에러 핸들링: 모든 외부 호출에 try/except + structlog
[ ] 엣지케이스: 빈 데이터, 단일 행, 한국어 특수문자, 인코딩 깨짐
[ ] 테스트 코드: 각 핵심 함수 최소 2개 테스트
[ ] print 제거: structlog만 사용
[ ] 환경변수 하드코딩 없음: .env + pydantic-settings
[ ] 타입힌트: 모든 함수 인자/반환값
[ ] docstring: 모든 클래스/public 함수
[ ] README.md: CLI 사용법 + Streamlit 실행 방법 + 예제
[ ] CSV 인코딩: UTF-8 BOM (비개발자 엑셀 호환)
```

---

## 구현 순서 (Claude Code에게)

```
Phase 1 (Day 1-2): 공유 엔진
  1. shared/korean_nlp.py — Kiwi 형태소 + 키워드 + 워드클라우드
  2. shared/report_generator.py — PDF 리포트
  3. shared/exporters.py + delivery.py — 내보내기 + 납품 패키지
  4. shared/ 테스트 작성 + 통과

Phase 2 (Day 3-5): 리뷰 분석 프로그램 (상품 1)
  1. review_analyzer/crawler/ — 크롤링 엔진 + 프리셋 3개
  2. review_analyzer/analyzer.py — 감성분석 + 키워드 + 시각화
  3. review_analyzer/app.py — Streamlit UI
  4. review_analyzer/cli.py
  5. 테스트 + 샘플 데이터로 E2E 테스트

Phase 3 (Day 6-7): AutoML 리포트 생성기 (상품 2)
  1. automl_reporter/runner.py — PyCaret 래핑
  2. automl_reporter/report_builder.py + visualizer.py
  3. automl_reporter/app.py — Streamlit UI
  4. automl_reporter/dl_option.py (선택적)
  5. 테스트 + 샘플 CSV로 E2E 테스트

Phase 4 (Day 8-9): 통합 + 배포 + 납품셋
  1. 메인 Streamlit 앱 (상품 선택 화면)
  2. Dockerfile + .streamlit/config.toml 작성
  3. Streamlit Cloud 배포 테스트
  4. 크몽 포트폴리오용 샘플 결과물 생성
  5. 전체 납품 체크리스트 검증
  6. README.md 최종 작성 (CLI/Docker/Cloud 실행법 포함)
```

**v1 대비 변경:**
- 10일 → 9일 (배포 작업 포함)
- 현재 파일 56개 (배포 파일, 테스트, YAML 프리셋 포함)
- 직접 구현 → PyCaret/AutoKeras 래핑 (코드량 70% 감소)
- 4개 독립 모듈 → 2개 판매 상품으로 시장 집중
- exe 대신 Streamlit Cloud + Docker 배포

---

## Claude Code 실행 프롬프트 (복붙용)

```
이 스펙 문서(v2)를 읽고 Phase 1을 구현해줘.

핵심 변경사항:
- ML은 PyCaret 래핑 (직접 구현 X)
- DL은 AutoKeras 래핑 (선택적 설치)
- 한국어 NLP(Kiwi)가 전체 프로젝트의 핵심 차별점

규칙:
- Python 타입힌트 필수, Black 포매터 기준
- 모든 클래스/함수에 docstring
- 에러 핸들링 필수 (try/except + structlog)
- 환경변수는 .env + pydantic-settings
- 테스트는 pytest로 작성하고 통과 확인까지
- CSV 내보내기는 UTF-8 BOM (비개발자 엑셀 호환)

구현 후 납품 체크리스트 점검 결과를 알려줘.
```
