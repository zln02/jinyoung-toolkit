"""
shared/korean_nlp.py — Kiwi 기반 한국어 NLP 처리 엔진.

이 모듈은 jinyoung-toolkit의 핵심 차별점 모듈로,
한국어 형태소 분석·불용어 제거·TF-IDF 키워드 추출·워드클라우드 생성을
일관된 인터페이스로 제공한다.

사용법:
    from shared.korean_nlp import KoreanTextProcessor

    proc = KoreanTextProcessor()
    tokens = proc.tokenize(texts_series)
    keywords = proc.extract_keywords_tfidf(texts_series, top_k=20)
"""

from __future__ import annotations

import platform
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
from kiwipiepy import Kiwi
from sklearn.feature_extraction.text import TfidfVectorizer

from shared.logger import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=None)
def _get_shared_kiwi(custom_dict_path: str | None) -> Kiwi:
    """Kiwi 인스턴스를 사용자 사전 경로별로 캐싱해 재사용한다.

    Kiwi() 초기화는 모델 로드 비용이 크므로(수 초·수백 MB), 동일 사전 설정에
    대해 단 한 번만 생성한다. 사용자 사전 로드는 인스턴스를 변형하므로
    경로를 캐시 키로 분리한다. 토크나이즈는 상태를 변경하지 않아 공유가 안전하다.
    """
    kiwi = Kiwi()
    if custom_dict_path is not None:
        dict_path = Path(custom_dict_path)
        if dict_path.is_file():
            try:
                kiwi.load_user_dictionary(str(dict_path))
                log.info("사용자_사전_로드", path=str(dict_path))
            except Exception as exc:
                log.warning("사용자_사전_로드_실패", path=str(dict_path), error=str(exc))
        else:
            log.warning("사용자_사전_파일_없음", path=str(dict_path))
    return kiwi


# ---------------------------------------------------------------------------
# 기본 한국어 불용어 셋
# ---------------------------------------------------------------------------
DEFAULT_STOPWORDS: frozenset[str] = frozenset(
    [
        "하다",
        "되다",
        "있다",
        "없다",
        "이다",
        "아니다",
        "것",
        "수",
        "등",
        "더",
        "좀",
        "잘",
        "안",
        "못",
        "저",
        "제",
        "나",
        "내",
        "너",
        "네",
        "그",
        "이",
        "때",
        "중",
        "적",
        "만",
        "또",
        "매우",
        "정말",
        "위",
        "아래",
        "앞",
        "뒤",
    ]
)

# 기본 POS 필터: 일반명사(NNG), 고유명사(NNP), 형용사(VA), 동사(VV)
_DEFAULT_POS_FILTER: list[str] = ["NNG", "NNP", "VA", "VV"]


class KoreanTextProcessor:
    """Kiwi 형태소 분석기를 래핑한 한국어 텍스트 처리 클래스.

    형태소 분석·불용어 제거·TF-IDF 키워드 추출·워드클라우드 생성을
    단일 인터페이스로 제공한다.

    Args:
        stopwords: 제거할 불용어 집합. None이면 DEFAULT_STOPWORDS 사용.
        custom_dict_path: Kiwi 사용자 사전 파일 경로(선택). 파일이 없으면 무시.
    """

    def __init__(
        self,
        stopwords: Optional[set[str]] = None,
        custom_dict_path: Optional[str | Path] = None,
    ) -> None:
        """KoreanTextProcessor를 초기화한다.

        Args:
            stopwords: 사용자 정의 불용어 집합. None이면 DEFAULT_STOPWORDS 사용.
            custom_dict_path: Kiwi 사용자 사전 파일 경로(선택).
        """
        self.stopwords: frozenset[str] = (
            frozenset(stopwords) if stopwords is not None else DEFAULT_STOPWORDS
        )

        # Kiwi 인스턴스는 모듈 레벨 캐시로 공유한다. Streamlit은 분석 버튼마다
        # KoreanTextProcessor를 새로 생성하는데, Kiwi() 로딩은 수 초·수백 MB라
        # 매번 재생성하면 지연/메모리 압박이 크다. 사용자 사전 경로별로 캐싱.
        self._kiwi: Kiwi = _get_shared_kiwi(
            str(custom_dict_path) if custom_dict_path is not None else None
        )

        log.info("KoreanTextProcessor_초기화_완료", stopwords_count=len(self.stopwords))

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _tokenize_single(
        self,
        text: str,
        pos_filter: list[str],
    ) -> str:
        """단일 문자열에 대해 형태소 분석 후 공백 구분 토큰 문자열로 반환.

        Args:
            text: 분석할 원본 텍스트.
            pos_filter: 유지할 품사 태그 리스트.

        Returns:
            불용어 제거 후 토큰을 공백으로 이은 문자열.
        """
        if not isinstance(text, str) or not text.strip():
            return ""

        try:
            result = self._kiwi.tokenize(text)
        except Exception as exc:
            log.warning("형태소_분석_실패", error=str(exc), text_preview=text[:50])
            return ""

        tokens: list[str] = []
        for token in result:
            # token: kiwipiepy.Token — .form, .tag 속성 보유
            form: str = token.form
            tag: str = str(token.tag)  # Tag enum → 문자열
            # 예: "POS.NNG" 형태인 경우 마지막 부분만 추출
            if "." in tag:
                tag = tag.split(".")[-1]

            if tag not in pos_filter:
                continue
            if form in self.stopwords:
                continue
            # 단일 문자·숫자 단독 토큰 제거
            if len(form) < 2:
                continue
            tokens.append(form)

        return " ".join(tokens)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tokenize(
        self,
        texts: pd.Series,
        pos_filter: Optional[list[str]] = None,
    ) -> pd.Series:
        """pd.Series 형태의 텍스트를 형태소 분석하여 토큰 문자열 Series로 반환.

        각 원소는 공백으로 구분된 형태소 토큰 문자열이다.
        불용어·1글자 토큰은 자동 제거된다.

        Args:
            texts: 분석할 원본 텍스트 Series.
            pos_filter: 유지할 품사 태그 리스트. None이면 기본값
                ["NNG", "NNP", "VA", "VV"] 사용.

        Returns:
            형태소 토큰을 공백으로 이은 문자열 Series (인덱스 유지).
        """
        if pos_filter is None:
            pos_filter = _DEFAULT_POS_FILTER

        log.info("형태소_분석_시작", size=len(texts), pos_filter=pos_filter)

        tokenized: pd.Series = texts.fillna("").apply(
            lambda t: self._tokenize_single(t, pos_filter)
        )

        log.info(
            "형태소_분석_완료",
            non_empty=int((tokenized != "").sum()),
        )
        return tokenized

    def remove_stopwords(self, tokens: pd.Series) -> pd.Series:
        """공백 구분 토큰 문자열 Series에서 불용어를 제거한다.

        tokenize() 결과물을 입력으로 받는다.
        이미 tokenize() 내부에서 불용어를 제거하므로,
        추가 후처리·외부 토크나이저 결과물 정제 시 사용한다.

        Args:
            tokens: 공백 구분 토큰 문자열 Series.

        Returns:
            불용어가 제거된 토큰 문자열 Series (인덱스 유지).
        """
        log.info("불용어_제거_시작", size=len(tokens))

        def _filter(token_str: str) -> str:
            if not isinstance(token_str, str):
                return ""
            words = token_str.split()
            return " ".join(w for w in words if w not in self.stopwords)

        result = tokens.fillna("").apply(_filter)
        log.info("불용어_제거_완료")
        return result

    def extract_keywords_tfidf(
        self,
        texts: pd.Series,
        top_k: int = 20,
    ) -> list[tuple[str, float]]:
        """TF-IDF 기반 키워드와 점수를 추출한다.

        texts를 먼저 tokenize()한 뒤 TfidfVectorizer를 적용하여
        코퍼스 전체 기준 상위 top_k 키워드와 평균 TF-IDF 점수를 반환한다.

        Args:
            texts: 원본 텍스트 Series.
            top_k: 반환할 상위 키워드 수.

        Returns:
            (키워드, 평균_TF-IDF_점수) 튜플 리스트 (점수 내림차순).

        Raises:
            ValueError: texts가 비어 있거나 유효한 토큰이 없을 때.
        """
        log.info("TF-IDF_키워드_추출_시작", top_k=top_k, size=len(texts))

        tokenized: pd.Series = self.tokenize(texts)
        valid: pd.Series = tokenized[tokenized.str.strip() != ""]

        if valid.empty:
            log.warning("TF-IDF_유효_토큰_없음")
            raise ValueError("유효한 토큰이 없습니다. 입력 텍스트를 확인하세요.")

        try:
            vectorizer = TfidfVectorizer(
                analyzer="word",
                token_pattern=r"[^\s]+",  # 공백 기준 분리 (이미 형태소 분리됨)
                max_features=5000,
            )
            tfidf_matrix = vectorizer.fit_transform(valid)
        except Exception as exc:
            log.error("TF-IDF_벡터화_실패", error=str(exc))
            raise

        # 각 단어의 코퍼스 평균 TF-IDF 점수 계산
        feature_names: list[str] = vectorizer.get_feature_names_out().tolist()
        # 희소 행렬의 열 평균 (0이 아닌 값 기준이 아닌 전체 평균)
        mean_scores = tfidf_matrix.mean(axis=0).A1  # (n_features,)

        top_indices = mean_scores.argsort()[::-1][:top_k]
        keywords: list[tuple[str, float]] = [
            (feature_names[i], float(mean_scores[i])) for i in top_indices
        ]

        log.info("TF-IDF_키워드_추출_완료", count=len(keywords))
        return keywords

    def extract_keywords_by_group(
        self,
        texts: pd.Series,
        labels: pd.Series,
        top_k: int = 10,
    ) -> dict[str, list[tuple[str, float]]]:
        """레이블(그룹)별 TF-IDF 키워드를 추출한다.

        같은 레이블을 가진 텍스트를 묶어 각 그룹별로
        extract_keywords_tfidf()를 수행하고 결과를 딕셔너리로 반환한다.

        Args:
            texts: 원본 텍스트 Series (labels와 인덱스 일치 필요).
            labels: 그룹 레이블 Series.
            top_k: 그룹별 반환할 상위 키워드 수.

        Returns:
            {레이블: [(키워드, 점수), ...]} 형태의 딕셔너리.
        """
        log.info(
            "그룹별_키워드_추출_시작",
            n_groups=labels.nunique(),
            top_k=top_k,
        )

        result: dict[str, list[tuple[str, float]]] = {}

        for label, group_idx in labels.groupby(labels).groups.items():
            group_texts = texts.loc[group_idx]
            label_str = str(label)
            try:
                result[label_str] = self.extract_keywords_tfidf(
                    group_texts, top_k=top_k
                )
                log.info("그룹_키워드_완료", label=label_str, count=len(result[label_str]))
            except ValueError as exc:
                log.warning("그룹_키워드_추출_건너뜀", label=label_str, reason=str(exc))
                result[label_str] = []
            except Exception as exc:
                log.error("그룹_키워드_추출_실패", label=label_str, error=str(exc))
                result[label_str] = []

        log.info("그룹별_키워드_추출_완료", groups=list(result.keys()))
        return result

    def to_tfidf_features(
        self,
        texts: pd.Series,
        max_features: int = 500,
    ) -> pd.DataFrame:
        """텍스트 Series를 TF-IDF 피처 DataFrame으로 변환한다.

        ML 모델 입력용 수치 피처 행렬을 생성한다.
        원본 Series 인덱스를 보존하며 컬럼명은 각 형태소 토큰이다.

        Args:
            texts: 원본 텍스트 Series.
            max_features: TF-IDF 최대 피처(단어) 수. 기본값 500.

        Returns:
            TF-IDF 값으로 채워진 DataFrame (shape: [n_texts, max_features]).

        Raises:
            ValueError: 유효한 토큰이 없어 피처 행렬을 만들 수 없을 때.
        """
        log.info("TF-IDF_피처_변환_시작", max_features=max_features, size=len(texts))

        tokenized: pd.Series = self.tokenize(texts)

        try:
            vectorizer = TfidfVectorizer(
                analyzer="word",
                token_pattern=r"[^\s]+",
                max_features=max_features,
            )
            matrix = vectorizer.fit_transform(tokenized.fillna(""))
        except Exception as exc:
            log.error("TF-IDF_피처_변환_실패", error=str(exc))
            raise ValueError(f"TF-IDF 피처 변환 실패: {exc}") from exc

        feature_names: list[str] = vectorizer.get_feature_names_out().tolist()
        df = pd.DataFrame(
            matrix.toarray(),
            index=texts.index,
            columns=feature_names,
            dtype="float32",
        )

        log.info(
            "TF-IDF_피처_변환_완료",
            shape=df.shape,
        )
        return df

    def generate_wordcloud(
        self,
        texts: pd.Series,
        output_path: str | Path,
        **kwargs,
    ) -> Path:
        """한국어 텍스트로부터 워드클라우드 이미지를 생성한다.

        한글 폰트를 자동 감지하여 적용하며, 결과 이미지를 output_path에 저장한다.

        Args:
            texts: 원본 텍스트 Series.
            output_path: 저장할 이미지 파일 경로 (PNG 권장).
            **kwargs: wordcloud.WordCloud 생성자에 전달할 추가 인자.
                예) width=800, height=600, background_color="white".

        Returns:
            저장된 이미지의 절대 Path.

        Raises:
            RuntimeError: 시스템에 한글 폰트가 없을 때.
            ImportError: wordcloud 라이브러리가 설치되지 않았을 때.
        """
        try:
            from wordcloud import WordCloud
        except ImportError as exc:
            log.error("wordcloud_라이브러리_없음", error=str(exc))
            raise ImportError(
                "wordcloud 라이브러리가 필요합니다: pip install wordcloud"
            ) from exc

        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        font_path: Path = self.find_korean_font()
        log.info("한글_폰트_감지", font=str(font_path))

        tokenized: pd.Series = self.tokenize(texts)
        combined_text: str = " ".join(tokenized.dropna().tolist())

        if not combined_text.strip():
            log.warning("워드클라우드_입력_텍스트_없음")
            raise ValueError("워드클라우드 생성 가능한 텍스트가 없습니다.")

        # 기본 설정 + 사용자 오버라이드
        wc_kwargs: dict = {
            "font_path": str(font_path),
            "width": 800,
            "height": 600,
            "background_color": "white",
            "max_words": 200,
            "collocations": False,
        }
        wc_kwargs.update(kwargs)

        try:
            wc = WordCloud(**wc_kwargs)
            wc.generate(combined_text)
            wc.to_file(str(output_path))
        except Exception as exc:
            log.error("워드클라우드_생성_실패", error=str(exc))
            raise

        log.info("워드클라우드_저장_완료", path=str(output_path))
        return output_path

    @staticmethod
    def find_korean_font() -> Path:
        """시스템에서 한글 지원 폰트를 탐색하여 경로를 반환한다.

        탐색 순서:
        1. OS별 시스템 폰트 디렉토리 내 .ttf/.otf 파일 중 한글 관련 파일명.
        2. 프로젝트 번들 폰트 디렉토리: ``shared/fonts/``.
        3. 모두 실패하면 RuntimeError 발생.

        Returns:
            발견된 한글 폰트 파일의 절대 Path.

        Raises:
            RuntimeError: 한글 폰트를 찾을 수 없을 때.
        """
        # 1단계: OS별 시스템 폰트 경로 + 한글 관련 키워드
        system = platform.system()

        system_font_dirs: list[Path] = []
        if system == "Linux":
            system_font_dirs = [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                Path.home() / ".fonts",
                Path.home() / ".local/share/fonts",
            ]
        elif system == "Darwin":
            system_font_dirs = [
                Path("/Library/Fonts"),
                Path("/System/Library/Fonts"),
                Path.home() / "Library/Fonts",
            ]
        elif system == "Windows":
            system_font_dirs = [
                Path("C:/Windows/Fonts"),
            ]

        # 한글 폰트 파일명 키워드 (우선순위 순)
        korean_keywords: list[str] = [
            "NanumGothic",
            "NanumBarunGothic",
            "NanumMyeongjo",
            "Nanum",
            "malgun",
            "Malgun",
            "AppleGothic",
            "Batang",
            "Gulim",
            "Dotum",
            "gothic",
            "Gothic",
            "korean",
            "Korean",
            "kr",
        ]

        for font_dir in system_font_dirs:
            if not font_dir.is_dir():
                continue
            # 재귀 탐색
            for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
                for font_file in sorted(font_dir.rglob(ext)):
                    name = font_file.name
                    for kw in korean_keywords:
                        if kw in name:
                            log.debug(
                                "시스템_한글_폰트_발견",
                                font=str(font_file),
                            )
                            return font_file.resolve()

        # 2단계: 프로젝트 번들 shared/fonts/ 탐색
        bundle_dir = Path(__file__).parent / "fonts"
        if bundle_dir.is_dir():
            for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
                for font_file in sorted(bundle_dir.rglob(ext)):
                    log.debug(
                        "번들_한글_폰트_발견",
                        font=str(font_file),
                    )
                    return font_file.resolve()

        # 3단계: 실패
        raise RuntimeError(
            "한글 폰트를 찾을 수 없습니다. "
            "NanumGothic 등을 설치하거나 shared/fonts/ 에 폰트 파일을 추가하세요. "
            f"(탐색된 디렉토리: {system_font_dirs}, {bundle_dir})"
        )
