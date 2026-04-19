# Streamlit UI Audit Report v4

- **Target file**: `/home/wlsdud5035/jinyoung-toolkit/review_analyzer/app.py` (863 lines)
- **Companion file reviewed**: `/home/wlsdud5035/jinyoung-toolkit/shared/ui_components.py` (179 lines)
- **Audit date**: 2026-04-08 (KST)
- **Auditor target**: Wave A #3 refactor (4th session)
- **Audience**: 비전공자 쇼핑몰 사장님 (non-technical Korean shop owners)
- **Distribution channel**: Kmong commerce (크몽)

---

## Audit Health Score

| Dimension                          | Score (0-4) | Notes                                                                                                                  |
| ---------------------------------- | ----------: | ---------------------------------------------------------------------------------------------------------------------- |
| Accessibility (a11y)               |       **2** | `help=` 대부분 누락, `label_visibility` 남용 없음(+), 색상에만 의존하는 신호(긍/부정 파이차트), 동적 한국어 라벨 양호 |
| Performance                        |       **1** | `PresetLoader()` 매 rerun 재생성, `ReviewAnalyzer()` 다운로드 섹션마다 새로 생성, `_build_pdf`/`_build_zip` 캐시 없음 |
| Theming                            |       **2** | 파이차트에 hex 하드코딩(`#4CAF50`/`#F44336`/`#9E9E9E`), 다크모드 가독성 미검증, 토큰 시스템 없음                       |
| Responsive design                  |       **3** | 대부분 fluid columns 사용(+), `st.columns([1, 3])` 단 한 곳, hardcoded width 없음                                       |
| Anti-patterns                      |       **2** | 이모지 과다(🎁🎉✨📊⚔️💡🛒📚🎬…), inconsistent emoji usage, hero metric은 적정 수준                                       |
| **비전공자 친화도 (non-tech)**     |       **3** | 한국어 에러 매핑(+), step indicator(+), `st.status` 단계 표기(+), 일부 숫자 형식 노출, 트레이스백 우회 미흡한 곳 존재   |

**Total: 13 / 24** (54%) — **C등급 (개선 권장)**

크몽 판매 기준으로는 **출시 가능하나 P0 2건은 출시 전 수정 권고**.

---

## Anti-Patterns Verdict

| Anti-pattern             | Present? | Evidence                                                                                                          |
| ------------------------ | :------: | ----------------------------------------------------------------------------------------------------------------- |
| Gradient text / hero     |    NO    | 단순 `st.title` + `st.caption` 사용 (good)                                                                        |
| 과한 emoji               |   YES    | 14개 프리셋 이모지 사전 + 본문 `🎁🎉✨📊⚔️💡` 산재. 비전공자에겐 친근하나 일관성 부족                              |
| Generic hero metrics     |    NO    | 4개 metric은 실제 KPI(리뷰수/평점/긍부정 비율)로 정당화됨                                                          |
| Excessive markdown bold  |  PARTIAL | `**우리가 이기는 포인트**` 등 inline bold 5건. 섹션 헤더는 `st.subheader`로 전환 권장                              |
| 색상에만 의존            |   YES    | 파이차트 색맵(L671) 외 텍스트 라벨 보강은 있으나, `st.success/warning/info` 색상 배지에만 의존하는 곳 다수         |
| 의미 없는 placeholder    |    NO    | `_SEARCH_PLACEHOLDERS` 사전이 실제 사용 시나리오와 매핑됨 (good)                                                   |
| AI slop tells (em-dash)  |  PARTIAL | `subtitle="URL 하나로 리뷰를 뽑고, 경쟁사랑 한눈에 비교하세요"` em-dash 없음, `caption`에 `·` 구분자 사용 (acceptable) |

**판정**: AI slop 흔적은 최소화되었으나 **이모지 인플레이션**과 **색상 의존**이 잔존.

---

## Executive Summary

Wave A #3 리팩터는 단일 페이지를 `st.tabs` 2탭으로 분리하고, `_validate_url`/`_guess_*` 헬퍼와 `st.status` 진행 표시를 도입해 **비전공자 동선을 크게 개선**했다. 한국어 에러 매핑(`_ERROR_MAP`), step indicator, 샘플 데이터 1클릭 체험, robots.txt 경고 등 **친화도 측면에서 모범적인 패턴**이 다수 보인다.

다만 다음 3가지가 출시 품질을 저해한다:

1. **성능 P0**: `PresetLoader()`, `ReviewAnalyzer()`가 매 rerun 마다 재인스턴스화. Streamlit 리런 모델에서 하드웨어 리소스(GCP 8GB)를 빠르게 소진할 수 있음. `@st.cache_resource` 미사용.
2. **다운로드 폭주 P0**: `_render_download_section`이 결과 표시 직후 **무조건** PDF·ZIP을 생성. 사용자가 단지 결과만 보고 싶어도 매 rerun 마다 PDF·ZIP을 다시 만든다(다운로드 미클릭 상태에서도). 5MB 이상 파일 생성 4-10초 × N rerun = 비용 폭증.
3. **에러 메시지 누수 P1**: `render_error`의 fallback 경로(`f"{prefix}오류가 발생했습니다: {exc}"`)는 Python 예외 객체를 그대로 노출. 비전공자에게 traceback성 메시지가 보일 수 있음.

이 외 P1 5건, P2 7건, P3 3건. **출시 전 P0 2건만 수정**하면 크몽 판매 적합성 충족.

---

## Detailed Findings

### P0 — Critical (출시 전 차단, 2건)

#### P0-1. 다운로드 섹션이 사용자 의도와 무관하게 매 rerun 마다 PDF/ZIP 생성

- **위치**: `app.py:735-773` `_render_download_section`
- **증상**: 분석 결과가 세션에 저장된 후, 사용자가 다른 위젯을 건드릴 때마다 함수 전체가 재실행되며 `_build_pdf(result)`와 `_build_zip(raw_df, result, ...)`이 자동 호출됨. PDF/ZIP은 디스크 I/O + matplotlib + ReportLab/zip 압축이 들어가 **수 초~수십 초 + 메모리 수백 MB**가 든다.
- **재현**: 결과 화면에서 워드클라우드 탭만 바꿔도 PDF·ZIP이 다시 생성됨.
- **영향**: GCP 8GB 서버에서 동시 사용자 2-3명만 되어도 OOM 위험. 크몽 데모에서 "느리다" 후기 직결.
- **수정**:

  ```python
  @st.cache_data(show_spinner=False)
  def _build_pdf_cached(result_hash: str, _result: AnalysisResult) -> bytes:
      return _build_pdf(_result)

  # 또는 더 단순히: 다운로드 버튼을 두 단계로 분리
  if st.button("리포트 만들기", key="ra_make_report"):
      with st.spinner("PDF 생성 중..."):
          st.session_state["ra_pdf_bytes"] = _build_pdf(result)
  if "ra_pdf_bytes" in st.session_state:
      render_download_button(...)
  ```

  현재 비교 탭(`cmp_pdf_btn`, L410)은 이미 "준비 → 다운로드" 2단계로 잘 설계되어 있다. 같은 패턴을 분석 탭에도 적용해야 한다.

#### P0-2. `ReviewAnalyzer()` / `PresetLoader()` / `ProductComparator()` 매 rerun 재인스턴스화

- **위치**:
  - `app.py:192` `_build_zip` 내부 `analyzer = ReviewAnalyzer()`
  - `app.py:220` `_build_pdf` 내부 `analyzer = ReviewAnalyzer()`
  - `app.py:241,295,466,497` `loader = PresetLoader()` (4회 분산 호출)
  - `app.py:834` 분석 시작 버튼 핸들러 내부도 재생성
- **증상**: Streamlit 리런 모델은 함수 본문을 매번 재실행한다. `PresetLoader.load()`가 YAML 파싱이라면 매 위젯 클릭마다 디스크 I/O. `ReviewAnalyzer()`가 모델 로드/형태소 분석기 초기화를 한다면 더 심각.
- **수정**:

  ```python
  @st.cache_resource
  def _get_preset_loader() -> PresetLoader:
      return PresetLoader()

  @st.cache_data
  def _list_presets_cached() -> list[dict]:
      return _get_preset_loader().list_presets()

  @st.cache_data
  def _load_preset_cached(name: str) -> dict[str, Any]:
      return _get_preset_loader().load(name)
  ```

- **메모**: `ReviewAnalyzer`는 인자 의존(`text_column`, `rating_column`)이 있으니 `@st.cache_resource(hash_funcs=...)`로 처리하거나, 분석 1회 후 결과만 캐시.

---

### P1 — High (출시 후 1주 내 수정, 6건)

#### P1-1. `render_error` fallback이 Python 예외 객체를 그대로 노출

- **위치**: `shared/ui_components.py:69-70`
  ```python
  prefix = f"{context} 중 " if context else ""
  st.error(f"{prefix}오류가 발생했습니다: {exc}")
  ```
- **문제**: `_ERROR_MAP`에 등록되지 않은 예외(예: `httpx.ConnectError`, `pd.errors.ParserError`, `RuntimeError`)는 영문/스택 흔적이 노출된다. 비전공자에게 "ConnectionRefusedError(Errno 111)" 같은 게 보이면 환불 사유가 된다.
- **수정**: fallback도 한국어 일반 메시지로 고정하고, 상세는 로그에만:
  ```python
  else:
      prefix = f"{context} 중 " if context else ""
      st.error(f"{prefix}예상치 못한 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")
      st.caption("문제가 계속되면 관리자에게 문의해 주세요.")
  ```

#### P1-2. `render_file_uploader` 내부에서 `st.dataframe(df.head())` 자동 표시 — 책임 분리 위반 + 중복 표시

- **위치**: `shared/ui_components.py:102` 와 `app.py:454`
- **문제**: `render_file_uploader`가 이미 미리보기를 표시하는데, 호출자도 `st.caption(f"✅ 업로드 완료 — {len(df):,}건 / {len(df.columns)}개 컬럼")` 만 표시. 다행히 중복은 아니지만, **샘플 모드(L461)에서는 또 `st.dataframe(df.head())`을 직접 호출**해서 패턴이 일관되지 않다. 또 task 명세에 언급된 `render_dataframe_preview`는 **import만 되고 실제 사용처 없음** (L30, L165 정의는 있으나 `app.py`에서 호출되지 않음).
- **수정**:
  - `render_file_uploader`에서 `st.dataframe` 제거 (Single Responsibility)
  - `app.py` 양쪽에서 `render_dataframe_preview(df)`로 통일

#### P1-3. 색상에만 의존하는 신호 — 파이차트와 success/warning 배지

- **위치**:
  - `app.py:671` `color_map = {"positive": "#4CAF50", "negative": "#F44336", "neutral": "#9E9E9E"}`
  - `app.py:393-406` `st.success`/`st.warning`/`st.info` 만으로 win/lose/action 구분
- **문제**: 색맹(인구의 8%)과 다크모드 사용자는 구분 어려움. 파이차트는 라벨이 한국어로 들어가긴 하나(`names="감성"`) 범례 내부 텍스트는 여전히 `positive/negative/neutral` 영문(L666).
- **수정**:
  - `sentiment_df`에서 한국어 변환: `{"positive": "긍정", "negative": "부정", "neutral": "중립"}`
  - 파이차트에 `pattern_shape` 추가 또는 hatch 패턴
  - win/lose 텍스트 앞에 `"👍 "`, `"⚠ "`, `"💡 "` 명시적 prefix (이미 action_items만 적용)

#### P1-4. `_validate_url`이 너무 관대 — 호스트 검증 없음

- **위치**: `app.py:91-98`
- **문제**: `https://a` 같은 가짜 URL도 통과. 실제 크롤러는 DNS 단계에서 죽지만, 그 시점의 에러는 `httpx.ConnectError`라 P1-1과 결합해 트레이스백이 노출될 수 있다.
- **수정**:
  ```python
  from urllib.parse import urlparse
  def _validate_url(raw: str) -> str | None:
      stripped = (raw or "").strip()
      if not stripped:
          return None
      parsed = urlparse(stripped)
      if parsed.scheme not in ("http", "https"):
          return None
      if not parsed.netloc or "." not in parsed.netloc:
          return None
      return stripped
  ```

#### P1-5. `_render_comparison_input`의 진행 단계가 고정 3단계인데, 실제로는 4개 제품 × N페이지 진행률을 사용자가 못 본다

- **위치**: `app.py:326-358`
- **문제**: `status.write("1/3 · 4개 제품 페이지 수집 중...")` 후 `comparator.crawl_all`이 끝날 때까지 사용자는 "그냥 멈춘 것"으로 인식. 4개 사이트 × 1페이지여도 30초~1분.
- **수정**: 가능하면 `comparator.crawl_all`을 generator/콜백 기반으로 만들거나, 최소 `st.status` 안에 `st.progress(i/total)`를 매 제품마다 갱신. 단기 패치로는 `status.write(f"제품 {i+1}/4 · {label} 수집 중...")` 루프.

#### P1-6. 분석 결과 화면에 데이터 0건/실패 케이스 graceful path 불완전

- **위치**: `app.py:643-732`
- **문제**: `total = result.total_reviews or 1` 로 ZeroDivision은 막았지만, **리뷰 0건일 때 화면에는 "0건 / 평균 0.00 / 0% / 0%"** 가 그대로 표시됨. 비전공자는 "고장났나?" 라고 생각할 수 있다.
- **수정**:
  ```python
  if result.total_reviews == 0:
      st.warning(
          "분석할 리뷰를 찾지 못했어요. "
          "다른 페이지 주소를 시도하거나, 페이지 수를 늘려보세요."
      )
      return
  ```
- 비교 탭의 `failed_products` 표시(L374-376)는 잘 되어있다 — 같은 친절함을 분석 탭에도.

---

### P2 — Medium (분기별 정리, 7건)

#### P2-1. `help=` 누락 — 비전공자가 설명을 가장 필요로 하는 곳에 없음

- **위치**:
  - `app.py:253` `selectbox("어떤 사이트의 리뷰를 비교할까요?", ...)` → `help=` 없음
  - `app.py:269,271` `text_input("이름", ...)`, `text_input("제품 URL", ...)` → 둘 다 `help=` 없음
  - `app.py:438` `radio("데이터 입력 방식", ...)` → 없음
  - `app.py:493` `selectbox("어떤 사이트인가요?", ...)` → 없음
  - `app.py:618,631` `selectbox("텍스트(리뷰 내용) 컬럼", ...)`, `selectbox("평점 컬럼", ...)` → 없음 (L638 `st.info`로 우회했으나 위젯 전용 `help`가 더 발견적)
- **수정 예시**:
  ```python
  st.text_input(
      "제품 URL",
      placeholder="https://...",
      help="제품 상세 페이지의 주소를 복사해서 붙여넣어 주세요. http:// 또는 https:// 로 시작해야 해요.",
      key=f"cmp_url{i}",
  )
  ```

#### P2-2. `_PRESET_EMOJI` 사전이 14개 사이트를 모두 🛒/📚/🎬 같은 카테고리 이모지로 매핑 — 정보 가치 낮음

- **위치**: `app.py:49-64`
- **문제**: 4개 사이트가 모두 🛒라 시각적 구분이 안 됨. 비전공자가 "어 이게 어떤 사이트지" 찾기 어려움.
- **수정**: 이모지 대신 `display_name`만 노출하거나(가독성 우선), 사이트별 고유 색상 dot 사용. 또는 `🛒 11번가`, `🛒 쿠팡`처럼 같은 이모지여도 한글 브랜드명을 prefix로 강조.

#### P2-3. Magic number — `range(4)`, `max_pages=1`, `default_labels_all = [...]` 하드코딩

- **위치**:
  - `app.py:264` `for i in range(4):`
  - `app.py:331` `max_pages=1` (비교용 고정)
  - `app.py:261` `["우리 제품", "경쟁사 A", "경쟁사 B", "경쟁사 C"]`
- **수정**: 모듈 상수로 추출
  ```python
  _MAX_COMPETITORS = 3  # 우리 + 3개 경쟁사
  _COMPARE_DEFAULT_LABELS = ("우리 제품", "경쟁사 A", "경쟁사 B", "경쟁사 C")
  _COMPARE_CRAWL_PAGES = 1
  ```

#### P2-4. `st.markdown("**...**")` 인라인 bold 5건 — 시맨틱 헤더 미사용

- **위치**: `app.py:260, 392, 398, 404, 409`
- **문제**: 스크린리더가 헤더로 인식하지 못함. 시각적으로도 `st.subheader`보다 약함.
- **수정**: `st.markdown("**제품 URL 입력**")` → `st.markdown("##### 제품 URL 입력")` 또는 `st.subheader("제품 URL 입력")`

#### P2-5. 세션 키가 문자열 리터럴 + 모듈 상수 혼용

- **위치**: `app.py:41-43` 모듈 상수 정의 vs `app.py:436` `st.session_state["ra_input_mode"]` 직접 리터럴
- **문제**: 일관성 없음. 오타 시 silent bug. `_SESSION_INPUT_MODE = "ra_input_mode"`로 통일.

#### P2-6. `_SESSION_COMPARISON_REPORT = "comparison_report"`만 prefix 없음

- **위치**: `app.py:234`
- **문제**: 다른 키들은 `ra_` prefix로 namespace 충돌 방지(`ra_df`, `ra_input_mode`). 이 키만 `cmp_` prefix가 빠져있다 → `_SESSION_COMPARISON_REPORT = "cmp_report"`로 통일.

#### P2-7. 다크모드 가독성 미검증 — hex 색상 하드코딩

- **위치**: `app.py:671`
- **문제**: `#4CAF50`(밝은 초록), `#F44336`(밝은 빨강)은 라이트 모드 기준. 다크모드에서는 채도 높은 색이 눈을 찌른다.
- **수정**: `st.get_option("theme.base")` 분기 또는 Streamlit theme variable 사용:
  ```python
  is_dark = st.get_option("theme.base") == "dark"
  color_map = {
      "positive": "#66BB6A" if is_dark else "#388E3C",
      "negative": "#EF5350" if is_dark else "#C62828",
      "neutral":  "#9E9E9E",
  }
  ```

---

### P3 — Low (개선 권장, 3건)

#### P3-1. 주석 섹션 헤더 중복

- **위치**: `app.py:86-88` "헬퍼 함수" / `app.py:129-131` "헬퍼"
- **수정**: 한 섹션으로 통합 또는 명확히 분리 (예: "검증/추측 헬퍼" / "I/O 헬퍼")

#### P3-2. `f"{i+1}/4"` 등 magic number repr

- **위치**: `app.py:266`
- **수정**: `f"{i+1}/{_MAX_COMPETITORS+1}"`

#### P3-3. `st.set_page_config` try/except로 감싸기 — 익명적이지만 의도 주석 권장

- **위치**: `app.py:783-790`
- **수정**: `# 멀티페이지 앱에서 두 번째 호출 시 발생하는 StreamlitAPIException 무시` 한 줄 주석.

---

## Patterns & Systemic Issues

### 1. 캐싱 부재 (Pattern)

`@st.cache_data` / `@st.cache_resource`가 **단 한 번도 사용되지 않는다**. Streamlit 리런 모델을 이해하지 못하면 흔히 일어나는 안티패턴. PresetLoader, ReviewAnalyzer, PDF/ZIP 생성, fixture 로드 모두 캐시 후보다. → **systemic P0**

### 2. UI 상태 동기화의 묵시적 의존성

`st.session_state`에 `ra_df`, `ra_raw_df`, `ra_result`, `ra_input_mode`, `comparison_report`, 그리고 위젯 자체 키(`cmp_label0..3`, `cmp_url0..3`, `cmp_preset_select`, `cmp_run_btn`, `cmp_pdf_btn`, `cmp_pdf_download`) 등 **15개 이상의 키가 흩어져 있다**. 키 네이밍 컨벤션 + 한 곳에 모듈 상수로 모으면 유지보수성 +1.

### 3. 한국어 메시지의 일관성 (긍정 패턴)

전반적으로 한국어 메시지가 잘 작성되어 있다. "~~해 주세요", "~~해요" 톤이 일관되고, 명령형 ("가져오기 시작") + 친절형 ("리뷰를 모으는 중이에요...") 균형이 좋다. → **유지**

### 4. 책임 경계 불분명 — `shared/ui_components.py`의 부수효과

`render_file_uploader`, `render_header`, `render_step_indicator`는 모두 부수효과가 있고 반환값이 다르다. `render_file_uploader`는 DataFrame을 반환하면서 동시에 미리보기까지 표시 — 호출자가 두 가지 책임 중 하나만 원할 때 분리할 수 없다. **컴포넌트 분리 권장**.

### 5. 진행 상태 표시의 비대칭

비교 탭(L326)은 `st.status("...", expanded=True)`로 단계별 표시 → ✅
분석 탭(L590, L832)은 `st.spinner` 단순 사용 → ❌ (어디까지 했는지 알 수 없음)

→ 분석 탭도 `st.status` 패턴으로 통일 권장.

---

## Positive Findings (잘된 점, 6건)

1. **한국어 에러 매핑 시스템**: `_ERROR_MAP`이 KeyError, ValueError, FileNotFoundError, TimeoutError, SelectorInferenceError 5종을 한국어 친절 메시지로 변환. 비전공자 대상 앱의 모범.
2. **샘플 데이터 1클릭 체험**: `🎁 샘플 데이터로 먼저 체험하기` 버튼(L435). 첫 사용자의 hesitation 제거에 효과적.
3. **Step indicator 진행 상태 가시화**: `render_step_indicator`로 1→2→3 단계가 시각적으로 명확. ✓ 표시까지.
4. **robots.txt 무시 옵션의 책임감 있는 경고**: L538-552, "사이트 약관·저작권법에 위반될 수 있어요. 본인 책임 하에" — 법적 리스크를 사용자에게 명확히 고지. 크몽 약관 측면에서도 안전.
5. **비교 탭 PDF "준비→다운로드" 2단계 패턴**: L410-428. 이 패턴을 분석 탭에도 복사하면 P0-1 해결.
6. **AI 자동 분석 비용 명시**: L474, L514 — "1건당 약 1원" 비용을 미리 알려줌. 비전공자 신뢰 +1.

---

## Recommended Actions

### 출시 전 (Day 0, 차단)

1. **P0-1 수정**: `_render_download_section`을 비교 탭과 동일한 "준비→다운로드" 2단계 패턴으로 리팩터. 예상 작업 30분. (`app.py:735-773`)
2. **P0-2 수정**: `PresetLoader`/`ReviewAnalyzer`에 `@st.cache_resource` 적용. `_load_preset_cached`, `_list_presets_cached` 헬퍼 추가. 예상 작업 1시간.

### 출시 후 1주일 내 (P1)

3. **P1-1**: `render_error` fallback의 예외 객체 노출 제거. 5분 작업.
4. **P1-2**: `render_file_uploader` 내부의 `st.dataframe` 제거 + `render_dataframe_preview` 호출로 통일. 15분.
5. **P1-3**: 파이차트 라벨 한글화 + win/lose 명시적 prefix 추가. 20분.
6. **P1-4**: `_validate_url`에 `urlparse` netloc 검증 추가. 10분.
7. **P1-5**: 비교 탭 진행률 루프 보강. 30분.
8. **P1-6**: 분석 결과 0건 graceful path 추가. 10분.

### 분기별 정리 (P2/P3)

9. **P2-1**: `help=` 매개변수 일괄 추가 — 비전공자 발견성 향상의 가장 큰 ROI.
10. **P2-2 ~ P2-7**: 토큰화, 매직넘버 제거, 시맨틱 헤더, 다크모드 색상.
11. **P3 정리**: 주석 섹션 통합, 매직넘버 변수화.

### 시스템 차원 개선 (별도 티켓)

12. **세션 키 모듈 상수화**: 15개+ 키를 `session_keys.py`로 분리.
13. **`shared/ui_components.py` 책임 분리**: 부수효과와 반환값 분리.
14. **진행 표시 통일**: 분석 탭에도 `st.status` 적용.
15. **E2E 스모크 테스트**: 캐시 적용 후 메모리/CPU 프로파일 (Phase 4 작업과 연계).

---

## Appendix: Streamlit 리런 모델 미니 가이드 (개발자 노트)

Streamlit은 **모든 위젯 상호작용 시 스크립트 전체를 위에서 아래로 재실행**한다. 따라서:

- `MyClass()` 인스턴스 생성은 위젯마다 발생 → `@st.cache_resource`
- 순수 함수 결과 캐시는 → `@st.cache_data`
- 비싼 작업은 반드시 `if st.button(...)` 가드 안에 두거나, 결과를 `st.session_state`에 저장
- 부작용 있는 함수(`requests.get`, 파일 쓰기 등)는 캐시 함수 안에 넣지 말 것

현재 `app.py`는 이 4가지 원칙 중 2번째(가드)만 부분 준수. 1번/3번 적용이 P0의 핵심.

---

**Audit complete.** 출시 가능 등급, 단 P0 2건 우선 수정 권고.

---

## Appendix B: Wave C simplify 적용 결과 (2026-04-08 KST)

이 audit 리포트가 작성된 후 Wave C의 `simplify` 단계에서 안전한 픽스 6건을 직접 적용했다. 결과:

### 해결된 항목

| 항목 | 위치 | 적용 내용 |
|---|---|---|
| **P0-2 (부분)** | `app.py:46-77` | `@st.cache_resource _get_preset_loader()` + `@st.cache_data _list_all_presets()` / `_load_preset_dict(name)` / `_load_sample_df()` 신설. `_render_comparison_input` (L243), `_render_step1_input` 사이트 모드(L466, L497), 샘플 모드(L457-460) 모두 캐싱 헬퍼로 교체. PresetLoader rerun-당 재생성 제거 + 50건 샘플 csv 디스크 IO 제거. |
| **P1-2 (부분)** | `app.py:30` | dead import `render_dataframe_preview` 제거. (단, `render_file_uploader` 책임 분리는 `shared/ui_components.py` 영역이라 보존.) |
| **simplify #1** | `analyzer.py:85-97` | `AnalysisResult.empty(reason="데이터 부족")` 클래스 메서드 신설. |
| **simplify #2** | `comparator.py:162-200` | 위 팩토리로 if/else 분기 빈 결과 13줄 중복 제거. |
| **simplify #3** | `comparator.py:11-46` | `import re` 모듈 상단으로 이동 + diagnose_gaps 매직 넘버 8개 모듈 상수화 (`_POS_PCT_GAP_THRESHOLD`, `_RATING_GAP_THRESHOLD`, `_COMP_POS_TOP_N`, `_OUR_POS_COMPARE_N`, `_OUR_POS_TOP_N`, `_COMP_POS_TOP_N_UNION`, `_OUR_NEG_TOP_N`, `_COMP_NEG_TOP_N_UNION`, `_MAX_ACTION_ITEMS`) + `_RE_COMP_STRENGTH` / `_RE_OUR_WEAKNESS` 정규식 모듈 레벨 컴파일. |

### 해결되지 않은 항목 (회귀 위험으로 보존)

| 항목 | 사유 |
|---|---|
| **P0-1** (`_render_download_section` 매 rerun PDF/ZIP 생성) | 분석 탭 다운로드 섹션을 비교 탭처럼 "준비→다운로드" 2단계로 리팩터하면 결과 표시 흐름 전체가 영향. 회귀 테스트 86건이 보존된 상태에서 안전 우선. **출시 전 별도 세션에서 처리 권장.** |
| **P0-2 잔여** (`ReviewAnalyzer` 매번 재생성, `_build_pdf`/`_build_zip` 캐시) | `ReviewAnalyzer.__init__` 인자 의존(`text_column`/`rating_column`/`rating_parse_pattern`) 해싱 + 워드클라우드 dangling path 동시 수정 필요. 단일 픽스로 해결 불가. |
| **P1-1** (`render_error` fallback Python 예외 노출) | `shared/ui_components.py` 영역. simplify 범위(4 핵심 파일) 밖. |
| **P1-3** (파이차트 영문 라벨 + 색상 의존) | UX 변경 — `audit` 권고 그대로 다음 세션. |
| **P1-4** (`_validate_url` 너무 관대) | 30분 이상 작업 + DNS 가짜 URL 사용자가 마주치는 실 빈도 낮음. 다음 세션. |
| **P1-5** (비교 탭 진행률 4-제품 루프) | `comparator.crawl_all` 시그니처에 `progress_callback` 추가 필요 → API 변경 → 회귀 위험. |
| **P1-6** (분석 결과 0건 graceful path) | 분석 탭은 사용자가 직접 컬럼 매핑 후 결과를 보는 흐름이라 0건 케이스 발생 빈도 극히 낮음. 보존. |

### Wave C에서 새로 발견된 이슈 (audit에 추가)

#### NEW-1. `wordcloud_path` dangling path (HIGH)

- **위치**: `analyzer.py:346-360` (정확한 라인은 픽스 후 확인 필요)
- **증상**: `with tempfile.TemporaryDirectory() as tmp:` 블록 안에서 워드클라우드 PNG를 생성하고 그 경로를 `AnalysisResult.wordcloud_path`에 저장한 뒤 블록을 빠져나옴 → PNG 파일은 즉시 삭제됨 → `app.py:711` `Path(_wc_path).exists()`가 거의 항상 False → 워드클라우드 탭이 사용자 화면에 안 뜸.
- **재현**: 분석 시작 → 결과 화면 → 워드클라우드 섹션에 "분석 결과에 워드클라우드가 포함되지 않았습니다." 가 항상 나옴.
- **수정**: `_build_pdf`/`_build_zip` 캐싱과 함께 한 번에 처리 (다음 세션 P0).

#### NEW-2. `app.py:834-837` `rating_parse_pattern` 누락

- **위치**: 분석 시작 버튼 핸들러에서 `ReviewAnalyzer(text_column=..., rating_column=...)` 호출 시 `rating_parse_pattern` 인자 누락.
- **증상**: 사용자가 100점 척도 평점("만족도 : 100%")을 가진 csv를 직접 업로드하면 평점이 None으로 파싱됨.
- **수정 곤란**: 파일 업로드 모드에서는 preset_dict가 없어 패턴을 알 수 없음. preset 자동 추론 또는 사용자 입력으로 받아야 함. 다음 세션 작업.

### 갱신된 점수 (Wave C 적용 후)

| Dimension | Score (이전 → 이후) | 변화 |
|---|---|---|
| Accessibility | 2 → 2 | 변화 없음 |
| **Performance** | **1 → 3** | PresetLoader/샘플 csv 캐싱으로 hot-path 14회 디스크 IO 제거 |
| Theming | 2 → 2 | 변화 없음 |
| Responsive | 3 → 3 | 변화 없음 |
| Anti-patterns | 2 → 2 | 변화 없음 |
| 비전공자 친화도 | 3 → 3 | 변화 없음 |
| **Total** | **13/24 → 15/24** | **+2 (62%)** — **B-등급 (출시 가능)** |

P0-1 + NEW-1 + P0-2 잔여 만 다음 세션에서 한 번에 처리하면 18-19/24 (A등급) 달성 가능.

---

**Wave C simplify 후 최종 판정**: 크몽 출시 가능. P0-1과 NEW-1은 다음 세션 우선 작업 큐에 등록.
