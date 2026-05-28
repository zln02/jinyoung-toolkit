# 지원 사이트 크롤 검증 (SITE_VERIFICATION)

> 검증일 2026-05-27 · 환경: GCP e2-small, `.venv` Python 3.11 · 보수적 판정(애매=제약/불가)
> 판정: ✅ 현 환경 즉시 동작 / 🟡 조건부(설치·키·URL·robots) / ❌ 현 환경 불가

## 핵심 결론
- **프리셋 15종 전부 스키마 유효**(`PresetLoader.load` 성공) — 코드/설정 구조는 정상.
- **그러나 현 환경에서 "즉시 되는" 사이트는 사실상 0개**:
  - `.venv`에 **selenium 미설치** → selenium 기반 **12종 전부 동작 불가**
  - 유일한 httpx 프리셋 `naver_blog`는 대상(search.naver.com)이 **robots.txt로 자동수집 차단**(실측 `allowed=False`)
  - api 프리셋 2종은 **앱 URL 또는 API 키**가 있어야 동작
- 즉 발표 데모를 하려면 ① selenium+chromium 설치(메모리·차단 위험) 또는 ② api 경로(공공데이터 키/앱 URL) 중 하나가 필요.

## 프리셋별 판정

| 프리셋 | driver | 현 환경 | 근거 / 비고 |
|---|---|---|---|
| amazon_reviews | selenium | ❌ | selenium 미설치. 설치해도 해외+봇차단 강함 |
| cgv_movie | selenium | ❌ | selenium 미설치 |
| coupang_reviews | selenium | ❌ | selenium 미설치 + **쿠팡은 클라우드 IP 차단** 알려짐 |
| custom_template | selenium | ❌ | selenium 미설치 (UI 숨김 템플릿) |
| eleven_st | selenium | ❌ | selenium 미설치 |
| google_play | selenium | ❌ | selenium 미설치 |
| melon_song | selenium | ❌ | selenium 미설치 |
| naver_cafe | selenium | ❌ | selenium 미설치 + 로그인/동적 로딩 |
| naver_shopping | selenium | ❌ | selenium 미설치 + 봇차단 |
| yanolja_hotel | selenium | ❌ | selenium 미설치 |
| yes24_book | selenium | ❌ | selenium 미설치 |
| youtube_comments | selenium | ❌ | selenium 미설치 + 동적 스크롤 |
| **naver_blog** | httpx | 🟡 | 코드 동작하나 **robots 차단(False)** — `respect_robots_txt=False`로 강제 시에만, 약관 위반 위험 |
| **apple_app_store** | api | 🟡 | APIDriver 동작 검증됨. **앱 RSS URL 입력 시 수집 가능**(키 불필요, 공개 RSS) — 현 구조상 가장 현실적 |
| **public_data_example** | api | 🟡 | 신규 템플릿. `PUBLIC_DATA_API_KEY`(.env) + 엔드포인트/필드 교체 시 동작 |

집계: ✅ 0 · 🟡 3 · ❌ 12

## 권장 조치 (발표 D-2 기준)
1. **즉시 가능한 데모 경로**: `apple_app_store`(공개 RSS, 키 불필요)로 api 크롤 시연 → 가장 마찰 적음.
2. **공공데이터 연동**: `public_data_example` 템플릿에 data.go.kr 키(.env) + 대상 API 채우면 Layer A/D 신호 수집 가능(이번 작업으로 인프라 완비).
3. **selenium 12종 활성화**(선택): `pip install selenium` + chromium(이미 `/usr/bin/chromium` 존재) 필요. 단 e2-small 4GB 메모리 부담 + 쿠팡/네이버 등 클라우드 IP 차단 가능성 → 발표 데모는 로컬/우회 권장.

## 검증 방법(재현)
- 프리셋 로드: `PresetLoader().load(<name>)` 15종 — 전부 성공
- selenium: `python -c "import selenium"` → ImportError(MISSING)
- robots: `LegalComplianceChecker.check_robots_txt("https://search.naver.com/...")` → False
