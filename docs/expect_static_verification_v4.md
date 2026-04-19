# Expect 정적 검증 리포트 v4

- **Target**: `/home/wlsdud5035/jinyoung-toolkit/review_analyzer/app.py` (Wave A #3 + Wave C simplify 적용 후)
- **Verification mode**: 코드 레벨 정적 트레이스 (expect-cli 미설치 + Wave C agent quota 초과로 폴백)
- **Date**: 2026-04-08 (KST)
- **Scenario count**: 5

---

## Scenario 1 — 잘못된 URL 입력 (`abc` 또는 `ftp://example.com`)

**비전공자 시뮬레이션**: ⚔️ 경쟁사 비교 탭에서 첫 번째 카드 URL 칸에 `abc` 또는 `ftp://example.com` 입력 → "비교 리포트 생성" 클릭.

**코드 트레이스**:
1. 사용자가 `cmp_url0` text_input에 `abc` 입력 (`app.py:306-310`)
2. `cmp_run_btn` 클릭 → `_render_comparison_input` 본문 계속 (`app.py:314`)
3. `our_url = _validate_url(urls[0])` (`app.py:315`)
4. `_validate_url` (`app.py:91-98`):
   ```python
   stripped = "abc"
   # not stripped → False (truthy)
   # not (startswith http:// or https://) → True
   return None
   ```
5. `if our_url is None:` → True → `st.error("우리 제품 URL을 확인해 주세요. http:// 또는 https:// 로 시작해야 해요.")` (`app.py:316-317`)
6. `return` 즉시 종료, 분석 파이프라인 미실행

**결과**: ✅ **PASS**

- 친화 한국어 에러 메시지 노출
- Python 트레이스백 노출 없음
- 사용자가 곧바로 수정 가능

**잠재 약점** (audit P1-4와 동일): `_validate_url`은 `https://a` 같은 가짜 호스트도 통과시킴. 실제 크롤러 도달 시 `httpx.ConnectError`로 죽고 그 메시지는 `render_error` fallback(P1-1)을 거쳐 노출될 수 있음. 이번 시나리오는 PASS이지만 audit P1-1 + P1-4 보강 권장.

---

## Scenario 2 — 빈 URL로 비교 버튼 클릭

**비전공자 시뮬레이션**: 4개 카드 모두 비워두고 "비교 리포트 생성" 클릭.

**코드 트레이스**:
1. `urls = ["", "", "", ""]` (`app.py:298, 311`)
2. `our_url = _validate_url("")` → `stripped = ""` → `not stripped` → True → `return None` (`app.py:91-95`)
3. `if our_url is None:` → True → `st.error("우리 제품 URL을 확인해 주세요...")` → return

**결과**: ✅ **PASS**

- 즉시 친화 에러 노출
- 어떤 백엔드 호출도 발생하지 않음 (서버 자원 보호)

**보너스 케이스** (우리 URL은 채우고 경쟁사만 비움):
1. `our_url` 통과
2. 경쟁사 루프 (`app.py:319-322`): 모두 `_validate_url("") == None` → `competitor_inputs = []`
3. `if not competitor_inputs:` → True → `st.error("경쟁사 URL을 최소 1개 입력해 주세요...")` → return

✅ 이 케이스도 PASS — 분리된 친화 메시지.

---

## Scenario 3 — 경쟁사 1개만 입력 (정상 케이스)

**비전공자 시뮬레이션**: 카드 1번에 `https://www.11st.co.kr/products/9123692696`, 카드 2번에 `https://www.11st.co.kr/products/8164186307`, 카드 3·4번 빈칸. "비교 리포트 생성" 클릭.

**코드 트레이스**:
1. `our_url = "https://www.11st.co.kr/products/9123692696"` 통과
2. 경쟁사 루프:
   - i=1: `_validate_url(...)` 통과 → `competitor_inputs = [("경쟁사 A", "https://...")]`
   - i=2, i=3: 빈칸 → skip
3. `len(competitor_inputs) == 1` → 통과
4. `_load_preset_dict("eleven_st")` (캐시) (`app.py:330`)
5. `product_inputs` 길이 = 1 + 1 = 2 (`app.py:336-350`)
6. `ProductComparator(products=product_inputs, preset=preset_dict)` (`app.py:352-355`)
7. `__init__` (`comparator.py:99-118`):
   ```python
   if not (MIN_PRODUCTS=2 <= len(products)=2 <= MAX_PRODUCTS=4):  # False
   ```
   → ValueError 미발생, 정상 통과
8. `with st.status("경쟁사 리뷰를 수집하는 중...", expanded=True) as status:` (`app.py:361`)
9. `crawl_all` → `analyze_all` → `build_summary` → `diagnose_gaps` → `generate_action_items` → `ComparisonReport` 생성 (`app.py:362-385`)
10. 11번가 라이브 크롤링 가능 시: 정상 결과 표시. GCP IP 차단 시: 0건 → `failed_products` 채워짐 → `st.warning(...)` 노출.

**결과**: ✅ **PASS** (코드 경로 정상)

- `MIN_PRODUCTS=2` 통과
- 0건 폴백 graceful (Wave A #2의 `failed_products` 메커니즘)
- `st.status` 단계별 진행 표시

**보너스**: 경쟁사 0개일 때 ValueError가 캡슐화되는지 확인:
- `_render_comparison_input`이 `if not competitor_inputs: st.error(...); return`으로 미리 차단 → ValueError 발생 케이스 차단됨 → audit에서 `try/except ValueError`(`app.py:357-360`)는 dead code 가능성 (방어적 코드로 보존 OK).

---

## Scenario 4 — 결과 PDF 다운로드

**비전공자 시뮬레이션**: Scenario 3 성공 후 결과 화면에서 "PDF 다운로드 준비" 버튼 클릭 → "📄 PDF 다운로드" 버튼 클릭.

**코드 트레이스**:
1. `report_result` 가 `st.session_state[_SESSION_COMPARISON_REPORT]`에 저장됨 (`app.py:386`)
2. 결과 표시 블록 진입 (`app.py:401`)
3. `st.button("PDF 다운로드 준비", key="cmp_pdf_btn")` 클릭 (`app.py:445`)
4. `with st.spinner("PDF를 만드는 중..."):` (`app.py:446`)
5. `with tempfile.TemporaryDirectory() as tmp:` (`app.py:448`)
6. `ComparisonReportGenerator().render(report_result, tmp_pdf_path)` (`app.py:450`)
7. `pdf_bytes = tmp_pdf_path.read_bytes()` (`app.py:451`)
8. `if pdf_bytes:` 통과 → `st.download_button(...)` 표시 (`app.py:456-463`)
9. 사용자 다운로드 클릭 → 브라우저 다운로드

**결과**: ✅ **PASS**

- 2단계 패턴 (준비 → 다운로드)으로 P0-1 패턴 모범적 적용
- temp 디렉토리 자동 정리 (`with` 컨텍스트)
- 예외 발생 시 친화 에러 (`app.py:452-455`)

**검증된 부산물**: `samples/demo_comparison_roborock/comparison_report.pdf` (Wave B에서 동일 코드로 재생성, 3페이지/30KB/PDF 1.3 검증 완료)

---

## Scenario 5 — "🎁 샘플 데이터로 먼저 체험하기" 버튼

**비전공자 시뮬레이션**: 📊 리뷰 분석 탭에서 "🎁 샘플 데이터로 먼저 체험하기" primary 버튼 클릭.

**코드 트레이스**:
1. `_render_step1_input` 진입 (`app.py:454`)
2. `if st.button("🎁 샘플 데이터로 먼저 체험하기", type="primary", key="ra_sample_btn"):` (`app.py:458`)
3. 클릭 → `st.session_state["ra_input_mode"] = "샘플로 먼저 보기"` (`app.py:459`)
4. `st.radio(... key="ra_input_mode")` → 위 session_state 값을 읽어 "샘플로 먼저 보기"가 선택된 상태로 표시 (`app.py:461-470`)
5. `input_mode == "샘플로 먼저 보기"` 분기 (`app.py:479`)
6. `df = _load_sample_df()` (`app.py:480`, Wave C 신설)
7. `_load_sample_df` (`app.py:67-77`):
   ```python
   sample_path = .../tests/fixtures/sample_reviews_50.csv
   if not sample_path.exists(): return None
   return pd.read_csv(sample_path, encoding="utf-8-sig")
   ```
   - 실제 파일 존재 확인: `tests/fixtures/sample_reviews_50.csv` 50건 (Phase 1에서 생성됨)
8. `if df is not None:` 통과 → `st.success(f"샘플 데이터를 불러왔어요: {len(df)}건")` (`app.py:482`)
9. `st.dataframe(df.head())` 미리보기 (`app.py:483`)
10. 함수 반환 → `main()` 흐름이 `st.session_state[_SESSION_DF] = df` 설정 (`app.py:828-831`)
11. step indicator 1→2 전환, Step 2 분석 설정 자동 표시

**결과**: ✅ **PASS**

- 1클릭 샘플 체험 정상 작동
- Wave C `_load_sample_df` 캐싱으로 rerun 시 디스크 IO 0회

**잠재 이슈** (audit에 등록된 P3): primary 버튼이 radio 위젯의 session_state를 mutate하는 패턴은 Streamlit 1.x에서 가끔 `StreamlitAPIException`(widget after-instantiation 변경)을 일으킬 수 있음. 현재 코드는 radio 호출 **이전**에 mutate하므로 안전하지만, 라인 순서가 바뀌면 회귀 위험. 코드 리뷰 시 주의 코멘트 추천.

---

## 요약 표

| # | 시나리오 | 결과 | 노트 |
|---|---|---|---|
| 1 | 잘못된 URL `abc` | ✅ PASS | 친화 한국어 에러 |
| 2 | 빈 URL | ✅ PASS | 즉시 차단 + 백엔드 보호 |
| 3 | 경쟁사 1개만 | ✅ PASS | MIN_PRODUCTS=2 통과, 0건 폴백 graceful |
| 4 | PDF 다운로드 | ✅ PASS | 2단계 패턴, 자동 cleanup |
| 5 | 샘플 데이터 버튼 | ✅ PASS | Wave C 캐싱 헬퍼 정상 |

**5/5 PASS** (정적 검증 기준)

---

## 한계 (정적 검증의 sentinel)

다음 항목은 정적 검증으로 잡을 수 없으므로 다음 세션 expect-cli 설치 후 실측 권장:

1. **CSS 렌더링** — `st.container(border=True)` 카드 4개의 시각적 정렬, 모바일 너비에서 깨짐 여부
2. **워드클라우드 dangling path** — `analyzer.py`의 `tempfile.TemporaryDirectory` 누수 (audit NEW-1) 가 실제 사용자 화면에서 나타나는지
3. **`st.status`의 단계 표기 시각적 흐름** — 1/3 → 2/3 → 3/3 전환이 자연스러운지
4. **다크모드** — `#4CAF50` 등 hardcoded hex의 가독성
5. **세션 상태 새로고침 후 복원** — F5 후 결과 화면 유지/소실 거동

---

## 관련 문서

- `docs/audit_report_v4.md` — Streamlit UI Audit (5 dimensions, P0/P1/P2)
- `samples/demo_comparison_roborock/summary.md` — Wave B 샘플 검증
- `samples/kmong_delivery_package/handoff_notes.md` — 크몽 납품 인계 노트

**Verification complete.** 5개 시나리오 모두 PASS (코드 경로 기준). expect-cli 실측 권장 항목 5건은 다음 세션 큐에 등록.
