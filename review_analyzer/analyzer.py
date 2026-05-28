"""리뷰 분석기 — 전처리→감성분석→키워드추출→시각화→PDF 리포트."""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")

from shared.config import get_settings
from shared.delivery import DeliveryPackage
from shared.exporters import export_csv
from shared.korean_nlp import KoreanTextProcessor
from shared.logger import get_logger
from shared.report_generator import ReportGenerator

logger = get_logger(__name__)

POSITIVE_KEYWORDS: set[str] = {
    "좋다",
    "훌륭하다",
    "만족",
    "추천",
    "최고",
    "예쁘다",
    "빠르다",
    "편하다",
    "깔끔",
    "가성비",
    "친절",
    "빠른배송",
    "고품질",
    "완벽",
    "마음에들다",
    "재구매",
    "감동",
    "실용적",
    "튼튼",
    "저렴",
}

NEGATIVE_KEYWORDS: set[str] = {
    "별로",
    "실망",
    "후회",
    "불량",
    "느리다",
    "불편",
    "비싸다",
    "교환",
    "환불",
    "불만",
    "최악",
    "형편없다",
    "불친절",
    "파손",
    "오배송",
    "불량품",
    "낮은품질",
    "느린배송",
    "사기",
    "고장",
}

# 부정어 — 긍정 키워드 바로 앞에 오면 의미를 반전("안 좋다", "별로 안 깔끔")
NEGATION_WORDS: tuple[str, ...] = ("안", "못", "별로", "전혀", "않", "없")


@dataclass
class SentimentConfig:
    """감성 분석 사용자 설정.

    UI(고급 설정) → ReviewAnalyzer → 리포트/패키지 빌드까지 동일하게 전달된다.

    Attributes:
        mode: "auto"(평점 우선·실패 시 키워드) | "rating"(평점만) | "keyword"(키워드만).
        rating_scale: 평점 만점(5/10/100). None이면 값 크기로 자동 추정.
        positive_threshold: 5점 환산 후 이 값 이상이면 positive.
        negative_threshold: 5점 환산 후 이 값 이하면 negative.
        extra_positive/extra_negative: 사용자 추가 긍/부정 키워드(균형안 미사용, 예약).
    """

    mode: str = "auto"
    rating_scale: float | None = None
    positive_threshold: float = 4.0
    negative_threshold: float = 2.0
    extra_positive: tuple[str, ...] = ()
    extra_negative: tuple[str, ...] = ()


@dataclass
class AnalysisResult:
    """분석 결과 컨테이너."""

    sentiment_distribution: dict[str, int]
    keywords_positive: list[tuple[str, float]]
    keywords_negative: list[tuple[str, float]]
    rating_distribution: dict[int, int]
    total_reviews: int
    avg_rating: float
    wordcloud_path: Path | None
    insights: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls, reason: str = "데이터 부족") -> "AnalysisResult":
        """크롤링 0건/분석 실패 등 빈 상태의 표준 fallback 인스턴스."""
        return cls(
            sentiment_distribution={"positive": 0, "negative": 0, "neutral": 0},
            keywords_positive=[],
            keywords_negative=[],
            rating_distribution={},
            total_reviews=0,
            avg_rating=0.0,
            wordcloud_path=None,
            insights=[reason],
        )


class ReviewAnalyzer:
    """리뷰 분석기 — 전처리→감성분석→키워드추출→시각화→PDF 리포트."""

    def __init__(
        self,
        text_column: str = "content",
        rating_column: str | None = "rating",
        rating_parse_pattern: str | None = None,
        cache_root: Path | None = None,
        sentiment_config: SentimentConfig | None = None,
    ) -> None:
        """초기화. KoreanTextProcessor 인스턴스 생성.

        Args:
            text_column: 리뷰 본문 컬럼명.
            rating_column: 평점 컬럼명. 없으면 None.
            rating_parse_pattern: 평점 파싱용 regex.
            cache_root: 워드클라우드 PNG를 보존할 루트 디렉토리.
                None이면 ``get_settings().output_dir / "wordcloud_cache"`` 사용.
                Streamlit rerun/다운로드 후에도 PNG가 살아있도록 영구 디렉토리에 저장한다.
            sentiment_config: 감성 분석 사용자 설정(분석 방식·평점 척도·긍부정 경계).
                None이면 기본값(auto 모드)을 사용한다.
        """
        self.text_column = text_column
        self.rating_column = rating_column
        self.rating_parse_pattern = rating_parse_pattern
        self._rating_regex = re.compile(rating_parse_pattern) if rating_parse_pattern else None
        self.config = sentiment_config or SentimentConfig()
        self._positive_keywords = POSITIVE_KEYWORDS | set(self.config.extra_positive)
        self._negative_keywords = NEGATIVE_KEYWORDS | set(self.config.extra_negative)
        self.nlp = KoreanTextProcessor()
        self.cache_root: Path = (
            cache_root
            if cache_root is not None
            else get_settings().output_dir / "wordcloud_cache"
        )

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """전처리: 중복제거, 결측처리, 텍스트 정규화.

        - df[text_column] 결측 → 제거
        - 중복 행 제거
        - 텍스트 앞뒤 공백 strip
        """
        logger.info("전처리 시작 (행 수: %d)", len(df))
        df = df.copy()

        before = len(df)
        df = df.dropna(subset=[self.text_column])
        logger.info("결측 제거: %d → %d", before, len(df))

        before = len(df)
        df = df.drop_duplicates()
        logger.info("중복 제거: %d → %d", before, len(df))

        df[self.text_column] = df[self.text_column].str.strip()

        df = df[df[self.text_column].str.len() > 0].reset_index(drop=True)
        logger.info("전처리 완료 (행 수: %d)", len(df))
        return df

    def analyze_sentiment(self, df: pd.DataFrame) -> pd.DataFrame:
        """감성 분석 (SentimentConfig 기반).

        - mode="auto" (기본): 행마다 평점 파싱을 시도해 성공하면 평점 기반,
          실패하면 키워드 기반으로 fallback. 평점이 "만족도:100%"처럼 비표준이라
          파싱 못 해도 전부 neutral로 떨어지지 않는다(과거 버그 수정).
        - mode="rating": 평점 기반만 (파싱 실패 행은 neutral).
        - mode="keyword": 키워드 기반만.
        - rating_column이 없으면 mode와 무관하게 키워드 기반.

        평점 분류 경계와 척도는 self.config(positive/negative_threshold, rating_scale)를 따른다.
        결과: 'sentiment' 컬럼 추가 ("positive"/"negative"/"neutral")
        """
        df = df.copy()
        mode = self.config.mode
        has_rating = bool(self.rating_column and self.rating_column in df.columns)

        if not has_rating or mode == "keyword":
            logger.info("감성 분석: 키워드 기반 (mode=%s, 평점컬럼=%s)", mode, has_rating)
            df["sentiment"] = df[self.text_column].apply(self._sentiment_by_keywords)
        elif mode == "rating":
            logger.info("감성 분석: 평점 기반 (mode=rating)")
            df["sentiment"] = df[self.rating_column].apply(self._sentiment_by_rating)
        else:  # auto — 평점 우선, 파싱 실패 행은 키워드 fallback
            logger.info("감성 분석: 자동 하이브리드 (평점 우선, 실패 시 키워드 fallback)")
            df["sentiment"] = df.apply(self._sentiment_row, axis=1)

        counts = df["sentiment"].value_counts().to_dict()
        logger.info("감성 분포: %s", counts)
        return df

    def _sentiment_row(self, row: "pd.Series") -> str:
        """auto 모드 행 단위 분류: 평점 파싱 성공 시 평점 기반, 실패 시 키워드 fallback."""
        r = self._parse_rating_value(row.get(self.rating_column))
        if r is None:
            return self._sentiment_by_keywords(row.get(self.text_column))
        return self._classify_rating(r)

    def _parse_rating_value(self, raw: Any) -> float | None:
        """원시 평점 값(숫자 or 문자열)을 float으로 변환.

        - 숫자면 그대로 float 반환
        - 문자열이면 rating_parse_pattern regex로 첫 매칭 그룹 추출
        - 100점 척도("만족도 : 100%", "96%" 등)는 자동으로 5점 척도로 변환
          (값이 6 이상이면 100점 척도로 간주하여 /20)
        - 실패 시 None
        """
        if raw is None:
            return None
        # 이미 숫자
        if isinstance(raw, (int, float)):
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return None
            if pd.isna(val):
                return None
        else:
            text = str(raw).strip()
            if not text or text.lower() == "nan":
                return None
            if self._rating_regex is not None:
                m = self._rating_regex.search(text)
                if not m:
                    return None
                try:
                    # 첫 그룹 사용. 그룹 없으면 전체 매치.
                    val = float(m.group(1) if m.groups() else m.group(0))
                except (TypeError, ValueError, IndexError):
                    return None
            else:
                # 패턴 없으면 기존처럼 직접 float 시도
                try:
                    val = float(text)
                except (TypeError, ValueError):
                    return None
        # 척도 → 5점 척도 환산
        scale = self.config.rating_scale
        if scale == 10:
            val = val / 2.0
        elif scale == 100:
            val = val / 20.0
        elif scale == 5:
            pass  # 이미 5점 척도
        else:
            # 자동 추정: 5.5 초과면 100점 척도로 간주("만족도 : 100%", "96%" 등)
            if val > 5.5:
                val = val / 20.0
        # 0~5 클램핑
        if val < 0:
            return None
        if val > 5.0:
            val = 5.0
        return val

    def _classify_rating(self, r: float) -> str:
        """5점 환산 평점을 설정 경계(positive/negative_threshold)로 분류."""
        if r >= self.config.positive_threshold:
            return "positive"
        if r <= self.config.negative_threshold:
            return "negative"
        return "neutral"

    def _sentiment_by_rating(self, rating: Any) -> str:
        """평점으로 감성 분류 (5점 환산 + 설정 경계). 파싱 실패 시 neutral."""
        r = self._parse_rating_value(rating)
        if r is None:
            return "neutral"
        return self._classify_rating(r)

    def _sentiment_by_keywords(self, text: Any) -> str:
        """키워드 카운트로 감성 분류 (부정어 반전 포함).

        긍정 키워드가 매칭돼도 바로 앞(최대 6글자)에 부정어(안/못/별로/전혀/않/없)가
        있으면 부정으로 센다 — "안 좋다", "별로 안 깔끔" 같은 표현의 오분류를 막는다.
        """
        if not isinstance(text, str):
            return "neutral"
        pos_count = 0
        neg_count = 0
        for kw in self._positive_keywords:
            idx = text.find(kw)
            if idx == -1:
                continue
            window = text[max(0, idx - 6):idx]
            if any(neg in window for neg in NEGATION_WORDS):
                neg_count += 1
            else:
                pos_count += 1
        neg_count += sum(1 for kw in self._negative_keywords if kw in text)
        if pos_count > neg_count:
            return "positive"
        if neg_count > pos_count:
            return "negative"
        return "neutral"

    def extract_keywords(
        self, df: pd.DataFrame, top_k: int = 20
    ) -> dict[str, list[tuple[str, float]]]:
        """감성별 키워드 추출.

        KoreanTextProcessor.extract_keywords_by_group 사용.
        Returns: {"positive": [(kw, score), ...], "negative": [...], "neutral": [...]}
        """
        logger.info("키워드 추출 시작 (top_k=%d)", top_k)
        try:
            result = self.nlp.extract_keywords_by_group(
                df[self.text_column],
                df["sentiment"],
                top_k=top_k,
            )
        except Exception:
            logger.exception("키워드 추출 실패")
            result = {"positive": [], "negative": [], "neutral": []}
        logger.info("키워드 추출 완료")
        return result

    def generate_wordcloud(
        self, df: pd.DataFrame, output_dir: Path
    ) -> dict[str, Path]:
        """워드클라우드 생성 — 전체/긍정/부정 3개.

        KoreanTextProcessor.generate_wordcloud 사용.
        Returns: {"all": Path, "positive": Path, "negative": Path}
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        groups = {
            "all": df[self.text_column],
            "positive": df.loc[df["sentiment"] == "positive", self.text_column],
            "negative": df.loc[df["sentiment"] == "negative", self.text_column],
        }

        for name, texts in groups.items():
            if texts.empty:
                logger.warning("워드클라우드 스킵 (데이터 없음): %s", name)
                continue
            out_path = output_dir / f"wordcloud_{name}.png"
            try:
                saved = self.nlp.generate_wordcloud(texts, out_path)
                paths[name] = saved
                logger.info("워드클라우드 저장: %s", saved)
            except Exception:
                logger.exception("워드클라우드 생성 실패: %s", name)

        return paths

    def generate_insights(self, result: AnalysisResult) -> list[str]:
        """규칙 기반 인사이트 3줄 생성.

        1. 긍정 비율 + 전반적 만족도 평가
        2. 가장 많이 언급된 긍정 키워드
        3. 부정 리뷰에서 두드러지는 불만
        """
        insights: list[str] = []
        total = result.total_reviews or 1

        pos_count = result.sentiment_distribution.get("positive", 0)
        neg_count = result.sentiment_distribution.get("negative", 0)
        pos_ratio = pos_count / total * 100

        if pos_ratio >= 70:
            satisfaction = "전반적으로 높은 만족도를 보입니다."
        elif pos_ratio >= 40:
            satisfaction = "보통 수준의 만족도를 보입니다."
        else:
            satisfaction = "전반적으로 낮은 만족도를 보입니다."

        insights.append(
            f"긍정 리뷰 비율은 {pos_ratio:.1f}%({pos_count}건)이며, {satisfaction}"
        )

        if result.keywords_positive:
            top_pos = [kw for kw, _ in result.keywords_positive[:3]]
            insights.append(
                f"긍정 리뷰에서 가장 많이 언급된 키워드: {', '.join(top_pos)}"
            )
        else:
            insights.append("긍정 리뷰 키워드 데이터가 부족합니다.")

        if result.keywords_negative:
            top_neg = [kw for kw, _ in result.keywords_negative[:3]]
            insights.append(
                f"부정 리뷰({neg_count}건)에서 두드러진 불만 키워드: {', '.join(top_neg)}"
            )
        else:
            insights.append("부정 리뷰 키워드 데이터가 부족합니다.")

        return insights

    def run(self, df: pd.DataFrame) -> AnalysisResult:
        """전체 분석 파이프라인.

        preprocess → analyze_sentiment → extract_keywords → generate_wordcloud → generate_insights
        워드클라우드 PNG는 ``self.cache_root`` 하위 인스턴스 전용 디렉토리에 영속 저장한다.
        Streamlit rerun이나 PDF 빌드 단계에서도 동일한 경로가 유효해야 하기 때문이다.
        """
        logger.info("분석 파이프라인 시작")

        # best-effort: 24h 이상 지난 캐시 인스턴스 디렉토리 청소
        self._sweep_stale_cache(max_age_seconds=24 * 3600)

        df = self.preprocess(df)
        df = self.analyze_sentiment(df)

        keywords = self.extract_keywords(df, top_k=20)

        sentiment_dist: dict[str, int] = (
            df["sentiment"].value_counts().to_dict()
        )
        for key in ("positive", "negative", "neutral"):
            sentiment_dist.setdefault(key, 0)

        rating_dist: dict[int, int] = {}
        avg_rating = 0.0
        if self.rating_column and self.rating_column in df.columns:
            rating_series = df[self.rating_column].apply(self._parse_rating_value)
            valid = rating_series.dropna()
            rating_dist = (
                valid.round().astype(int).value_counts().sort_index().to_dict()
                if not valid.empty else {}
            )
            avg_rating = float(valid.mean()) if not valid.empty else 0.0

        instance_dir = self._make_instance_dir()
        wc_paths = self.generate_wordcloud(df, instance_dir)
        wc_all = wc_paths.get("all")

        result = AnalysisResult(
            sentiment_distribution=sentiment_dist,
            keywords_positive=keywords.get("positive", []),
            keywords_negative=keywords.get("negative", []),
            rating_distribution=rating_dist,
            total_reviews=len(df),
            avg_rating=avg_rating,
            wordcloud_path=wc_all,
            insights=[],
        )
        result.insights = self.generate_insights(result)

        logger.info("분석 파이프라인 완료")
        return result

    def _make_instance_dir(self) -> Path:
        """워드클라우드 저장용 인스턴스 디렉토리 생성.

        cache_root 하위에 uuid12 서브디렉토리를 만든다.
        cache_root mkdir 권한 실패 시 tempfile.mkdtemp()로 1회 폴백한다.
        """
        try:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            instance_dir = self.cache_root / uuid.uuid4().hex[:12]
            instance_dir.mkdir(parents=True, exist_ok=True)
            return instance_dir
        except OSError as exc:
            logger.warning(
                "워드클라우드 캐시 디렉토리 생성 실패 — 임시 디렉토리로 폴백: %s",
                exc,
            )
            return Path(tempfile.mkdtemp(prefix="wordcloud_"))

    def _sweep_stale_cache(self, max_age_seconds: int) -> None:
        """cache_root 하위 디렉토리 중 mtime이 max_age_seconds 이상 지난 것 삭제.

        실패는 무시 (best-effort).
        """
        try:
            if not self.cache_root.exists():
                return
            now = time.time()
            for child in self.cache_root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    if now - child.stat().st_mtime > max_age_seconds:
                        shutil.rmtree(child, ignore_errors=True)
                except OSError:
                    continue
        except OSError:
            pass

    def generate_report(self, result: AnalysisResult, output_path: Path) -> Path:
        """PDF 리포트 생성. ReportGenerator 사용.

        구성: 데이터개요, 감성분포, 평점분포, 키워드Top10, 워드클라우드, 인사이트
        matplotlib로 파이차트/바차트 생성 후 add_chart로 삽입.
        """
        logger.info("PDF 리포트 생성 시작")

        try:
            font_path = KoreanTextProcessor.find_korean_font()
            import matplotlib.font_manager as fm

            fm.fontManager.addfont(str(font_path))
            font_name = fm.FontProperties(fname=str(font_path)).get_name()
            plt.rcParams["font.family"] = font_name
        except Exception:
            logger.warning("한글 폰트 설정 실패 — 기본 폰트 사용")

        rg = ReportGenerator(title="리뷰 분석 리포트")

        rg.add_section(
            "데이터 개요",
            (
                f"총 리뷰 수: {result.total_reviews}건\n"
                f"평균 평점: {result.avg_rating:.2f}"
                if result.avg_rating
                else f"총 리뷰 수: {result.total_reviews}건"
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 파이차트 — 감성 분포
            pie_path = tmp_path / "sentiment_pie.png"
            try:
                labels = list(result.sentiment_distribution.keys())
                sizes = list(result.sentiment_distribution.values())
                colors = {"positive": "#4CAF50", "negative": "#F44336", "neutral": "#9E9E9E"}
                clrs = [colors.get(lbl, "#2196F3") for lbl in labels]

                fig, ax = plt.subplots(figsize=(5, 4))
                ax.pie(sizes, labels=labels, colors=clrs, autopct="%1.1f%%", startangle=90)
                ax.set_title("감성 분포")
                fig.tight_layout()
                fig.savefig(pie_path, dpi=120)
                plt.close(fig)
                rg.add_chart(pie_path, caption="감성 분포 (긍정/부정/중립)")
            except Exception:
                logger.exception("파이차트 생성 실패")

            # 바차트 — 평점 분포
            if result.rating_distribution:
                bar_path = tmp_path / "rating_bar.png"
                try:
                    ratings = sorted(result.rating_distribution.keys())
                    counts = [result.rating_distribution[r] for r in ratings]

                    fig, ax = plt.subplots(figsize=(5, 4))
                    ax.bar([str(r) for r in ratings], counts, color="#2196F3")
                    ax.set_xlabel("평점")
                    ax.set_ylabel("리뷰 수")
                    ax.set_title("평점 분포")
                    fig.tight_layout()
                    fig.savefig(bar_path, dpi=120)
                    plt.close(fig)
                    rg.add_chart(bar_path, caption="평점 분포")
                except Exception:
                    logger.exception("바차트 생성 실패")

            # 감성 분포 테이블
            rg.add_table(
                headers=["감성", "건수", "비율(%)"],
                rows=[
                    [
                        k,
                        str(v),
                        f"{v / (result.total_reviews or 1) * 100:.1f}",
                    ]
                    for k, v in result.sentiment_distribution.items()
                ],
            )

            # 키워드 Top 10
            pos_top10 = result.keywords_positive[:10]
            neg_top10 = result.keywords_negative[:10]

            if pos_top10:
                rg.add_section("긍정 키워드 Top 10", "")
                rg.add_table(
                    headers=["키워드", "점수"],
                    rows=[[kw, f"{score:.4f}"] for kw, score in pos_top10],
                )

            if neg_top10:
                rg.add_section("부정 키워드 Top 10", "")
                rg.add_table(
                    headers=["키워드", "점수"],
                    rows=[[kw, f"{score:.4f}"] for kw, score in neg_top10],
                )

            # 워드클라우드
            if result.wordcloud_path and result.wordcloud_path.exists():
                rg.add_chart(result.wordcloud_path, caption="전체 리뷰 워드클라우드")

            # 인사이트
            for insight in result.insights:
                rg.add_insight(insight)

            saved = rg.save(output_path)

        logger.info("PDF 리포트 저장: %s", saved)
        return saved

    def save_delivery_package(
        self,
        raw_df: pd.DataFrame,
        result: AnalysisResult,
        output_dir: Path,
        project_name: str = "review_analysis",
    ) -> Path:
        """납품 패키지 생성. DeliveryPackage 사용."""
        logger.info("납품 패키지 생성 시작")

        pkg = DeliveryPackage(output_dir=output_dir, project_name=project_name)

        pkg.add_raw(raw_df)

        try:
            clean_df = self.preprocess(raw_df)
            pkg.add_clean(clean_df)
        except Exception:
            logger.exception("전처리 데이터 패키징 실패")

        analysis_files: dict[str, Any] = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            wc_paths = {}
            try:
                analyzed_df = self.analyze_sentiment(self.preprocess(raw_df))
                wc_paths = self.generate_wordcloud(analyzed_df, tmp_path)
            except Exception:
                logger.exception("워드클라우드 패키징 실패")

            analysis_files.update(wc_paths)

            report_path = tmp_path / "report.pdf"
            try:
                report_path = self.generate_report(result, report_path)
                pkg.add_report(report_path)
            except Exception:
                logger.exception("PDF 리포트 패키징 실패")

            pkg.add_analysis(analysis_files)

        pkg.generate_readme(
            context={
                "project_name": project_name,
                "total_reviews": result.total_reviews,
                "avg_rating": result.avg_rating,
                "sentiment_distribution": result.sentiment_distribution,
                "insights": result.insights,
            }
        )

        built_path = pkg.build()
        logger.info("납품 패키지 완료: %s", built_path)
        return built_path
