"""
shared/logger.py — structlog 기반 공용 로깅 모듈.

사용법:
    from shared.logger import get_logger

    log = get_logger(__name__)
    log.info("event_name", key="value")

주의:
    이 프로젝트에서 print() 사용은 절대 금지.
    모든 출력은 반드시 이 모듈의 get_logger()를 통해 구조화 로그로 남겨야 한다.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_configured: bool = False


def setup_logging(log_level: str = "INFO") -> None:
    """structlog 전역 설정을 초기화한다.

    환경변수 ``LOG_ENV`` 값이 ``"production"`` 이면 JSON 렌더러를,
    그 외(기본값 ``"development"``)에는 rich ConsoleRenderer를 사용한다.

    Args:
        log_level: 문자열 로그 레벨. 예) ``"DEBUG"``, ``"INFO"``, ``"WARNING"``.
            대소문자 무관. 기본값은 ``"INFO"``.

    Note:
        이미 설정이 완료된 경우(_configured == True) 재호출해도 무시된다.
        print() 사용 금지 — 로깅은 반드시 get_logger()로만 수행할 것.
    """
    global _configured
    if _configured:
        return

    level: int = getattr(logging, log_level.upper(), logging.INFO)

    def _add_logger_name_safe(
        logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """PrintLogger 호환 logger name 프로세서."""
        event_dict.setdefault(
            "logger", getattr(logger, "name", None) or ""
        )
        return event_dict

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_logger_name_safe,
        structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    log_env: str = os.getenv("LOG_ENV", "development").lower()
    is_production: bool = log_env == "production"

    if is_production:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # stdlib logging도 동일 레벨로 맞춰준다 (서드파티 라이브러리 로그 포함).
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """name에 해당하는 structlog BoundLogger를 반환한다.

    최초 호출 전 setup_logging()이 실행되지 않은 경우 자동으로 기본값으로 초기화한다.

    Args:
        name: 로거 이름. 일반적으로 ``__name__`` 을 전달한다.

    Returns:
        structlog.stdlib.BoundLogger: name이 바인딩된 구조화 로거 인스턴스.

    Example:
        log = get_logger(__name__)
        log.info("user_created", user_id=42)

    Note:
        print() 사용 금지 — 반드시 이 함수를 통해 로그를 남길 것.
    """
    if not _configured:
        setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))

    return structlog.get_logger(name)


# 모듈 import 시 자동 초기화.
setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
