# jinyoung-toolkit — 문서 검증 및 코드 수정 완료 보고서

> **작성일**: 2026-04-07
> **작성자**: Claude Code (Opus 4.6)
> **대상 커밋**: `5119f9a` (feat: Phase 4)
> **작업 범위**: README.md 작성, IMPLEMENTATION_SPEC_v2.md 코드-문서 정합성 수정, 버그 수정

---

## 1. 작업 요약

Phase 0~4 구현 완료 후, 문서(README.md, IMPLEMENTATION_SPEC_v2.md)가 실제 코드와 일치하는지 전수 검증하고 불일치를 수정했다.

| 항목 | 수치 |
|------|------|
| README.md 수정 | 신규 작성 (191줄) |
| IMPLEMENTATION_SPEC_v2.md 수정 | 10건 |
| 코드 버그 수정 | 1건 (`review_analyzer/app.py:53`) |
| 영향 받은 파일 | 3개 |

---

## 2. README.md — 신규 작성

Phase 4에서 프로젝트 최종 구조에 맞는 README.md를 새로 작성했다.

| 섹션 | 내용 |
|------|------|
| 구성 | 2개 도구 (리뷰 분석기, AutoML 리포트) 테이블 |
| 디렉토리 구조 | 실제 파일 트리와 1:1 대응 (56개 파일) |
| 설치 | venv + requirements.txt + .env 설정 |
| 환경변수 | 16개 변수 테이블 (.env.example 기반) |
| 실행 | Streamlit UI / CLI / 쉘 스크립트 4가지 방법 |
| Docker | docker compose up --build |
| Cloud Run | gcloud builds submit + deploy 명령 |
| 테스트 | pytest -v --cov |

---

## 3. IMPLEMENTATION_SPEC_v2.md — 수정 내역 (10건)

### 3.1 프로젝트 구조 메타데이터

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 1 | 파일 수 통계 | `~40개 → ~25개 (37% 감소)` | `현재 56개 (배포 파일, 테스트, YAML 프리셋 포함)` | 실제 파일 수와 불일치 |

### 3.2 의존성 관리

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 2 | pyproject.toml | Poetry 포맷 (`[tool.poetry]`) 40줄 | PEP 517 표준 (`[project]`) 10줄 + pytest 설정 | 실제는 requirements.txt 기반, Poetry 미사용 |

### 3.3 리뷰 분석기 (review_analyzer)

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 3 | CrawlResult.data | `data: pd.DataFrame` (주석 없음) | `data: pd.DataFrame  # ⚠️ 필드명 data (dataframe 아님)` | app.py에서 `.dataframe` 접근 버그 문서화 |
| 4 | AnalysisResult.insights | `insights: list[str]  # AI 생성 인사이트 3줄` | `insights: list[str] = field(default_factory=list)  # 규칙 기반 인사이트 3줄` | 실제는 AI가 아닌 규칙 기반, default_factory 누락 |
| 5 | ReviewAnalyzer Usage | `analyzer = ReviewAnalyzer(config)` | `analyzer = ReviewAnalyzer(text_column="content", rating_column="rating")` | 생성자 시그니처 불일치 |
| 6 | save_delivery_package | `(crawl_result, analysis_result, output_dir)` | `(raw_df, result, output_dir, project_name)` | 실제 메서드 시그니처와 불일치 |
| 7 | sentiment_method | `rating_based \| keyword_based \| hybrid` | `rating_based \| keyword_based` + hybrid 미구현 주석 | hybrid 옵션 미구현 |
| 8 | PresetLoader | docstring 없음 | `__init__`, `load()` Raises 문서화 | 스키마 검증 로직 미문서화 |
| 9 | LegalComplianceChecker 주석 | 비격식 표현 (`이거 안 하면`) | 격식 표현 (`이를 수행하지 않으면`) | 문서 톤 통일 |

### 3.4 AutoML 리포트 (automl_reporter)

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 10 | save_delivery_package → save_best_model | `save_delivery_package(result)` 납품 패키지 생성 | `save_best_model(output_path)` 모델 저장 | 실제 구현은 save_best_model만 존재 |

### 3.5 공유 엔진 (shared)

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| — | DEFAULT_STOPWORDS 타입 | `set[str]` | `frozenset[str]` | 실제 코드는 frozenset 사용 |
| — | config.py 섹션 | 없음 | AppSettings 전체 스펙 추가 | shared/config.py가 문서에 미반영 |

---

## 4. 코드 버그 수정

### `review_analyzer/app.py:53` — AttributeError

```python
# 수정 전 (버그)
return crawl_result.dataframe

# 수정 후
return crawl_result.data
```

**원인**: `CrawlResult` dataclass의 필드명은 `data`이나 app.py에서 `.dataframe`으로 접근.
크롤링 실행 시 `AttributeError: 'CrawlResult' object has no attribute 'dataframe'` 발생.

**영향도**: 크롤링 기능을 사용하는 모든 사용자에게 영향 (CSV 업로드는 무관).

### `review_analyzer/app.py:323` — StreamlitAPIException

```python
# 수정 전 (버그)
st.set_page_config(...)

# 수정 후
try:
    st.set_page_config(...)
except st.errors.StreamlitAPIException:
    pass  # 루트 허브에서 이미 호출됨
```

**원인**: 메인 허브(`app.py`)에서 `set_page_config`을 호출한 뒤 리뷰 분석기를 로드하면 중복 호출 에러 발생.

---

## 5. 전후 비교 테이블

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| README.md | 없음 | 191줄, 실제 구조와 1:1 대응 |
| SPEC 파일 수 통계 | ~25개 (허위) | 56개 (정확) |
| SPEC pyproject.toml | Poetry 포맷 (미사용) | PEP 517 표준 (실제) |
| SPEC CrawlResult 필드 | 주석 없음 | `.data` 필드명 명시 + 경고 |
| SPEC AnalysisResult.insights | AI 생성 (허위) | 규칙 기반 (정확) |
| SPEC ReviewAnalyzer 시그니처 | `config` 인자 | `text_column`, `rating_column` 인자 |
| SPEC save_delivery_package | 존재 (허위) | `save_best_model`로 교체 |
| SPEC sentiment hybrid | 지원 (허위) | 미구현 명시 |
| 크롤링 버그 | `.dataframe` (AttributeError) | `.data` (정상) |
| set_page_config | 중복 호출 에러 | try/except 방어 |

---

## 6. UI 개선 점검 결과

> critique 스킬로 Streamlit UI 4개 파일을 분석한 결과 도출된 개선 항목과 수정 내역.

### 6.1 Design Health Score

| 카테고리 | 점수 | 만점 |
|----------|------|------|
| Visual Hierarchy | 5 | 10 |
| Information Architecture | 6 | 10 |
| Emotional Resonance | 4 | 10 |
| Cognitive Load | 6 | 10 |
| **총점** | **21** | **40** |

### 6.2 우선순위별 개선 항목

| 우선순위 | 파일 | 문제 | 해결 |
|----------|------|------|------|
| P1 | `app.py` | `unsafe_allow_html=True` XSS 위험, URL 하드코딩 | `st.link_button()` + 환경변수 전환 |
| P1 | `review_analyzer/app.py` | Step 진행 표시 없음, 에러 메시지 raw exception 노출 | `render_step_indicator()` + `render_error()` 적용 |
| P1 | `automl_reporter/app.py` | Step 진행 표시 없음, 에러 메시지 raw exception 노출 | `render_step_indicator()` + `render_error()` 적용 |
| P2 | `shared/ui_components.py` | CSV만 지원, 메트릭 열 수 하드코딩 | Excel 지원 추가, `num_cols` 파라미터화 |
| P2 | `app.py` | 랜딩 페이지 없음 — 바로 도구 화면 진입 | 홈 카드 2개 + 도구 설명 사이드바 추가 |
| P3 | `review_analyzer/app.py` | 워드클라우드 빈 탭 3개 표시, 샘플 데이터 없음 | 동적 탭 생성 + 샘플 체험 버튼 추가 |

### 6.3 수정 완료 내역

| # | 변경 | 대상 파일 |
|---|------|-----------|
| 1 | `render_step_indicator()` 신규 추가 | `shared/ui_components.py` |
| 2 | `render_error()` + `_ERROR_MAP` 신규 추가 | `shared/ui_components.py` |
| 3 | `render_file_uploader()` Excel 지원 (xlsx/xls) | `shared/ui_components.py` |
| 4 | `render_metrics()` `num_cols` 파라미터화 | `shared/ui_components.py` |
| 5 | `uis_url` 환경변수 추가 | `shared/config.py`, `.env.example` |
| 6 | 랜딩 페이지 + `st.link_button()` + 도구 설명 | `app.py` |
| 7 | Step indicator + 샘플 데이터 + 에러 개선 + 워드클라우드 동적 탭 | `review_analyzer/app.py` |
| 8 | Step indicator + 에러 개선 + 메트릭 설명 expander | `automl_reporter/app.py` |

---

## 7. 문서-코드 정합성 2차 수정 (6건)

> **작업일**: 2026-04-07
> **트리거**: 코드 리뷰에서 IMPLEMENTATION_SPEC_v2.md와 실제 코드 간 불일치 6건 추가 발견

### 7.1 스펙 문서 수정 (4건)

| # | 위치 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 1 | Dockerfile (SPEC:1361-1362) | `poetry install` | `pip install -r requirements.txt` | 실제 Dockerfile은 pip 기반, poetry.lock 없음 |
| 4 | 와이어프레임 (SPEC:610) | `감성 분석: ○ 평점 기반  ● 하이브리드` | `💡 감성 분석: 평점 컬럼 유무에 따라 자동 선택` | 하이브리드 미구현, rating_column 유무로 자동 선택 |
| 5 | 크롤러/AutoML (SPEC:551-589, 776-782) | `crawl_with_streamlit_progress()` + `run_with_progress()` | 4줄 주석 + 1줄 주석 | 이중 실행 버그 코드 제거, `run()` + `st.spinner()` 명시 |
| 6 | AutoML Usage (SPEC:749-753) | `save_delivery_package(result)` | `DeliveryPackage` 조립 5줄 예시 | 미구현 메서드 대신 실제 사용법 문서화 |

### 7.2 코드 수정 (1건 + 테스트 연동)

| # | 파일 | 수정 전 | 수정 후 | 이유 |
|---|------|---------|---------|------|
| 2-3 | `shared/config.py` | `crawl_delay=1.0, model=KR-FinBert-SC, batch=32, test=0.2` | `crawl_delay=1.5, model=gpt-4o-mini, batch=10, test=0.3` | `.env.example` 정본과 불일치 |
| — | `tests/test_shared.py` | 이전 기본값 assert | 새 기본값 assert | config.py 변경에 따른 테스트 연동 |

### 7.3 검증 결과

| 검증 항목 | 결과 |
|-----------|------|
| `get_settings()` 기본값 출력 | `1.5 gpt-4o-mini 10 0.3` |
| `pytest` 전체 (55건) | ALL PASSED |
| SPEC `poetry` 검색 | 158행 주석 1건만 (Poetry 아님 설명) |
| SPEC `하이브리드`/`hybrid` 검색 | 465행 미구현 경고 1건만 |
| SPEC `run_with_progress` 검색 | 275행 메서드 선언 + 주석 2건만 (사용 코드 없음) |
