"""
shared/comparison_report_generator.py — 경쟁사 비교 리포트 PDF 생성기.

ComparisonReport(comparator.py)를 받아 ReportGenerator(report_generator.py)로
PDF를 렌더링한다. NaN/0건/빈 인사이트에 대한 방어 레이어가 포함되어 있다.

사용법:
    from pathlib import Path
    from shared.comparison_report_generator import ComparisonReportGenerator

    gen = ComparisonReportGenerator()
    gen.render(report, Path("output/cmp_report.pdf"))
"""

from __future__ import annotations

import math
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from review_analyzer.comparator import ComparisonReport
from shared.korean_nlp import KoreanTextProcessor
from shared.logger import get_logger
from shared.report_generator import ReportGenerator

log = get_logger(__name__)


def _is_nan(val: Any) -> bool:
    """NaN/None 판정 헬퍼."""
    if val is None:
        return True
    if isinstance(val, float):
        return math.isnan(val)
    return False


def _format_rating(val: Any) -> str:
    """평점 값을 PDF 표시용 문자열로 변환. NaN/0 → '데이터 부족'."""
    if _is_nan(val):
        return "데이터 부족"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "데이터 부족"
    if math.isnan(f) or f == 0.0:
        return "데이터 부족"
    return f"{f:.2f}"


def _format_pct(val: Any) -> str:
    """% 값을 PDF 표시용 문자열로 변환. NaN → '-'."""
    if _is_nan(val):
        return "-"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(f):
        return "-"
    return f"{f}%"


class ComparisonReportGenerator:
    """ComparisonReport를 PDF로 렌더링하는 클래스."""

    def __init__(self) -> None:
        """ComparisonReportGenerator 초기화."""
        log.info("ComparisonReportGenerator_초기화")

    def render(self, report: ComparisonReport, output_path: Path) -> Path:
        """ComparisonReport를 PDF로 저장한다.

        Args:
            report: comparator.ProductComparator.run() 이 반환한 ComparisonReport.
            output_path: 저장할 PDF 파일 경로.

        Returns:
            저장된 PDF 파일의 절대 Path.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rg = ReportGenerator(title="경쟁사 리뷰 한눈에 비교 리포트")

        # 제품이 없는 경우 최소 리포트 저장
        if not report.products:
            log.warning("비교_제품_없음 — 최소_리포트_저장")
            rg.add_insight(
                "비교할 제품 데이터가 없습니다. URL을 확인한 후 다시 시도해 주세요."
            )
            return rg.save(output_path)

        now_kst = datetime.now(tz=ZoneInfo("Asia/Seoul"))
        total_reviews = sum(row.get("review_count", 0) for row in report.summary_rows)
        product_count = len(report.summary_rows)  # 0건 제품 제외된 수

        # 섹션 1: 데이터 개요
        rg.add_section(
            "데이터 개요",
            (
                f"비교 제품 수: {product_count}개\n"
                f"총 리뷰 수: {total_reviews:,}건\n"
                f"분석일시: {now_kst.strftime('%Y-%m-%d %H:%M')} (KST)"
            ),
        )

        # 크롤링 실패 제품 경고 (있을 때만)
        if report.failed_products:
            failed_labels = ", ".join(report.failed_products)
            rg.add_insight(
                f"⚠️ 크롤링 실패 제품: {failed_labels} — 아래 분석에서 제외됨"
            )

        # 요약 비교 테이블 (NaN 방어)
        if report.summary_rows:
            try:
                headers = ["제품명", "리뷰 수", "평균 평점", "긍정%", "부정%"]
                table_rows: list[list[str]] = []
                for row in report.summary_rows:
                    table_rows.append(
                        [
                            str(row.get("label", "")),
                            str(row.get("review_count", 0)),
                            _format_rating(row.get("avg_rating")),
                            _format_pct(row.get("positive_pct")),
                            _format_pct(row.get("negative_pct")),
                        ]
                    )
                rg.add_table(headers, table_rows)
            except Exception:
                log.exception("요약_테이블_렌더링_실패")
        else:
            rg.add_insight(
                "표시할 요약 데이터가 없습니다. 모든 제품에서 리뷰 수집에 실패했을 수 있어요."
            )

        # 차트 PNG 생성 (임시 디렉토리)
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            self._add_charts(rg, report, tmp_dir)
        finally:
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                log.warning("임시_디렉토리_정리_실패", path=str(tmp_dir))

        # 인사이트 섹션: win/lose/action 전부 빈 경우 단일 경고로 스킵
        has_any_insight = bool(
            report.win_points or report.lose_points or report.action_items
        )
        if not has_any_insight:
            rg.add_section("종합 분석", "")
            rg.add_insight(
                "리뷰 데이터가 충분치 않아 명확한 차별화 포인트를 도출할 수 없습니다. "
                "리뷰 수 50건 이상 제품으로 다시 시도해 주세요."
            )
        else:
            # 섹션 2: 우리가 이기는 포인트 (내용 있을 때만)
            if report.win_points:
                rg.add_section("우리가 이기는 포인트", "")
                for point in report.win_points:
                    try:
                        rg.add_insight(f"WIN: {point}")
                    except Exception:
                        log.exception("win_point_렌더링_실패", point=point)

            # 섹션 3: 우리가 지는 포인트 (내용 있을 때만)
            if report.lose_points:
                rg.add_section("우리가 지는 포인트", "")
                for point in report.lose_points:
                    try:
                        rg.add_insight(f"LOSE: {point}")
                    except Exception:
                        log.exception("lose_point_렌더링_실패", point=point)

            # 섹션 4: 권장 개선 포인트 (내용 있을 때만, 이름 변경)
            if report.action_items:
                rg.add_section("권장 개선 포인트", "")
                for item in report.action_items:
                    try:
                        rg.add_insight(f"ACTION: {item}")
                    except Exception:
                        log.exception("action_item_렌더링_실패", item=item)

        # 푸터 캡션
        try:
            rg.add_insight(
                "※ 리뷰 수 차이가 클 경우 비율 기준 비교가 더 공정합니다."
            )
        except Exception:
            log.exception("푸터_캡션_렌더링_실패")

        return rg.save(output_path)

    def _add_charts(
        self,
        rg: ReportGenerator,
        report: ComparisonReport,
        tmp_dir: Path,
    ) -> None:
        """matplotlib 차트 2개를 생성해 ReportGenerator에 삽입한다.

        Args:
            rg: ReportGenerator 인스턴스.
            report: ComparisonReport.
            tmp_dir: PNG 임시 저장 디렉토리.
        """
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # 한글 폰트 설정
        try:
            font_path = KoreanTextProcessor.find_korean_font()
            import matplotlib.font_manager as fm
            fm.fontManager.addfont(str(font_path))
            font_name = fm.FontProperties(fname=str(font_path)).get_name()
            plt.rcParams["font.family"] = font_name
        except Exception:
            log.warning("한글_폰트_설정_실패 — 기본_폰트_사용")

        if not report.summary_rows:
            return

        labels = [row.get("label", "") for row in report.summary_rows]

        # 차트 1: 감성 분포 스택 바차트 (전부 0이면 스킵)
        pos_pcts = [
            float(row.get("positive_pct") or 0.0)
            for row in report.summary_rows
        ]
        neg_pcts = [
            float(row.get("negative_pct") or 0.0)
            for row in report.summary_rows
        ]
        all_zero_sentiment = all(
            p == 0 and n == 0 for p, n in zip(pos_pcts, neg_pcts)
        )
        if all_zero_sentiment:
            log.warning("감성_비율_전부_0 — 스택바_차트_스킵")
            rg.add_insight(
                "감성 분석 결과가 충분하지 않아 감성 분포 차트를 생략했습니다."
            )
        else:
            stack_path = tmp_dir / "sentiment_stack.png"
            try:
                neu_pcts = [
                    max(0.0, 100.0 - p - n)
                    for p, n in zip(pos_pcts, neg_pcts)
                ]
                x = range(len(labels))
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.bar(x, pos_pcts, label="긍정", color="#4CAF50")
                ax.bar(x, neu_pcts, bottom=pos_pcts, label="중립", color="#9E9E9E")
                ax.bar(
                    x,
                    neg_pcts,
                    bottom=[p + n for p, n in zip(pos_pcts, neu_pcts)],
                    label="부정",
                    color="#F44336",
                )
                ax.set_xticks(list(x))
                ax.set_xticklabels(labels, fontsize=9)
                ax.set_ylabel("비율 (%)")
                ax.set_title("제품별 감성 분포")
                ax.legend(loc="upper right")
                fig.tight_layout()
                fig.savefig(stack_path, dpi=120)
                plt.close(fig)
                rg.add_chart(stack_path, caption="제품별 긍정/중립/부정 감성 분포 (%)")
            except Exception:
                log.exception("감성_스택바_차트_생성_실패")

        # 차트 2: 평균 평점 바차트 (전부 0이면 스킵)
        rating_path = tmp_dir / "avg_rating_bar.png"
        try:
            raw_ratings = [row.get("avg_rating") for row in report.summary_rows]
            avg_ratings = [
                float(r) if r is not None and not _is_nan(r) else 0.0
                for r in raw_ratings
            ]
            if any(r > 0 for r in avg_ratings):
                fig, ax = plt.subplots(figsize=(7, 4))
                bars = ax.bar(
                    range(len(labels)),
                    avg_ratings,
                    color="#2196F3",
                )
                ax.set_xticks(list(range(len(labels))))
                ax.set_xticklabels(labels, fontsize=9)
                ax.set_ylabel("평균 평점")
                ax.set_ylim(0, 5.5)
                ax.set_title("제품별 평균 평점 비교")
                for bar, val in zip(bars, avg_ratings):
                    if val > 0:
                        ax.text(
                            bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + 0.05,
                            f"{val:.2f}",
                            ha="center",
                            va="bottom",
                            fontsize=9,
                        )
                fig.tight_layout()
                fig.savefig(rating_path, dpi=120)
                plt.close(fig)
                rg.add_chart(rating_path, caption="제품별 평균 평점 비교")
            else:
                log.warning("평균_평점_전부_0 — 바차트_스킵")
        except Exception:
            log.exception("평균_평점_바차트_생성_실패")
