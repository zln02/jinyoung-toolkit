# CRAWLING_AUDIT_REPORT.md

> **감사 메타**
> - **감사 대상**: `jinyoung-toolkit` — 상품 리뷰 크롤러 + 한국어 NLP 분석 (Streamlit, http://34.64.217.243:8501, pid 213101)
> - **감사 기준**: LG ThinQ Workspace Sentinel 체크리스트 (사무실 감염병 예측 도메인)
> - **감사일**: 2026-05-27 / 점수 보수적 (애매하면 ❌)
> - **⚠️ 도메인 불일치**: 대상은 **상품 리뷰 크롤러**, 기준은 **감염병 예측 시스템**이다. 두 목적이 달라 Sentinel 전용 항목(KOWAS·페르소나·선행성 등)은 코드 자체가 없어 대부분 ❌가 정확한 결과다. 단 범용 **크롤 인프라·한국어 NLP·토픽모델링·시각화**는 견고하여 Sentinel의 Layer C(정성 수집)·전처리·토픽 분석 **기반으로 재사용 가능**하다. 점수는 "Sentinel 요구 충족도"이므로 낮은 것이 정상이며, 그것이 곧 발표까지의 갭이다.

---

## 0. 시스템 기본 정보

| 항목 | 값 |
|---|---|
| Streamlit 프로세스 PID | ✅ 213101 |
| 앱 진입 파일 | ✅ `app.py` (루트 허브) → `review_analyzer.app.main()` 호출 (app.py:105-107) |
| Python 버전 | ✅ Python 3.11.2 |
| Streamlit 버전 | ✅ 1.56.0 |
| 의존성(핵심) | httpx>=0.27, beautifulsoup4>=4.12, lxml>=5.1, kiwipiepy>=0.18, anthropic>=0.40, pandas>=2.2, scikit-learn>=1.4, fpdf2>=2.7 (selenium은 런타임 동적 import, requirements 미기재 🟡) |
| 데이터 저장 경로/형식 | ✅ CSV/JSON/Excel/Parquet (`shared/exporters.py`) · ❌ SQLite/Postgres 없음 |
| 마지막 git commit | ✅ `dd64ea1` / 2026-04-19 16:53 (단, **현재 작업트리에 미커밋 변경 다수** — 감성 개선·고급분석 탭) |

---

## 1. 크롤링 채널 커버리지 (BX 데이터 수집 체계성 - 5점)

**프리셋 14종 전량 상품/콘텐츠 리뷰 크롤러** (amazon·apple_app_store·cgv·coupang·eleven_st·google_play·melon·naver_blog·naver_cafe·naver_shopping·yanolja·yes24_book·youtube_comments·custom_template). 감염병 신호 채널은 설계 목적이 아니다.

### Layer A — 정량/외부 유행 신호
| 채널 | 구현? | 코드 위치 | 비고 |
|---|---|---|---|
| KOWAS API (질병청 하수) | ❌ | 없음 | 어떤 프리셋·드라이버에도 질병청 엔드포인트 없음 |
| 네이버 DataLab API (검색 트렌드) | ❌ | 없음 | naver_blog/cafe는 페이지 크롤러이며 DataLab 검색량 API 호출 없음 |
| 약국 OTC 데이터 | ❌ | 없음 | UIS 이관 흔적 없음 |

### Layer B — 정량/실내 환경
| 채널 | 구현? | 코드 위치 | 비고 |
|---|---|---|---|
| LG ThinQ Business API | ❌ | 없음 | — |
| 퓨리케어 CADR 스펙시트 | ❌ | 없음 | — |

### Layer C — 정성/Pain Points
| 채널 | 구현? | 코드 위치 | 비고 |
|---|---|---|---|
| 블라인드 | ❌ | 없음 | 프리셋 없음 |
| 네이버 카페/블로그 검색 | 🟡 | `presets/naver_cafe.yaml`, `naver_blog.yaml` | **크롤 인프라는 동작**(블로그 httpx, 카페 selenium). 단 감염병 페르소나 키워드 매핑 없음 — 범용 수집기 |
| YouTube Data API v3 (댓글) | 🟡 | `presets/youtube_comments.yaml` | 댓글 수집 가능하나 **공식 API 아님(Selenium DOM 스크래핑)**, 페르소나 매핑 없음 |
| 네이버 뉴스 API | ❌ | 없음 | 전용 프리셋 없음 |

### Layer D — 시장/제도
| 채널 | 구현? | 코드 위치 | 비고 |
|---|---|---|---|
| KOSIS API | ❌ | 없음 | — |
| 한국공기청정협회 KACA | ❌ | 없음 | — |
| Google Scholar | ❌ | 없음 | — |

**Layer A/B/C/D 종합 점수: 1 / 5점**
(Layer C 3개 채널의 범용 크롤 인프라만 부분 인정. 감염병 채널·페르소나 필터링 전무.)

---

## 2. 페르소나 키워드 매트릭스 (CX 페르소나 - 5점)

`PERSONA_KEYWORDS` 또는 유사 매핑: **전체 코드베이스에 없음** (grep: PERSONA / persona / 김민영 / 박준호 / 이수정 → 0건).

| 페르소나 | 구현? | 키워드 수 | 누락 키워드 |
|---|---|---|---|
| 김민영 (안전보건 담당자) | ❌ | 0개 | ISO 45001, ESG 의무공시, 안전보건 책임 (전부) |
| 박준호 (직원) | ❌ | 0개 | 사무실 환기, 옆자리 기침, 재택 거부 (전부) |
| 이수정 (경영진) | ❌ | 0개 | BCP, 사업연속성, ESG 등급, 콜센터 감염 손실 (전부) |

코드의 분류 차원은 **감성(positive/negative/neutral) 3종**뿐. 페르소나 개념 자체가 없다.

**페르소나 매핑 점수: 0 / 5점**

---

## 3. 전처리 파이프라인 (DX 충실성 - 4점 중)

| 기능 | 구현? | 사용 라이브러리 | 비고 |
|---|---|---|---|
| HTML 정제 (re/BeautifulSoup) | 🟡 | BeautifulSoup4 | `selector_inferer.py:240`, `preset_loader.py:106`의 **크롤러 레이어에서만** script/style 제거. `analyzer.preprocess()` 자체엔 HTML 정제 없음 |
| 한국어 형태소 분석 | ✅ | **Kiwi (kiwipiepy)** | `korean_nlp.py:103` `Kiwi()`, NNG/NNP/VA/VV POS 필터 + 불용어. 강력한 차별점 |
| 중복 제거 (MinHash/해시) | 🟡 | pandas | `analyzer.py:181` `df.drop_duplicates()` — 전체 행 단순 중복만. MinHash/근접중복 ❌ |
| 감정 분석 | ✅(룰) | 자체 키워드+평점 | `analyzer.py:190-219` auto/rating/keyword 3모드 + 부정어 반전. **KcBERT/KOSAC/VADER ML 모델 ❌** |
| 페르소나 자동 분류 | ❌ | — | 없음 |

**전처리 점수: 3 / 4점**
(Kiwi 형태소 ✅ + 감성 ✅ + 중복 🟡 + HTML 🟡 — 항목 충실. 단 ML 감성·근접중복은 미흡.)

---

## 4. 분석 기능 (CX 핵심 고객 경험 + 논리성 - 8점 중)

| 기능 | 구현? | 알고리즘 | 비고 |
|---|---|---|---|
| Pain Point 토픽 모델링 | ✅ | **sklearn LDA** | `advanced_analyzer.py:156-193` `extract_topics()`. BERTopic ❌ |
| 선행성 검증 (시계열 시차) | ❌ | — | Granger/교차상관/시차 코드 전무 |
| 페르소나 × Pain Point 매트릭스 | ❌ | — | 페르소나 부재로 불가 |
| 키워드 시간대별 트렌드 | ❌ | — | date 컬럼은 크롤하나 날짜별 집계·트렌드 분석 없음 |
| 지역별 키워드 분포 | ❌ | — | region 처리 없음 |
| *(실재) KMeans 군집화* | ✅ | TF-IDF+KMeans, silhouette 자동 k | `advanced_analyzer.py:74-153` |
| *(실재) 감성 분석* | ✅ | 평점+키워드 하이브리드 | `analyzer.py:190-219` |
| *(실재) 경쟁사 비교* | ✅ | 병렬 크롤→진단 | `comparator.py:104-401` |
| *(실재) 평점×감성 교차표* | ✅ | crosstab | `advanced_analyzer.py:257-260` |

**분석 점수: 1 / 8점**
(Sentinel 요구 5항목 중 LDA 토픽만 ✅. 선행성·페르소나매트릭스·시간/지역 트렌드 전무 — 발표 논리 핵심인 "선행성"이 빠진 게 치명적. 단 군집·감성·비교 등 범용 분석 자산은 풍부.)

---

## 5. 시각화 기능 (CX + DX 가시화 - 5점)

| 기능 | 구현? | 라이브러리 | 비고 |
|---|---|---|---|
| 워드클라우드 (3종) | ✅ | wordcloud | `analyzer.py:348-376` 전체/긍정/부정 3종. **단 페르소나별 3종 ❌** (감성별임) |
| 워드클라우드 한글 폰트 | ✅ | NanumGothic 자동탐색 | `korean_nlp.py:451-538` `find_korean_font()` |
| 선행성 시계열 차트 | ❌ | — | 없음 |
| 페르소나-페인 히트맵 | ❌ | — | 없음 |
| CAM (직원 하루 Journey) | ❌ | — | Timeline/Journey 코드 없음 |
| 토픽 클러스터 시각화 | ✅ | plotly (PCA/t-SNE 2D) | `advanced_analyzer.py:196-229` + `advanced_tab.py:159-170` |
| Streamlit 구조 | 🟡 | st.tabs 3탭 | `app.py:57-59` 기능 단위 3탭(분석/비교/고급). **멀티페이지(pages/)·페르소나별 페이지 ❌** |

라이브러리: plotly.express ✅, matplotlib ✅(PDF용), seaborn ❌.

**시각화 점수: 2 / 5점**
(워드클라우드+토픽 2D만 ✅. 선행성·히트맵·CAM 등 Sentinel 발표용 시각화 전무.)

---

## 6. 데이터 신뢰성 (BX 신뢰성 - 5점)

| 항목 | 구현? | 코드 위치 | 비고 |
|---|---|---|---|
| 출처 URL/endpoint 기록 | ❌ | `engine.py:344-475` | 결과 DataFrame에 source_url 컬럼 없음 (errors엔 URL 있으나 데이터엔 미주입) |
| 수집 timestamp 저장 | ❌ | `engine.py:673,818` | crawled_at 등 컬럼 추가 없음 |
| 샘플 크기(N건) 기록 | ✅ | `engine.py:700-706` | `CrawlResult.total_collected` + 로그 |
| 오류 처리 (try/except+로깅) | ✅ | `engine.py:632-654`, `drivers.py:101-186` | 단계별 try/except + logger, errors 리스트 누적 |
| 중복 제거 비율 기록 | 🟡 | `analyzer.py:181` | 중복 제거는 하나(전처리 단계), **제거 비율 로깅** 부분만 |
| API rate limit 준수 | ✅ | `crawler/rate_limiter.py`, `config.py:60-74` | Token Bucket, `crawl_delay_seconds=1.5`, `max_retries=3`, 프리셋별 rpm |
| robots.txt 준수 | ✅ | `engine.py:55-111` | `LegalComplianceChecker` + urllib.robotparser, 기본 ON |

**신뢰성 점수: 3 / 5점**
(rate limit·robots·오류처리는 견고. 그러나 **출처 URL·수집 timestamp 미저장**은 "데이터 출처 추적"을 요구하는 Sentinel 발표에 실질 결함.)

---

## 7. 통합 점수 (현재 → 목표)

| 영역 | 현재 | 목표 (5/29) | 갭 |
|---|---|---|---|
| BX 데이터 수집 체계성 (5점) | **1**/5 | 4/5 | 3 |
| BX 데이터 수집 신뢰성 (5점) | **3**/5 | 4/5 | 1 |
| CX 페르소나 (5점) | **0**/5 | 5/5 | 5 |
| CX 핵심 고객 경험 (5점) | **1**/5 | 4/5 | 3 |
| DX 충실성 일부 (4점) | **3**/4 | 3/4 | 0 |
| **합계 (24점 만점)** | **8** | **20** | **12** |

> 해석: 범용 크롤·NLP·시각화 기반(DX 충실성)은 거의 목표 수준이나, **Sentinel의 정체성(페르소나·감염병 채널·선행성)** 영역이 0~1점으로 갭의 대부분(12점 중 11점)을 차지. 즉 "엔진은 있으나 Sentinel 도메인으로 미특화" 상태.

---

## 8. 🚨 P0 즉시 보강 사항 (5/29 D-2)

- [ ] **(근본) 도메인 정합성 결정**: 현재 8501은 상품 리뷰 도구다. ① jinyoung-toolkit 엔진 위에 Sentinel 레이어(페르소나 키워드·감염병 채널)를 얹을지, ② 별도 Sentinel 코드베이스를 만들지 발표 전 확정 필요. 이 결정 없이는 아래 항목이 공중에 뜸.
- [ ] **PERSONA_KEYWORDS 매트릭스 신설**: 김민영/박준호/이수정 × 키워드 dict. 현재 0건 → CX 페르소나 5점이 통째로 비어있음.
- [ ] **다중 키워드 검색 크롤**: 현재 프리셋은 단일 URL/검색어 중심. 페르소나별 키워드 N개를 한 번에 돌리는 배치 크롤 필요 *(사용자 요청 사항과 직결 — 후속 작업으로 진행)*.
- [ ] **출처 URL + 수집 timestamp 컬럼 추가** (`engine.py` record dict): 신뢰성 결함이자 가장 적은 노력으로 메우는 항목.
- [ ] **KOWAS/네이버 DataLab 등 외부 유행 채널 최소 1개 연동**: Layer A가 0점 — 발표의 "선행 신호" 서사가 성립하려면 최소 하나는 필요.

---

## 9. 🟡 P1 발표 전 보강 (6/25)

- [ ] **선행성 검증**: KOWAS → 블로그/카페 → 뉴스 시차의 Granger/교차상관 (현재 시계열 분석 전무 — 발표 논리 핵심).
- [ ] **페르소나-Pain Point 히트맵**: 페르소나 매트릭스 완성 후 plotly heatmap.
- [ ] **키워드 시간대별 트렌드 차트**: date 컬럼은 이미 수집됨 → 날짜별 집계 로직만 추가.
- [ ] **워드클라우드 페르소나별 3종**으로 확장 (현재 감성별 3종 → 페르소나별).
- [ ] **CAM(직원 하루 Journey)** Plotly Timeline.
- [ ] BERTopic 검토 (현재 sklearn LDA로 충분할 수 있음 — 비용 대비 효과 판단).

---

## 10. 코드 구조 다이어그램 (실제)

```
jinyoung-toolkit/
├── app.py                      # 루트 허브 → review_analyzer / automl_reporter 선택
├── requirements.txt
├── shared/
│   ├── korean_nlp.py           # Kiwi 형태소·TF-IDF·워드클라우드(한글폰트)
│   ├── config.py               # crawl_delay_seconds, max_retries 등
│   ├── exporters.py            # CSV/JSON/Excel/Parquet (DB 없음)
│   ├── delivery.py / report_generator.py  # ZIP 납품·PDF
│   └── ui_components.py
└── review_analyzer/
    ├── app.py                  # 3탭: 리뷰분석/경쟁사비교/고급분석
    ├── analyzer.py             # 전처리·감성(룰)·키워드·워드클라우드
    ├── advanced_analyzer.py    # KMeans 군집·LDA 토픽·PCA/t-SNE·통계 (신규)
    ├── comparator.py           # 경쟁사 비교
    ├── selector_inferer.py     # LLM 셀렉터 자동 추론 (Claude)
    ├── preset_loader.py
    ├── crawler/
    │   ├── engine.py           # 크롤 오케스트레이션 + robots 준수
    │   ├── drivers.py          # httpx / selenium / api 드라이버
    │   └── rate_limiter.py     # Token Bucket
    ├── presets/                # 14종 YAML (전부 상품/콘텐츠 리뷰)
    │   ├── amazon_reviews.yaml ... youtube_comments.yaml
    └── ui/
        ├── crawler_tab.py      # Step1 입력
        ├── analyze_tab.py      # Step2·3 감성 분석·결과
        ├── advanced_tab.py     # 군집·토픽·2D·통계 (신규)
        └── compare_tab.py      # 경쟁사 비교
```

**핵심 결론**: 크롤 엔진·한국어 NLP·토픽모델링·시각화의 **기술 기반은 발표 수준에 근접**(DX 3/4). 그러나 LG ThinQ Sentinel의 **도메인 정체성(페르소나·감염병 선행신호)** 은 미구현으로, 24점 만점 중 **8점**. 갭 12점의 11점이 Sentinel 특화 영역에 집중되어 있다. D-2 우선순위는 ①도메인 결정 ②페르소나 매트릭스 ③다중 키워드 크롤 ④출처/timestamp이다.
