"""
shared/report_generator.py — fpdf2 기반 범용 한글 PDF 리포트 생성기.

사용법:
    from pathlib import Path
    from shared.report_generator import ReportGenerator

    rg = ReportGenerator(title="분석 리포트", author="박진영")
    rg.add_section("개요", "이 리포트는 ...")
    rg.add_table(["항목", "값"], [["정확도", "92.3%"], ["F1", "0.91"]])
    rg.add_chart(Path("chart.png"), caption="모델 성능 그래프")
    rg.add_insight("핵심 인사이트: 모델이 전반적으로 안정적으로 동작한다.")
    output = rg.save(Path("report.pdf"))
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF

from shared.korean_nlp import KoreanTextProcessor
from shared.logger import get_logger
from shared.report_base import (
    COLOR_CAPTION,
    COLOR_HEADER_BG,
    COLOR_HEADER_FG,
    COLOR_HEADING,
    COLOR_INSIGHT_BG,
    COLOR_TEXT,
    LINE_HEIGHT,
    PAGE_MARGIN,
    PAGE_WIDTH_USABLE,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 내부 별칭 (하위 호환 — 기존 코드가 _COLOR_* 로 참조하는 부분 유지)
# ---------------------------------------------------------------------------
_COLOR_HEADER_BG = COLOR_HEADER_BG
_COLOR_HEADER_FG = COLOR_HEADER_FG
_COLOR_INSIGHT_BG = COLOR_INSIGHT_BG
_COLOR_TEXT = COLOR_TEXT
_COLOR_CAPTION = COLOR_CAPTION
_COLOR_HEADING = COLOR_HEADING
_PAGE_MARGIN = PAGE_MARGIN
_PAGE_WIDTH_USABLE = PAGE_WIDTH_USABLE
_LINE_HEIGHT = LINE_HEIGHT


class ReportGenerator:
    """fpdf2 기반 한글 PDF 리포트 생성기.

    섹션·테이블·차트·인사이트 박스를 조합하여 구조화된
    PDF 문서를 생성한다. 한글 폰트를 자동으로 탐색·등록한다.

    Args:
        title: 리포트 제목.
        author: 작성자 이름. 기본값 "박진영".
        font_path: 한글 TrueType 폰트 파일 경로.
            None이면 KoreanTextProcessor.find_korean_font()로 자동 탐색.

    Raises:
        RuntimeError: 한글 폰트를 찾을 수 없을 때.
        FileNotFoundError: font_path가 지정됐으나 파일이 없을 때.
    """

    def __init__(
        self,
        title: str,
        author: str = "박진영",
        font_path: Path | None = None,
    ) -> None:
        """ReportGenerator를 초기화하고 첫 페이지 헤더를 출력한다."""
        self._title = title
        self._author = author

        # 폰트 경로 결정
        if font_path is None:
            try:
                resolved_font = KoreanTextProcessor.find_korean_font()
            except RuntimeError as exc:
                log.error("한글_폰트_자동_탐색_실패", error=str(exc))
                raise
        else:
            resolved_font = Path(font_path).resolve()
            if not resolved_font.is_file():
                raise FileNotFoundError(
                    f"지정된 폰트 파일이 없습니다: {resolved_font}"
                )

        log.info("한글_폰트_사용", path=str(resolved_font))

        # FPDF 인스턴스 생성
        self._pdf = FPDF(orientation="P", unit="mm", format="A4")
        self._pdf.set_margins(
            left=_PAGE_MARGIN,
            top=_PAGE_MARGIN,
            right=_PAGE_MARGIN,
        )
        self._pdf.set_auto_page_break(auto=True, margin=_PAGE_MARGIN)

        # 한글 폰트 등록 (Regular + Bold)
        try:
            self._pdf.add_font("Korean", "", str(resolved_font))
            self._pdf.add_font("Korean", "B", str(resolved_font))
        except Exception as exc:
            log.error("폰트_등록_실패", font=str(resolved_font), error=str(exc))
            raise

        # 첫 페이지 추가 및 헤더 출력
        self._pdf.add_page()
        self._render_header()

        log.info(
            "ReportGenerator_초기화_완료",
            title=title,
            author=author,
            font=str(resolved_font),
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _set_korean(self, style: str = "", size: float = 12.0) -> None:
        """한글 폰트를 지정된 스타일·크기로 설정한다.

        Args:
            style: 폰트 스타일. "" (regular) 또는 "B" (bold).
            size: 폰트 크기 (pt).
        """
        self._pdf.set_font("Korean", style=style, size=size)

    def _render_header(self) -> None:
        """제목·저자·날짜 헤더를 첫 페이지 상단에 출력한다."""
        pdf = self._pdf
        now_kst = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        date_str = now_kst.strftime("%Y-%m-%d")

        # 제목
        self._set_korean(style="B", size=20)
        pdf.set_text_color(*_COLOR_HEADING)
        pdf.cell(
            w=_PAGE_WIDTH_USABLE,
            h=12,
            text=self._title,
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        # 저자 / 날짜 (동일 행에 좌우 배치)
        self._set_korean(style="", size=10)
        pdf.set_text_color(*_COLOR_CAPTION)
        pdf.cell(
            w=_PAGE_WIDTH_USABLE / 2,
            h=8,
            text=f"작성자: {self._author}",
            align="L",
            new_x="RIGHT",
            new_y="TOP",
        )
        pdf.cell(
            w=_PAGE_WIDTH_USABLE / 2,
            h=8,
            text=f"작성일: {date_str}",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )

        # 구분선 (가로 직선)
        pdf.set_draw_color(*_COLOR_HEADER_BG)
        pdf.set_line_width(0.5)
        y_line = pdf.get_y() + 2
        pdf.line(
            x1=_PAGE_MARGIN,
            y1=y_line,
            x2=_PAGE_MARGIN + _PAGE_WIDTH_USABLE,
            y2=y_line,
        )
        pdf.set_y(y_line + 5)

        # 색상 초기화
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)

        log.debug("헤더_렌더링_완료", title=self._title, date=date_str)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_section(self, heading: str, content: str) -> None:
        """섹션 제목과 본문을 추가한다.

        제목은 볼드 14pt, 본문은 12pt로 출력한다.

        Args:
            heading: 섹션 제목 문자열.
            content: 섹션 본문 텍스트. 줄바꿈(\\n) 지원.
        """
        pdf = self._pdf
        pdf.ln(4)

        # 섹션 제목
        self._set_korean(style="B", size=14)
        pdf.set_text_color(*_COLOR_HEADING)
        pdf.multi_cell(
            w=_PAGE_WIDTH_USABLE,
            h=_LINE_HEIGHT + 1,
            text=heading,
            align="L",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(1)

        # 본문
        self._set_korean(style="", size=12)
        pdf.set_text_color(*_COLOR_TEXT)
        try:
            pdf.multi_cell(
                w=_PAGE_WIDTH_USABLE,
                h=_LINE_HEIGHT,
                text=content,
                align="L",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        except Exception as exc:
            log.error("섹션_본문_렌더링_실패", heading=heading, error=str(exc))
            raise

        pdf.ln(3)
        log.debug("섹션_추가", heading=heading, content_len=len(content))

    def add_table(
        self,
        headers: list[str],
        rows: list[list[str]],
    ) -> None:
        """테이블을 추가한다.

        열 너비는 균등 분배하며, 헤더 배경색은 #4A90D9, 텍스트는 흰색이다.

        Args:
            headers: 컬럼 헤더 문자열 리스트.
            rows: 데이터 행 리스트. 각 행은 headers와 동일한 수의 원소를 가진다.

        Raises:
            ValueError: headers가 비어 있을 때.
        """
        if not headers:
            raise ValueError("테이블 headers가 비어 있습니다.")

        pdf = self._pdf
        pdf.ln(4)

        n_cols = len(headers)
        col_w = _PAGE_WIDTH_USABLE / n_cols
        row_h = _LINE_HEIGHT + 1

        # ---------- 헤더 행 ----------
        self._set_korean(style="B", size=11)
        pdf.set_fill_color(*_COLOR_HEADER_BG)
        pdf.set_text_color(*_COLOR_HEADER_FG)

        for i, header in enumerate(headers):
            is_last = i == n_cols - 1
            pdf.cell(
                w=col_w,
                h=row_h,
                text=str(header),
                border=1,
                align="C",
                fill=True,
                new_x="RIGHT" if not is_last else "LMARGIN",
                new_y="TOP" if not is_last else "NEXT",
            )

        # ---------- 데이터 행 ----------
        self._set_korean(style="", size=10)
        pdf.set_fill_color(245, 245, 245)
        pdf.set_text_color(*_COLOR_TEXT)

        try:
            for row_idx, row in enumerate(rows):
                fill_row = row_idx % 2 == 1  # 홀수 행 음영
                for col_idx, cell_val in enumerate(row):
                    is_last = col_idx == n_cols - 1
                    pdf.cell(
                        w=col_w,
                        h=row_h,
                        text=str(cell_val),
                        border=1,
                        align="C",
                        fill=fill_row,
                        new_x="RIGHT" if not is_last else "LMARGIN",
                        new_y="TOP" if not is_last else "NEXT",
                    )
        except Exception as exc:
            log.error("테이블_데이터_렌더링_실패", error=str(exc))
            raise

        # 색상 초기화
        pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(*_COLOR_TEXT)
        pdf.ln(4)

        log.debug(
            "테이블_추가",
            cols=n_cols,
            rows=len(rows),
        )

    def add_chart(self, image_path: Path, caption: str = "") -> None:
        """차트 이미지를 삽입한다.

        이미지 너비는 170mm로 고정되며, 가로 중앙 정렬된다.
        caption이 있으면 이미지 아래에 회색 소문자로 출력한다.

        Args:
            image_path: 삽입할 이미지 파일의 경로.
            caption: 이미지 아래 출력할 캡션 문자열. 기본값 "".

        Raises:
            FileNotFoundError: 이미지 파일이 존재하지 않을 때.
        """
        resolved = Path(image_path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(
                f"차트 이미지 파일이 없습니다: {resolved}"
            )

        pdf = self._pdf
        pdf.ln(4)

        image_w = 170.0
        x_offset = _PAGE_MARGIN + (_PAGE_WIDTH_USABLE - image_w) / 2

        try:
            pdf.image(
                str(resolved),
                x=x_offset,
                y=None,
                w=image_w,
                keep_aspect_ratio=True,
            )
        except Exception as exc:
            log.error("이미지_삽입_실패", path=str(resolved), error=str(exc))
            raise

        if caption:
            pdf.ln(2)
            self._set_korean(style="", size=9)
            pdf.set_text_color(*_COLOR_CAPTION)
            pdf.multi_cell(
                w=_PAGE_WIDTH_USABLE,
                h=5,
                text=caption,
                align="C",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(*_COLOR_TEXT)

        pdf.ln(4)
        log.debug("차트_추가", path=str(resolved), caption_len=len(caption))

    def add_insight(self, text: str) -> None:
        """인사이트 박스를 추가한다.

        배경색 #F0F2F6의 패딩이 있는 박스 안에 텍스트를 출력한다.

        Args:
            text: 인사이트 내용 문자열. 줄바꿈(\\n) 지원.
        """
        pdf = self._pdf
        pdf.ln(4)

        padding = 4.0       # 박스 내부 패딩 mm
        text_w = _PAGE_WIDTH_USABLE - padding * 2

        # 텍스트 높이를 미리 계산 (dry_run)
        self._set_korean(style="", size=11)
        text_height: float = pdf.multi_cell(
            w=text_w,
            h=_LINE_HEIGHT,
            text=text,
            align="L",
            dry_run=True,
            output="HEIGHT",  # type: ignore[arg-type]
        )  # type: ignore[assignment]

        box_h = float(text_height) + padding * 2
        box_x = _PAGE_MARGIN
        box_y = pdf.get_y()

        # 자동 페이지 브레이크가 박스 중간에 발생하지 않도록 처리
        page_h_remaining = pdf.page_break_trigger - box_y  # type: ignore[attr-defined]
        if box_h > page_h_remaining:
            pdf.add_page()
            box_y = pdf.get_y()

        # 배경 직사각형
        try:
            pdf.set_fill_color(*_COLOR_INSIGHT_BG)
            pdf.rect(x=box_x, y=box_y, w=_PAGE_WIDTH_USABLE, h=box_h, style="F")
        except Exception as exc:
            log.error("인사이트_박스_배경_렌더링_실패", error=str(exc))
            raise

        # 텍스트 출력 (패딩 적용)
        pdf.set_xy(box_x + padding, box_y + padding)
        self._set_korean(style="", size=11)
        pdf.set_text_color(*_COLOR_TEXT)
        try:
            pdf.multi_cell(
                w=text_w,
                h=_LINE_HEIGHT,
                text=text,
                align="L",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        except Exception as exc:
            log.error("인사이트_텍스트_렌더링_실패", error=str(exc))
            raise

        pdf.set_y(box_y + box_h + 4)
        pdf.set_fill_color(255, 255, 255)

        log.debug("인사이트_추가", text_len=len(text))

    def save(self, output_path: Path) -> Path:
        """PDF를 파일로 저장한다.

        부모 디렉토리가 없으면 자동으로 생성한다.

        Args:
            output_path: 저장할 PDF 파일 경로.

        Returns:
            저장된 PDF 파일의 절대 Path.

        Raises:
            OSError: 파일 쓰기에 실패했을 때.
        """
        resolved = Path(output_path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._pdf.output(str(resolved))
        except Exception as exc:
            log.error("PDF_저장_실패", path=str(resolved), error=str(exc))
            raise OSError(f"PDF 저장 실패 ({resolved}): {exc}") from exc

        log.info("PDF_저장_완료", path=str(resolved))
        return resolved
