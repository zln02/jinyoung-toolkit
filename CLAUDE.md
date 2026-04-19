# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

한국어 리뷰 감성분석 + AutoML 리포트 생성기. Streamlit 허브(`app.py`) + 독립 실행 CLI 2개. Cloud Run 배포 타겟.

## 절대 규칙
- `.env` 커밋 금지 (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GCP_PROJECT_ID`)
- `output/` 산출물(PDF·ZIP·pkl) 커밋 금지
- 크롤러 수정 시 `CRAWL_DELAY_SECONDS` / `MAX_RETRIES` 하한 지키기 — 대상 사이트에 과부하 주지 않도록
- `review_analyzer/selector_inferer.py`는 LLM 기반 셀렉터 자동 추론 — 결과 프리셋 저장 시 사람이 한 번 검수하고 커밋

## Commands

```bash
cd ~/jinyoung-toolkit && source .venv/bin/activate

# Streamlit 허브 (:8501) — 두 도구 모두 사이드바에서 전환
streamlit run app.py

# 개별 도구 Streamlit
streamlit run review_analyzer/app.py
streamlit run automl_reporter/app.py

# CLI — 리뷰 분석기 (4개 서브커맨드)
python -m review_analyzer list-presets
python -m review_analyzer crawl   --preset naver_shopping --urls "..." --max-pages 50
python -m review_analyzer analyze --input reviews.csv
python -m review_analyzer full    --preset naver_shopping --urls "..."

# CLI — AutoML
python -m automl_reporter inspect --input data.csv
python -m automl_reporter run     --input data.csv --target churn --top-n 10

# 쉘 래퍼
bash scripts/run_review_analyzer.sh
bash scripts/run_automl_reporter.sh

# 테스트 (pyproject 설정상 3개 경로 자동 수집)
pytest -v --cov                              # tests/, review_analyzer/tests/, automl_reporter/tests/
pytest tests/test_integration.py -v
pytest review_analyzer/tests/ -k "preset"

# Docker / Cloud Run
docker compose up --build                    # :8501
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/jinyoung-toolkit
gcloud run deploy jinyoung-toolkit --image gcr.io/$GCP_PROJECT_ID/jinyoung-toolkit --port 8501 --allow-unauthenticated
```

## Architecture

**두 독립 파이프라인** — 공통 모듈은 `shared/`로만 공유. 상호 import 금지(순환 피함).

```
review_analyzer/                          automl_reporter/
  crawler/engine.py + drivers.py            feature_inspector.py  # 데이터 프로파일링
  preset_loader.py (presets/*.yaml)         runner.py             # 학습 파이프라인 (PyCaret optional)
  selector_inferer.py  (LLM → selector)     visualizer.py         # Plotly 차트
  analyzer.py   (감성/키워드)                dl_option.py          # AutoKeras 옵션
  comparator.py (다중 상품 비교)             report_builder.py     # PDF 조립
      ↓                                         ↓
  shared/report_generator.py (fpdf2) ← shared/korean_nlp.py (kiwipiepy)
  shared/delivery.py (ZIP 납품)         shared/ui_components.py (Streamlit 공용)
  shared/exporters.py (CSV/Excel)       shared/config.py (env 로더)
  shared/comparison_report_generator.py shared/logger.py (구조화 로깅)
```

**Streamlit 허브** (`app.py`): 사이드바에서 두 도구 선택. 각 도구의 `app.py`를 서브페이지로 로드.

**크롤러 계층** (`review_analyzer/crawler/`):
- `drivers.py` — httpx / Selenium / API 드라이버 스위처 (`CHROME_DRIVER_PATH=auto` 시 `webdriver-manager` 자동 설치)
- `engine.py` — 페이지네이션 / 재시도 / 파싱
- `rate_limiter.py` — `CRAWL_DELAY_SECONDS`·`MAX_RETRIES` 준수

**프리셋 시스템** (`review_analyzer/presets/*.yaml`): 사이트별 셀렉터·URL 패턴. 새 사이트는 `custom_template.yaml` 복제 또는 `selector_inferer.py`로 자동 생성(Claude Haiku 사용).

**감성 분석 레벨**:
- Level 1(룰) — 기본, API 없이 동작
- Level 2(사전) — `shared/korean_nlp.py` 키워드 기반
- Level 3(LLM) — `OPENAI_API_KEY` 있을 때 `gpt-4o-mini` 배치 호출 (`SENTIMENT_BATCH_SIZE=10`)

**AutoML 파이프라인** (`automl_reporter/runner.py`):
- 타겟 지정 시: binary/multiclass classification 또는 regression 자동 감지
- 타겟 생략 시: 군집화 모드
- `PyCaret` 설치 시 모델 비교 확장, 없으면 `scikit-learn` 기본 세트
- 결과: `best_model.pkl` + `automl_report.pdf`

## 환경변수

`.env.example` 복사 기준 — 필수는 아님(없어도 Level 1/기본 동작):

| 변수 | 기본 | 용도 |
|------|------|------|
| `LOG_LEVEL` | `INFO` | — |
| `OUTPUT_DIR` | `./output` | 결과물 출력 경로 |
| `REPORT_AUTHOR` | `박진영` | PDF 작성자명 |
| `CHROME_DRIVER_PATH` | `auto` | Selenium 드라이버 경로 |
| `CRAWL_DELAY_SECONDS` | `1.5` | 요청 간격(하한 지킬 것) |
| `MAX_RETRIES` | `3` | 크롤링 재시도 |
| `REQUEST_TIMEOUT` | `30` | HTTP 타임아웃 |
| `OPENAI_API_KEY` | — | Level 3 감성분석 |
| `SENTIMENT_MODEL` | `gpt-4o-mini` | LLM 모델 |
| `SENTIMENT_BATCH_SIZE` | `10` | LLM 배치 크기 |
| `ANTHROPIC_API_KEY` | — | 셀렉터 자동 추론 |
| `SELECTOR_INFERENCE_MODEL` | `claude-haiku-4-5-20251001` | 추론용 모델 |
| `RANDOM_SEED` | `42` | ML 재현성 |
| `TEST_SIZE` | `0.3` | 테스트셋 비율 |
| `GCP_PROJECT_ID` / `GCP_REGION` | — / `asia-northeast3` | Cloud Run 배포 |

## Code Rules

1. 외부 호출(`httpx`, `selenium`, `openai`, `anthropic`) 반드시 try/except + 재시도
2. `print()` 금지 — `shared/logger.py get_logger()` 사용
3. 출력 파일은 반드시 `OUTPUT_DIR` 하위에 (Streamlit에서 다운로드 링크 제공)
4. 한국어 처리는 `shared/korean_nlp.py` 경유 (kiwipiepy 인스턴스 싱글톤)
5. 새 프리셋 추가 시 `presets/*.yaml` 형식 맞추고 `list-presets` 출력 확인
6. PDF 리포트는 `shared/report_generator.py` 통합 엔진 사용 — 도구별 커스텀 렌더러 만들지 말 것

## 리스크 파일

| 파일 | 이유 |
|------|------|
| `review_analyzer/crawler/engine.py` | 크롤링 속도/재시도 — 대상 사이트 차단·법적 리스크 |
| `review_analyzer/crawler/drivers.py` | Selenium 드라이버 버전 호환성 민감 |
| `review_analyzer/selector_inferer.py` | LLM 호출 과금 + 셀렉터 오추론 시 전체 크롤링 실패 |
| `automl_reporter/runner.py` | PyCaret optional 의존 — try/import 분기 유지 |
| `shared/korean_nlp.py` | kiwipiepy 인스턴스 초기화 느림 — 싱글톤 깨지 말 것 |
