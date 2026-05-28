# CLAUDE.md

한국어 리뷰 감성분석 + AutoML 리포트. Streamlit 허브(`app.py`) + CLI 2개. Cloud Run 배포 타겟.

## 절대 규칙
- `.env` 커밋 금지 (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GCP_PROJECT_ID`)
- `output/` 산출물(PDF·ZIP·pkl) 커밋 금지
- 크롤러: `CRAWL_DELAY_SECONDS`/`MAX_RETRIES` 하한 지키기 — 사이트 과부하·차단 방지
- `selector_inferer.py` LLM 추론 결과 프리셋 저장 시 사람 검수 후 커밋
- `print()` 금지 → `shared/logger.py get_logger()`

## 리스크 파일
- `crawler/engine.py`·`drivers.py` — 차단·법적 리스크
- `selector_inferer.py` — LLM 과금 + 오추론 시 전체 크롤링 실패
- `automl_reporter/runner.py` — PyCaret optional 분기 유지
- `shared/korean_nlp.py` — kiwipiepy 싱글톤 깨지 말 것

## 명령
`streamlit run app.py` (:8501), `pytest -v --cov`
