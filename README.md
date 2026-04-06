# jinyoung-toolkit

데이터 분석 자동화 도구 모음. 리뷰 감성분석과 AutoML 리포트 생성을 웹 UI 및 CLI로 제공한다.

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
├── app.py                    # Streamlit 메인 허브
├── review_analyzer/          # 리뷰 분석기
│   ├── app.py               # Streamlit UI
│   ├── analyzer.py          # 분석 엔진
│   ├── cli.py               # CLI
│   └── crawler/             # 웹 크롤러
├── automl_reporter/          # AutoML 리포트
│   ├── app.py               # Streamlit UI
│   ├── runner.py            # AutoML 파이프라인
│   ├── report_builder.py    # PDF 리포트 빌더
│   ├── feature_inspector.py # 데이터 프로파일링
│   ├── dl_option.py         # 딥러닝 옵션(AutoKeras)
│   └── cli.py               # CLI
├── shared/                   # 공통 모듈
│   ├── ui_components.py     # Streamlit 컴포넌트
│   ├── report_generator.py  # PDF 엔진
│   ├── delivery.py          # 납품 패키지
│   └── logger.py            # 구조화 로깅
├── tests/
├── scripts/
├── Dockerfile
└── docker-compose.yml
```

---

## 설치

```bash
pip install -r requirements.txt
```

PyCaret을 사용하려면 별도 설치가 필요하다.

```bash
pip install pycaret
```

---

## 실행

### Streamlit (웹 UI)

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 사이드바에서 도구를 선택한다.

### CLI — 리뷰 분석기

```bash
python -m review_analyzer --help
```

### CLI — AutoML 리포트 생성

```bash
python -m automl_reporter run --input data.csv --target target
```

### CLI — 데이터 검사

```bash
python -m automl_reporter inspect --input data.csv
```

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
