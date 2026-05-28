"""
shared/report_base.py — PDF 리포트 공통 상수·헬퍼·베이스 클래스.

report_generator.py 와 comparison_report_generator.py 가 공유하는
색상 상수·레이아웃 상수·유틸 함수를 한 곳에 모아 중복을 제거한다.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# 색상 상수 (PDF 리포트 공통)
# ---------------------------------------------------------------------------
COLOR_HEADER_BG = (0x4A, 0x90, 0xD9)   # #4A90D9 — 테이블 헤더 배경
COLOR_HEADER_FG = (255, 255, 255)       # 흰색 — 테이블 헤더 텍스트
COLOR_INSIGHT_BG = (0xF0, 0xF2, 0xF6)  # #F0F2F6 — 인사이트 박스 배경
COLOR_TEXT = (33, 33, 33)              # 기본 본문 텍스트
COLOR_CAPTION = (100, 100, 100)        # 캡션 텍스트 (회색)
COLOR_HEADING = (30, 30, 30)           # 섹션 제목

# ---------------------------------------------------------------------------
# 레이아웃 상수 (A4 기준)
# ---------------------------------------------------------------------------
PAGE_MARGIN = 15.0        # mm
PAGE_WIDTH_USABLE = 180.0  # A4(210mm) - 좌우 여백(15mm*2)
LINE_HEIGHT = 7.0          # 기본 행 높이 mm


# ---------------------------------------------------------------------------
# 공통 유틸 함수
# ---------------------------------------------------------------------------


def is_nan(val: Any) -> bool:
    """NaN/None 판정 헬퍼."""
    if val is None:
        return True
    if isinstance(val, float):
        return math.isnan(val)
    return False


def format_rating(val: Any) -> str:
    """평점 값을 PDF 표시용 문자열로 변환. NaN/0 → '데이터 부족'."""
    if is_nan(val):
        return "데이터 부족"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "데이터 부족"
    if math.isnan(f) or f == 0.0:
        return "데이터 부족"
    return f"{f:.2f}"


def format_pct(val: Any) -> str:
    """% 값을 PDF 표시용 문자열로 변환. NaN → '-'."""
    if is_nan(val):
        return "-"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(f):
        return "-"
    return f"{f}%"
