"""경쟁사 비교 리포트 모듈.

ProductComparator — 우리 제품 + 경쟁사(1~3) URL을 병렬 크롤링·분석하여
비교 리포트(ComparisonReport)를 생성한다.

재사용:
- review_analyzer.crawler.engine.CrawlerEngine / CrawlConfig / DriverType
- review_analyzer.analyzer.ReviewAnalyzer / AnalysisResult
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from review_analyzer.analyzer import AnalysisResult, ReviewAnalyzer
from review_analyzer.crawler.engine import (
    CrawlConfig,
    CrawlerEngine,
    DriverType,
)
from shared.logger import get_logger

logger = get_logger(__name__)

MAX_PRODUCTS = 4
MIN_PRODUCTS = 2

# diagnose_gaps 임계값
_POS_PCT_GAP_THRESHOLD = 10.0
_RATING_GAP_THRESHOLD = 0.3
_COMP_POS_TOP_N = 5
_OUR_POS_COMPARE_N = 10
_OUR_POS_TOP_N = 5
_COMP_POS_TOP_N_UNION = 10
_OUR_NEG_TOP_N = 3
_COMP_NEG_TOP_N_UNION = 10
_MAX_ACTION_ITEMS = 5

# generate_action_items 정규식 (모듈 레벨 캐시)
_RE_COMP_STRENGTH = re.compile(r"경쟁사 강점 미언급: (.+)")
_RE_OUR_WEAKNESS = re.compile(r"우리만의 약점: (.+)")


@dataclass
class ProductInput:
    """비교 대상 제품 1개의 입력값.

    Args:
        label: 표시용 라벨 (예: "우리 제품", "경쟁사 A").
        url: 크롤링 대상 URL.
        preset_name: 사용할 프리셋 이름 (4개 모두 동일 사이트 가정).
    """

    label: str
    url: str
    preset_name: str


@dataclass
class ProductAnalyzed:
    """제품 1개의 크롤링·분석 결과.

    Args:
        label: ProductInput.label 과 동일.
        url: 크롤링 원본 URL.
        preset_name: 사용된 프리셋 이름.
        df: 크롤링 + 전처리된 DataFrame.
        result: ReviewAnalyzer.run() 결과.
    """

    label: str
    url: str
    preset_name: str
    df: pd.DataFrame
    result: AnalysisResult


@dataclass
class ComparisonReport:
    """비교 리포트 산출물.

    Args:
        products: 분석된 제품 리스트 (첫 원소 = primary/우리 제품).
        summary_rows: 요약 테이블 행 (label/리뷰수/평균평점/긍정%/부정%).
        win_points: 우리가 이기는 포인트 문자열 리스트.
        lose_points: 우리가 지는 포인트 문자열 리스트.
        action_items: 규칙 기반 파생 액션 아이템.
        failed_products: 크롤링 0건이거나 분석 실패한 제품 라벨 리스트.
    """

    products: list[ProductAnalyzed]
    summary_rows: list[dict[str, Any]] = field(default_factory=list)
    win_points: list[str] = field(default_factory=list)
    lose_points: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    failed_products: list[str] = field(default_factory=list)


class ProductComparator:
    """우리 제품 vs 경쟁사(1~3) 비교기.

    Args:
        products: ProductInput 리스트. 2~4개만 허용. 첫 원소 = primary.
        preset: 프리셋 딕셔너리 (analysis 섹션에서 text_column/rating_column 추출).

    Raises:
        ValueError: 제품 개수가 2~4 범위를 벗어날 때.
    """

    def __init__(
        self,
        products: list[ProductInput],
        preset: dict[str, Any],
    ) -> None:
        if not (MIN_PRODUCTS <= len(products) <= MAX_PRODUCTS):
            raise ValueError(
                f"제품 개수는 {MIN_PRODUCTS}~{MAX_PRODUCTS}개여야 합니다. "
                f"현재: {len(products)}"
            )
        self._products = products
        self._preset = preset

        analysis_cfg: dict[str, Any] = preset.get("analysis", {}) or {}
        self._text_column: str = analysis_cfg.get("text_column", "content")
        raw_rating = analysis_cfg.get("rating_column", "rating")
        self._rating_column: str | None = (
            None if raw_rating in (None, "", "none") else raw_rating
        )
        self._rating_parse_pattern: str | None = analysis_cfg.get("rating_parse_pattern") or None

    # ------------------------------------------------------------------
    # 크롤링 / 분석 (Phase 1 sonnet #1 구현)
    # ------------------------------------------------------------------

    async def crawl_all(
        self,
        max_pages: int,
        driver: DriverType,
        respect_robots: bool,
    ) -> list[tuple[ProductInput, pd.DataFrame]]:
        """4개 제품을 병렬 크롤링. 각 제품당 독립 CrawlerEngine 인스턴스."""
        engines = []
        for product in self._products:
            cfg = CrawlConfig(
                preset_name=product.preset_name,
                target_urls=[product.url],
                max_pages=max_pages,
                driver_type=driver,
                respect_robots_txt=respect_robots,
            )
            engines.append(CrawlerEngine(cfg, self._preset))

        results = await asyncio.gather(
            *[engine.run() for engine in engines],
            return_exceptions=True,
        )

        output: list[tuple[ProductInput, pd.DataFrame]] = []
        for product, result in zip(self._products, results):
            if isinstance(result, Exception):
                logger.error(
                    "제품 크롤링 실패: label=%s, url=%s, error=%s",
                    product.label,
                    product.url,
                    result,
                )
                output.append((product, pd.DataFrame()))
            else:
                output.append((product, result.data))

        return output

    def analyze_all(
        self,
        crawled: list[tuple[ProductInput, pd.DataFrame]],
    ) -> list[ProductAnalyzed]:
        """크롤링된 DataFrame들을 ReviewAnalyzer로 분석."""
        analyzer = ReviewAnalyzer(
            text_column=self._text_column,
            rating_column=self._rating_column,
            rating_parse_pattern=self._rating_parse_pattern,
        )

        analyzed: list[ProductAnalyzed] = []
        for product, df in crawled:
            if df.empty or self._text_column not in df.columns:
                result = AnalysisResult.empty()
            else:
                try:
                    result = analyzer.run(df)
                except Exception:
                    logger.exception(
                        "분석 실패: label=%s, url=%s", product.label, product.url
                    )
                    result = AnalysisResult.empty()

            analyzed.append(
                ProductAnalyzed(
                    label=product.label,
                    url=product.url,
                    preset_name=product.preset_name,
                    df=df,
                    result=result,
                )
            )

        return analyzed

    def build_summary(
        self,
        analyzed: list[ProductAnalyzed],
    ) -> list[dict[str, Any]]:
        """요약 비교 테이블 행 생성. 0건 제품은 자동 제외."""
        rows: list[dict[str, Any]] = []
        for p in analyzed:
            total = p.result.total_reviews
            if total == 0:
                # 0건 제품은 summary에서 제외 (failed_products로 이미 분류됨)
                continue
            pos_count = p.result.sentiment_distribution.get("positive", 0)
            neg_count = p.result.sentiment_distribution.get("negative", 0)

            positive_pct = round(pos_count / total * 100, 1)
            negative_pct = round(neg_count / total * 100, 1)

            if not p.df.empty and self._text_column in p.df.columns:
                avg_text_len = round(
                    float(p.df[self._text_column].str.len().mean()), 1
                )
            else:
                avg_text_len = 0.0

            rows.append(
                {
                    "label": p.label,
                    "review_count": total,
                    "avg_rating": round(p.result.avg_rating, 2),
                    "positive_pct": positive_pct,
                    "negative_pct": negative_pct,
                    "avg_text_length": avg_text_len,
                }
            )
        return rows

    def diagnose_gaps(
        self,
        analyzed: list[ProductAnalyzed],
    ) -> tuple[list[str], list[str]]:
        """win_points, lose_points 규칙 기반 진단. 0건 경쟁사는 자동 제외."""
        if len(analyzed) < 2:
            return [], []

        our = analyzed[0]
        # 0건 경쟁사는 비교에서 제외
        competitors = [c for c in analyzed[1:] if c.result.total_reviews > 0]

        if not competitors:
            return [], []

        # 우리 제품도 0건이면 진단 불가
        if our.result.total_reviews == 0:
            return [], []

        win_points: list[str] = []
        lose_points: list[str] = []

        # --- 긍정 비율 차이 ---
        our_total = our.result.total_reviews or 1
        our_pos = our.result.sentiment_distribution.get("positive", 0)
        our_pos_pct = our_pos / our_total * 100

        competitor_pos_pcts: list[float] = []
        for comp in competitors:
            comp_total = comp.result.total_reviews or 1
            comp_pos = comp.result.sentiment_distribution.get("positive", 0)
            competitor_pos_pcts.append(comp_pos / comp_total * 100)

        comp_avg_pos_pct = sum(competitor_pos_pcts) / len(competitor_pos_pcts)

        if our_pos_pct < comp_avg_pos_pct - _POS_PCT_GAP_THRESHOLD:
            lose_points.append(
                f"전반적 만족도 낮음 (우리 {our_pos_pct:.1f}% vs 경쟁사 평균 {comp_avg_pos_pct:.1f}%)"
            )
        elif our_pos_pct > comp_avg_pos_pct + _POS_PCT_GAP_THRESHOLD:
            win_points.append(
                f"전반적 만족도 높음 (우리 {our_pos_pct:.1f}% vs 경쟁사 평균 {comp_avg_pos_pct:.1f}%)"
            )

        # --- 평균 평점 차이 ---
        our_rating = our.result.avg_rating
        comp_ratings = [comp.result.avg_rating for comp in competitors]
        comp_avg_rating = sum(comp_ratings) / len(comp_ratings)

        if our_rating != 0.0 and comp_avg_rating != 0.0:
            if abs(our_rating - comp_avg_rating) >= _RATING_GAP_THRESHOLD:
                if our_rating > comp_avg_rating:
                    win_points.append(
                        f"평균 평점 우위 (우리 {our_rating:.2f} vs 경쟁사 평균 {comp_avg_rating:.2f})"
                    )
                else:
                    lose_points.append(
                        f"평균 평점 열위 (우리 {our_rating:.2f} vs 경쟁사 평균 {comp_avg_rating:.2f})"
                    )

        # --- 경쟁사 강점 미언급 ---
        competitor_pos_top5: set[str] = set()
        for comp in competitors:
            for kw, _ in comp.result.keywords_positive[:_COMP_POS_TOP_N]:
                competitor_pos_top5.add(kw)

        our_pos_top10: set[str] = {
            kw for kw, _ in our.result.keywords_positive[:_OUR_POS_COMPARE_N]
        }

        missing = competitor_pos_top5 - our_pos_top10
        for kw in missing:
            lose_points.append(f"경쟁사 강점 미언급: {kw}")

        # --- 우리만의 강점 ---
        our_pos_top5: set[str] = {
            kw for kw, _ in our.result.keywords_positive[:_OUR_POS_TOP_N]
        }

        competitor_pos_top10_union: set[str] = set()
        for comp in competitors:
            for kw, _ in comp.result.keywords_positive[:_COMP_POS_TOP_N_UNION]:
                competitor_pos_top10_union.add(kw)

        our_only = our_pos_top5 - competitor_pos_top10_union
        for kw in our_only:
            win_points.append(f"우리만의 강점: {kw}")

        # --- 우리만의 약점 ---
        our_neg_top3: set[str] = {
            kw for kw, _ in our.result.keywords_negative[:_OUR_NEG_TOP_N]
        }

        competitor_neg_top10_union: set[str] = set()
        for comp in competitors:
            for kw, _ in comp.result.keywords_negative[:_COMP_NEG_TOP_N_UNION]:
                competitor_neg_top10_union.add(kw)

        our_only_neg = our_neg_top3 - competitor_neg_top10_union
        for kw in our_only_neg:
            lose_points.append(f"우리만의 약점: {kw}")

        return win_points, lose_points

    def generate_action_items(
        self,
        lose_points: list[str],
        analyzed: list[ProductAnalyzed],
    ) -> list[str]:
        """lose_points 기반 액션 아이템 파생 (최대 5개)."""
        actions: list[str] = []

        for item in lose_points:
            if "배송" in item:
                actions.append("배송 정책·속도 재검토 권장")
            if "가격" in item or "저렴" in item:
                actions.append("가격 경쟁력 또는 가성비 카피 강화")
            if "품질" in item or "불량" in item:
                actions.append("QC 프로세스 점검 및 품질 관리 강화")
            m = _RE_COMP_STRENGTH.match(item)
            if m:
                kw = m.group(1)
                actions.append(f"제품 페이지에 '{kw}' 관련 문구 추가 A/B 테스트")
            m2 = _RE_OUR_WEAKNESS.match(item)
            if m2:
                kw2 = m2.group(1)
                actions.append(f"'{kw2}' 이슈 해결 우선순위 상향")

        deduped = list(dict.fromkeys(actions))
        return deduped[:_MAX_ACTION_ITEMS]

    def run(
        self,
        max_pages: int = 1,
        driver: DriverType = DriverType.SELENIUM,
        respect_robots: bool = True,
    ) -> ComparisonReport:
        """전체 파이프라인: crawl → analyze → summary → gaps → actions."""
        crawled = asyncio.run(self.crawl_all(max_pages, driver, respect_robots))
        analyzed = self.analyze_all(crawled)
        failed = [p.label for p in analyzed if p.result.total_reviews == 0]
        summary = self.build_summary(analyzed)
        win, lose = self.diagnose_gaps(analyzed)
        actions = self.generate_action_items(lose, analyzed)
        return ComparisonReport(
            products=analyzed,
            summary_rows=summary,
            win_points=win,
            lose_points=lose,
            action_items=actions,
            failed_products=failed,
        )
