"""공유 설정 관리 모듈.

pydantic-settings BaseSettings 기반으로 환경변수 및 .env 파일을 로드한다.
get_settings()를 통해 싱글턴 인스턴스에 접근한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """애플리케이션 전체 설정.

    .env 파일 및 환경변수에서 값을 자동으로 로드한다.
    환경변수가 .env 파일보다 우선순위가 높다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- UI ---
    uis_url: str = Field(
        default="",
        description="Urban Immune System 대시보드 URL (빈 문자열이면 링크 미표시)",
    )

    # --- 로깅 ---
    log_level: str = Field(
        default="INFO",
        description="로그 레벨 (DEBUG | INFO | WARNING | ERROR | CRITICAL)",
    )

    # --- 경로 ---
    output_dir: Path = Field(
        default=Path("output"),
        description="산출물(리포트, 데이터 등)을 저장할 루트 디렉토리",
    )
    chrome_driver_path: Path = Field(
        default=Path("/usr/local/bin/chromedriver"),
        description="ChromeDriver 실행 파일 경로",
    )

    # --- 리포트 ---
    report_author: str = Field(
        default="jinyoung-toolkit",
        description="생성된 리포트에 표시할 작성자 이름",
    )

    # --- 크롤링 ---
    crawl_delay_seconds: float = Field(
        default=1.5,
        ge=0.0,
        description="요청 사이 대기 시간 (초). 서버 부하 방지용",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="HTTP 요청 실패 시 최대 재시도 횟수",
    )
    request_timeout: int = Field(
        default=30,
        gt=0,
        description="HTTP 요청 타임아웃 (초)",
    )

    # --- OpenAI ---
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API 키. 미설정 시 LLM 기능 비활성화",
    )

    # --- Anthropic (자동 셀렉터 추론용) ---
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic Claude API 키 (자동 셀렉터 추론용)",
    )
    selector_inference_model: str = Field(
        default="claude-haiku-4-5-20251001",
        description="자동 셀렉터 추론에 사용할 Claude 모델",
    )

    # --- 감성 분석 ---
    sentiment_model: str = Field(
        default="gpt-4o-mini",
        description="감성 분석 모델 (Level 3 LLM API용, 미구현 시 무시됨)",
    )
    sentiment_batch_size: int = Field(
        default=10,
        gt=0,
        description="감성 분석 배치 크기",
    )

    # --- 머신러닝 ---
    random_seed: int = Field(
        default=42,
        description="재현성 보장을 위한 난수 시드",
    )
    test_size: float = Field(
        default=0.3,
        gt=0.0,
        lt=1.0,
        description="학습/테스트 분할 비율 (테스트 비율, 0 < test_size < 1)",
    )

    # --- GCP ---
    gcp_project_id: Optional[str] = Field(
        default=None,
        description="GCP 프로젝트 ID. 미설정 시 GCP 서비스 비활성화",
    )
    gcp_region: str = Field(
        default="asia-northeast3",
        description="GCP 기본 리전 (기본값: 서울)",
    )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """AppSettings 싱글턴 인스턴스를 반환한다.

    lru_cache를 이용해 최초 호출 시 한 번만 생성하며,
    이후 호출은 캐시된 인스턴스를 재사용한다.

    Returns:
        AppSettings: 애플리케이션 설정 인스턴스.

    Example:
        >>> settings = get_settings()
        >>> print(settings.log_level)
        INFO
    """
    return AppSettings()
