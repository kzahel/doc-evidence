"""Deterministic Unicode word, number, whitespace, and punctuation diff."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from doc_evidence.contracts.api import (
    ComparisonResult,
    DiffSegment,
    DiffToken,
    NumericDiscrepancy,
)

ALGORITHM_VERSION = "word_numeric_diff_v1"
MAX_COMPARISON_CHARACTERS = 1_000_000

_NUMBER = re.compile(
    r"[+-]?(?:"
    r"\d{1,3}(?:[.'’\u202f]\d{3})+(?:,\d+)?|"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"\d+(?:[.,]\d+)?"
    r")%?"
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class _ComparableToken:
    public: DiffToken
    comparison_key: tuple[str, str]


def _normalize_number(value: str) -> str:
    token = re.sub(r"[\u202f'’]", "", value).rstrip("%")
    suffix = "%" if value.endswith("%") else ""
    if "," in token and "." in token:
        if token.rfind(".") > token.rfind(","):
            token = token.replace(",", "")
        else:
            token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        tail = token.rsplit(",", 1)[1]
        token = token.replace(",", "" if len(tail) == 3 else ".")
    return token + suffix


def _tokens(value: str) -> list[_ComparableToken]:
    normalized = unicodedata.normalize("NFKC", value)
    output: list[_ComparableToken] = []
    position = 0
    while position < len(normalized):
        whitespace = _WHITESPACE.match(normalized, position)
        if whitespace:
            text = whitespace.group(0)
            output.append(
                _ComparableToken(
                    public=DiffToken(text=text, kind="whitespace"),
                    comparison_key=("whitespace", " "),
                )
            )
            position = whitespace.end()
            continue
        number = _NUMBER.match(normalized, position)
        if number:
            text = number.group(0)
            output.append(
                _ComparableToken(
                    public=DiffToken(text=text, kind="numeric"),
                    comparison_key=("numeric", _normalize_number(text)),
                )
            )
            position = number.end()
            continue
        word = _WORD.match(normalized, position)
        if word:
            text = word.group(0)
            output.append(
                _ComparableToken(
                    public=DiffToken(text=text, kind="word"),
                    comparison_key=("word", text.casefold()),
                )
            )
            position = word.end()
            continue
        text = normalized[position]
        output.append(
            _ComparableToken(
                public=DiffToken(text=text, kind="punctuation"),
                comparison_key=("punctuation", text),
            )
        )
        position += 1
    return output


def word_numeric_diff(
    *,
    document_id: str,
    page: int,
    left_run_ref: str,
    right_run_ref: str,
    left_text: str,
    right_text: str,
) -> ComparisonResult:
    """Align two normalized page strings with a fixed SequenceMatcher policy."""

    if len(left_text) > MAX_COMPARISON_CHARACTERS:
        raise ValueError("left comparison input exceeds 1,000,000 characters")
    if len(right_text) > MAX_COMPARISON_CHARACTERS:
        raise ValueError("right comparison input exceeds 1,000,000 characters")

    left = _tokens(left_text)
    right = _tokens(right_text)
    matcher = SequenceMatcher(
        None,
        [token.comparison_key for token in left],
        [token.comparison_key for token in right],
        autojunk=False,
    )
    segments: list[DiffSegment] = []
    discrepancies: list[NumericDiscrepancy] = []
    for index, (operation, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
        left_tokens = [token.public for token in left[i1:i2]]
        right_tokens = [token.public for token in right[j1:j2]]
        contains_numeric = any(
            token.kind == "numeric" for token in left_tokens + right_tokens
        )
        segment = DiffSegment(
            index=index,
            operation=operation,
            left=left_tokens,
            right=right_tokens,
            contains_numeric=contains_numeric,
        )
        segments.append(segment)
        if operation != "equal" and contains_numeric:
            discrepancies.append(
                NumericDiscrepancy(
                    segment_index=index,
                    left_values=[
                        token.text for token in left_tokens if token.kind == "numeric"
                    ],
                    right_values=[
                        token.text for token in right_tokens if token.kind == "numeric"
                    ],
                )
            )
    return ComparisonResult(
        document_id=document_id,
        page=page,
        left_run_ref=left_run_ref,
        right_run_ref=right_run_ref,
        options={
            "unicode_normalization": "NFKC",
            "word_comparison": "casefolded",
            "whitespace_comparison": "boundary",
            "sequence_matcher_autojunk": False,
            "maximum_characters_per_input": MAX_COMPARISON_CHARACTERS,
        },
        equivalent=left_text == right_text,
        segments=segments,
        numeric_discrepancies=discrepancies,
    )
