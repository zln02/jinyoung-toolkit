"""asyncio 기반 Token Bucket 패턴 속도 제한기."""

import asyncio
import time
from typing import Optional

from shared.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """asyncio 기반 요청 속도 제한기 (Token Bucket 패턴).

    Args:
        requests_per_minute: 분당 최대 요청 수 (기본 30)
        delay_between_requests: 요청 간 최소 대기 시간(초) (기본 1.0)
    """

    def __init__(
        self,
        requests_per_minute: int = 30,
        delay_between_requests: float = 1.0,
    ) -> None:
        self._requests_per_minute = requests_per_minute
        self._delay_between_requests = delay_between_requests
        self._tokens: float = float(requests_per_minute)
        self._max_tokens: float = float(requests_per_minute)
        self._refill_rate: float = requests_per_minute / 60.0  # tokens/sec
        self._last_refill: float = time.monotonic()
        self._last_request: Optional[float] = None
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """경과 시간에 비례해 토큰을 보충한다."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        self._tokens = min(self._max_tokens, self._tokens + added)
        self._last_refill = now

    async def acquire(self) -> None:
        """토큰 하나를 획득. 토큰이 없으면 리필될 때까지 대기."""
        async with self._lock:
            while True:
                try:
                    self._refill()
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        logger.debug(
                            "토큰 획득 완료. 잔여 토큰: %.2f", self._tokens
                        )
                        return
                    wait_seconds = (1.0 - self._tokens) / self._refill_rate
                    logger.debug("토큰 부족. %.3f초 대기", wait_seconds)
                except Exception as exc:
                    logger.error("acquire 중 오류 발생: %s", exc, exc_info=True)
                    raise

                await asyncio.sleep(wait_seconds)

    async def wait(self) -> None:
        """요청 간 최소 대기 시간을 보장."""
        async with self._lock:
            try:
                now = time.monotonic()
                if self._last_request is not None:
                    elapsed = now - self._last_request
                    remaining = self._delay_between_requests - elapsed
                    if remaining > 0:
                        logger.debug("최소 대기 시간 적용. %.3f초 대기", remaining)
                        await asyncio.sleep(remaining)
                self._last_request = time.monotonic()
            except Exception as exc:
                logger.error("wait 중 오류 발생: %s", exc, exc_info=True)
                raise

    def reset(self) -> None:
        """토큰 버킷을 초기 상태로 리셋."""
        self._tokens = self._max_tokens
        self._last_refill = time.monotonic()
        self._last_request = None
        logger.debug("토큰 버킷 리셋 완료. 토큰: %.0f", self._tokens)

    @property
    def available_tokens(self) -> int:
        """현재 사용 가능한 토큰 수."""
        self._refill()
        return int(self._tokens)
