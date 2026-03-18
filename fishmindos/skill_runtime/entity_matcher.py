from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable


MIN_MATCH_SCORE = 0.62


@dataclass(frozen=True, slots=True)
class EntityMatch:
    item: dict[str, Any]
    reference: str
    score: float


def normalize_entity_text(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\s_\-]+", "", text)
    text = re.sub(r"[，。、“”‘’'\"`~!@#$%^&*()（）【】\[\]{}<>《》;；:：,.?？/\\|]+", "", text)
    return text


def unique_references(values: Iterable[Any]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        normalized = normalize_entity_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(text)
    return items


def best_entity_match(
    items: Iterable[Any],
    references: Iterable[Any],
    *,
    label_keys: tuple[str, ...] = ("name",),
    id_keys: tuple[str, ...] = ("id",),
    threshold: float = MIN_MATCH_SCORE,
) -> EntityMatch | None:
    candidate_items = [item for item in items if isinstance(item, dict)]
    candidate_refs = unique_references(references)
    if not candidate_items or not candidate_refs:
        return None

    best: EntityMatch | None = None
    for item in candidate_items:
        for reference in candidate_refs:
            score = _score_item(reference, item, label_keys=label_keys, id_keys=id_keys)
            if score < threshold:
                continue
            if best is None or score > best.score:
                best = EntityMatch(item=item, reference=reference, score=score)
    return best


def _score_item(
    reference: str,
    item: dict[str, Any],
    *,
    label_keys: tuple[str, ...],
    id_keys: tuple[str, ...],
) -> float:
    normalized_ref = normalize_entity_text(reference)
    if not normalized_ref:
        return 0.0

    best = 0.0
    for key in label_keys + id_keys:
        raw_value = item.get(key)
        normalized_value = normalize_entity_text(raw_value)
        if not normalized_value:
            continue
        exact_bonus = 0.99 if key in label_keys else 1.0
        if normalized_ref == normalized_value:
            best = max(best, exact_bonus)
            continue
        if normalized_ref in normalized_value:
            overlap = min(len(normalized_ref), len(normalized_value)) / max(len(normalized_ref), len(normalized_value))
            base = 0.9 if key in label_keys else 0.94
            best = max(best, base + overlap * 0.05)
            continue
        if normalized_value in normalized_ref:
            overlap = min(len(normalized_ref), len(normalized_value)) / max(len(normalized_ref), len(normalized_value))
            base = 0.82 if key in label_keys else 0.86
            best = max(best, base + overlap * 0.05)
            continue
        ratio = SequenceMatcher(a=normalized_ref, b=normalized_value).ratio()
        if ratio >= 0.85:
            best = max(best, 0.72 + ratio * 0.2)
        elif ratio >= 0.72:
            best = max(best, 0.58 + ratio * 0.15)
    return best
