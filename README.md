# jinyoung-toolkit

[![CI](https://github.com/zln02/jinyoung-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/zln02/jinyoung-toolkit/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/zln02/jinyoung-toolkit/graph/badge.svg)](https://codecov.io/gh/zln02/jinyoung-toolkit)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](./Dockerfile)

데이터 분석 자동화 도구 모음. 리뷰 감성분석과 AutoML 리포트 생성을 웹 UI 및 CLI로 제공한다.

🌐 **라이브 데모**: http://34.64.217.243:8501

---

## 구성

| 도구 | 설명 |
|------|------|
| **리뷰 분석기** (`review_analyzer`) | CSV/크롤링 → 감성분석 → 키워드 추출 → PDF 리포트 → 납품 패키지(ZIP) |
| **AutoML 리포트** (`automl_reporter`) | CSV → 자동 모델학습 → Feature Importance → PDF 리포트 → 모델(.pkl) 저장 |

**스택:** Python 3.11, Streamlit, scikit-learn, PyCaret(optional), fpdf2, Plotly, kiwipiepy

---

## 디렉토리 구조

```
jinyoung-toolkit/
├── app.py                          # Streamlit 메인 허브
├── review_analyzer/                # 리뷰 분석기
│   ├── __main__.py                # python -m 진입점
│   ├── app.py                     # Streamlit UI
│   ├── analyzer.py                # 분석 엔진
│   ├── cli.py                     # CLI
│   ├── preset_loader.py           # 프리셋 로더
│   ├── presets/                   # 크롤링 프리셋 (YAML)
│   │   ├── naver_shopping.yaml
│   │   ├── coupang_reviews.yaml
│   │   ├── google_play.yaml
│   │   └── custom_template.yaml
│   ├── crawler/                   # 웹 크롤러
│   │   ├── engine.py             # 크롤링 엔진
│   │   ├── drivers.py            # WebDriver 관리
│   │   └── rate_limiter.py       # 요청 속도 제한
│   └── tests/                     # 리뷰 분석기 테스트
├── automl_reporter/                # AutoML 리포트
│   ├── __main__.py                # python -m 진입점
│   ├── app.py                     # Streamlit UI
│   ├── runner.py                  # AutoML 파이프라인
│   ├── report_builder.py          # PDF 리포트 빌더
│   ├── feature_inspector.py       # 데이터 프로파일링
│   ├── visualizer.py              # 차트 시각화
│   ├── dl_option.py               # 딥러닝 옵션(AutoKeras)
│   ├── cli.py                     # CLI
│   └── tests/                     # AutoML 리포트 테스트
├── shared/                         # 공통 모듈
│   ├── config.py                  # 설정 관리
│   ├── korean_nlp.py              # 한국어 NLP (형태소, 불용어)
│   ├── ui_components.py           # Streamlit 컴포넌트
│   ├── report_generator.py        # PDF 엔진
│   ├── exporters.py               # CSV/Excel 내보내기
│   ├── delivery.py                # 납품 패키지
│   └── logger.py                  # 구조화 로깅
├── tests/                          # 통합 테스트
│   └── fixtures/                  # 테스트 데이터
├── scripts/                        # 실행 스크립트
│   ├── run_review_analyzer.sh
│   └── run_automl_reporter.sh
├── output/                         # 결과물 출력 디렉토리
├── .env.example                    # 환경변수 템플릿
├── .streamlit/config.toml          # Streamlit 설정
├── pyproject.toml                  # 프로젝트 메타데이터
├── requirements.txt
├── Procfile                        # Cloud Run 실행 명령
├── Dockerfile
└── docker-compose.yml
```

---

## 설치

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 필요한 값을 채운다 (아래 "환경변수" 섹션 참조)
```

PyCaret을 사용하려면 별도 설치가 필요하다.

```bash
pip install pycaret
```

---

## 환경변수

`.env.example`을 복사하여 `.env`로 만든 뒤, 아래 값을 설정한다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LOG_LEVEL` | `INFO` | 로그 레벨 (DEBUG, INFO, WARNING, ERROR) |
| `OUTPUT_DIR` | `./output` | 결과물 출력 경로 |
| `REPORT_AUTHOR` | `박진영` | PDF 리포트 작성자명 |
| `CHROME_DRIVER_PATH` | `auto` | ChromeDriver 경로 (`auto`면 자동 설치) |
| `CRAWL_DELAY_SECONDS` | `1.5` | 크롤링 요청 간 대기 시간(초) |
| `MAX_RETRIES` | `3` | 크롤링 재시도 횟수 |
| `REQUEST_TIMEOUT` | `30` | HTTP 요청 타임아웃(초) |
| `OPENAI_API_KEY` | — | LLM 감성분석(Level 3) 사용 시 필요 |
| `SENTIMENT_MODEL` | `gpt-4o-mini` | LLM 감성분석 모델명 |
| `SENTIMENT_BATCH_SIZE` | `10` | LLM 배치 크기 |
| `RANDOM_SEED` | `42` | ML 랜덤 시드 |
| `TEST_SIZE` | `0.3` | 테스트셋 비율 |
| `GCP_PROJECT_ID` | — | Cloud Run 배포 시 GCP 프로젝트 ID |
| `GCP_REGION` | `asia-northeast3` | Cloud Run 리전 |

---

## 실행

### 1. Streamlit (웹 UI)

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 사이드바에서 도구를 선택한다.

### 2. CLI — 리뷰 분석기

```bash
python -m review_analyzer --help
```

4개 서브커맨드를 제공한다.

#### `list-presets` — 프리셋 목록 조회

```bash
python -m review_analyzer list-presets
```

출력 예시:

```
사용 가능한 프리셋:
  naver_shopping    네이버 쇼핑 리뷰
  coupang_reviews   쿠팡 상품 리뷰
  google_play       Google Play 앱 리뷰
  custom_template   커스텀 템플릿
```

#### `crawl` — 크롤링 전용

| 옵션 | 타입 | 기본값 | 필수 | 설명 |
|------|------|--------|:----:|------|
| `--preset` | str | — | O | 프리셋 이름 (`list-presets`로 확인) |
| `--urls` | str (복수) | — | O | 크롤링 대상 URL (여러 개 가능) |
| `--output` | Path | `./output` | | 출력 디렉토리 |
| `--max-pages` | int | `100` | | 최대 페이지 수 |
| `--driver` | str | `httpx` | | 드라이버 (`httpx` / `selenium` / `api`) |

```bash
# 네이버 쇼핑 리뷰 크롤링
python -m review_analyzer crawl \
  --preset naver_shopping \
  --urls "https://shopping.naver.com/..." \
  --max-pages 50 \
  --output ./output/naver

# 여러 URL 동시 크롤링
python -m review_analyzer crawl \
  --preset coupang_reviews \
  --urls "https://coupang.com/product/1" "https://coupang.com/product/2" \
  --driver selenium
```

#### `analyze` — CSV 분석 전용

| 옵션 | 타입 | 기본값 | 필수 | 설명 |
|------|------|--------|:----:|------|
| `--input` | Path | — | O | 입력 CSV 파일 경로 |
| `--output` | Path | `./output` | | 출력 디렉토리 |
| `--text-column` | str | `content` | | 텍스트 컬럼명 |
| `--rating-column` | str | `rating` | | 평점 컬럼명 (없으면 `none`) |
| `--report` / `--no-report` | bool | `True` | | PDF 리포트 생성 여부 |
| `--package` / `--no-package` | bool | `True` | | 납품 패키지(ZIP) 생성 여부 |

```bash
# 기본 분석 (리포트 + 패키지 포함)
python -m review_analyzer analyze --input reviews.csv

# 커스텀 컬럼 지정, 리포트만 생성
python -m review_analyzer analyze \
  --input data.csv \
  --text-column "review_text" \
  --rating-column "score" \
  --no-package
```

출력 파일: `output/report.pdf`, `output/{project}.zip` (패키지 활성화 시)

#### `full` — 크롤링 + 분석 일괄

| 옵션 | 타입 | 기본값 | 필수 | 설명 |
|------|------|--------|:----:|------|
| `--preset` | str | — | O | 프리셋 이름 |
| `--urls` | str (복수) | — | O | 크롤링 대상 URL |
| `--output` | Path | `./output` | | 출력 디렉토리 |

```bash
python -m review_analyzer full \
  --preset naver_shopping \
  --urls "https://shopping.naver.com/..." \
  --output ./output/full_run
```

### 3. CLI — AutoML 리포트

```bash
python -m automl_reporter --help
```

2개 서브커맨드를 제공한다.

#### `inspect` — 데이터 프로파일링

| 옵션 | 타입 | 기본값 | 필수 | 설명 |
|------|------|--------|:----:|------|
| `--input` | Path | — | O | 입력 CSV 파일 경로 |

```bash
python -m automl_reporter inspect --input data.csv
```

출력 예시:

```
=== 데이터 프로파일 ===
Shape: (1200, 15)
DTypes: float64(8), int64(3), object(4)

컬럼별 결측률:
  age         0.0%
  income      2.3%
  region     12.1%

추천 타겟: churn (binary, 2 classes)
전처리 제안:
  - region: 결측률 높음 → 최빈값 대체 또는 제거 권장
  - income: 결측 28건 → 중앙값 대체 권장
```

#### `run` — AutoML 파이프라인

| 옵션 | 타입 | 기본값 | 필수 | 설명 |
|------|------|--------|:----:|------|
| `--input` | Path | — | O | 입력 CSV 파일 경로 |
| `--target` | str | `None` | | 타겟 컬럼명 (생략 시 군집화 모드) |
| `--output` | Path | `./output` | | 출력 디렉토리 |
| `--top-n` | int | `5` | | 비교할 상위 N개 모델 수 |
| `--task-type` | str | 자동 감지 | | 태스크 유형 강제 지정 |
| `--report` / `--no-report` | bool | `True` | | PDF 리포트 생성 여부 |

`--task-type` 허용값: `binary_classification`, `multiclass_classification`, `regression`, `clustering`

```bash
# 자동 감지 (타겟 컬럼 지정)
python -m automl_reporter run --input data.csv --target churn

# 상위 10개 모델 비교, 회귀 강제
python -m automl_reporter run \
  --input sales.csv \
  --target revenue \
  --top-n 10 \
  --task-type regression \
  --output ./output/sales

# 군집화 (타겟 없음)
python -m automl_reporter run --input customers.csv
```

출력 예시:

```
[1/4] 데이터 전처리 완료 (1200행, 12피처)
[2/4] 모델 학습 중... top-5 비교
[3/4] 최적 모델: LGBMClassifier (AUC=0.923)
[4/4] 리포트 저장 → output/automl_report.pdf

출력 파일:
  output/automl_report.pdf   PDF 리포트
  output/best_model.pkl      학습된 모델
```

### 4. 쉘 스크립트

```bash
bash scripts/run_review_analyzer.sh
bash scripts/run_automl_reporter.sh
```

### 5. 출력 파일 요약

| 도구 | 출력물 | 설명 |
|------|--------|------|
| 리뷰 분석기 | `report.pdf` + `{project}.zip` | 감성분석 리포트 + 납품 패키지 |
| AutoML | `automl_report.pdf` + `best_model.pkl` | 모델 비교 리포트 + 최적 모델 |

---

## Docker 실행

```bash
docker compose up --build
```

`http://localhost:8501` 에서 접속 가능하다.

---

## Cloud Run 배포

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/jinyoung-toolkit
gcloud run deploy jinyoung-toolkit \
  --image gcr.io/PROJECT_ID/jinyoung-toolkit \
  --port 8501 \
  --allow-unauthenticated
```

`PROJECT_ID` 를 실제 GCP 프로젝트 ID로 교체한다.

---

## 테스트

```bash
pytest -v --cov
```

---

## 라이선스

MIT

---

## 2026-05-28 업데이트 (요약)

> 이번 사이클에 추가·개선된 기능. 자세한 검증은 `CRAWLING_AUDIT_REPORT.md` · `SITE_VERIFICATION.md` 참고.

### 리뷰 분석기 (`review_analyzer`)
- **감성 분석 개선**: `SentimentConfig` 도입 — `auto`(평점 우선, 실패 시 키워드 fallback) / `rating` / `keyword` 3모드 + 부정어 반전 처리. 평점이 `"만족도 : 100%"`처럼 비표준이라 모두 중립으로 떨어지던 버그 수정. UI에 "고급 설정"(분석 방식·평점 척도·긍부정 경계 슬라이더) 추가.
- **🔬 고급 분석 탭 신설** (`review_analyzer/advanced_analyzer.py` + `ui/advanced_tab.py`):
  - TF-IDF 기반 **KMeans 군집화** (silhouette로 k 자동 선택, 클러스터별 대표 키워드·대표 리뷰)
  - **LDA 토픽 모델링** (sklearn)
  - **PCA / t-SNE 2D 시각화** (plotly 산점도)
  - **통계 요약** (silhouette·길이 분포·평점×감성 교차표)
- **다중 키워드 검색 크롤**: 검색형 프리셋(예: `naver_blog`)에서 키워드를 줄바꿈/쉼표로 여러 개 입력 → 각각 크롤 후 `_keyword` 컬럼으로 합쳐 반환.
- **공공데이터 API 인프라**: `APIDriver`에 `query_params` + 쿼리 인증(`auth_param`) 지원, `config.public_data_api_key`(.env) 폴백, `presets/public_data_example.yaml` 템플릿 추가 → data.go.kr 같은 공공 API를 같은 프리셋 패턴으로 수집.

### AutoML 리포트 (`automl_reporter`)
- **업로드 오류 수정**: 한글 엑셀 CSV(cp949/euc-kr) 인코딩 폴백(`utf-8-sig→cp949→euc-kr→utf-8`), `runner`의 BOM 처리(`encoding="utf-8-sig"`)로 컬럼명 오염 KeyError 해결.
- **'📝 텍스트 피처 포함' UI 옵션 추가**: 수치 컬럼이 부족한 텍스트 위주 데이터(리뷰 등)에서 텍스트 컬럼을 TF-IDF로 변환해 모델 입력에 사용. 비수치 데이터 명시적 가드 + 친절한 에러 메시지.
- 샘플 시연: `samples/automl_text_demo.csv`(한글 리뷰 40행) — 텍스트 옵션 ON 시 LogisticRegression / accuracy ≈ 87.5%.

### 메인 허브 (`app.py`)
- **익명 이용 현황 집계** (`shared/visitor_stats.py`): IP·식별자 미저장. 세션 기반 SQLite 카운터로 누적/오늘 접속·분석 실행 횟수 + 최근 활동 시각을 사이드바와 홈 상단에 표시.

### 검증 문서
- `CRAWLING_AUDIT_REPORT.md` — 도메인 기준 감사 (24점 만점 중 8점, 갭 분석)
- `SITE_VERIFICATION.md` — 프리셋 15종 동작 가능성 실측 (selenium 미설치로 12종 현 환경 동작불가, `apple_app_store`·공공API가 현실적 데모 경로)

