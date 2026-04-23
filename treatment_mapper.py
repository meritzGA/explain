"""
담보 리스트를 '치료 방식별 서브카드'로 분해하는 매퍼.

동작 방식:
  1. 상품명에서 product_matcher 결정 → 어떤 치료 카드 프리셋을 쓸지 선택
  2. 각 치료 카드의 contributions를 순회하며 매칭되는 담보를 찾아 금액 합산
  3. 실제로 담보가 존재하는 치료 카드만 반환 (담보 없으면 카드 생략)
  4. 5년 헤드라인 금액 계산 (전체 min/max 합계 × 5)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from extractor import Coverage


@dataclass
class TreatmentItem:
    """치료 카드 내의 한 줄 (예: '(연1회) 표적항암약물치료비 1,000만(3,000만)')"""
    coverage_name: str  # 소속 담보명 (예: '암 통합치료비(기본형)...')
    label: str  # 치료 항목 설명 (예: '(연1회) 표적항암약물치료비')
    min_amount: int  # 만원 단위
    max_amount: int  # 만원 단위
    display: str  # '1,000만', '1,000만(3,000만)' 등


@dataclass
class TreatmentCard:
    id: str
    label: str
    icon: str
    color_text: str
    items: list[TreatmentItem] = field(default_factory=list)
    subtotal_min: int = 0
    subtotal_max: int = 0

    @property
    def subtotal_display(self) -> str:
        if self.subtotal_min == self.subtotal_max:
            return _format_man(self.subtotal_min)
        return f"{_format_man(self.subtotal_min)}~\n{_format_man(self.subtotal_max)}"


def _format_man(man: int) -> str:
    """150 → '150만원', 30000 → '3억원', 32000 → '3억 2,000만원'"""
    if man == 0:
        return "0만원"
    eok = man // 10000
    rest = man % 10000
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    if eok:
        return f"{eok}억원"
    return f"{man:,}만원"


# ─────────────────────────────────────────────────────────────
# Product type matching
# ─────────────────────────────────────────────────────────────

def pick_product_type(product_name: str, treatments_config: dict) -> Optional[str]:
    for matcher in treatments_config["product_matchers"]:
        for p in matcher["patterns"]:
            if re.search(p, product_name):
                return matcher["id"]
    return None


# ─────────────────────────────────────────────────────────────
# Treatment card building
# ─────────────────────────────────────────────────────────────

def build_treatment_cards(
    coverages: list[Coverage],
    product_type: str,
    treatments_config: dict,
) -> list[TreatmentCard]:
    """해당 상품 타입의 프리셋을 기반으로 치료 카드들을 구성.

    특정 product_type에 카드 프리셋이 없으면, 2대담보처럼 상품 무관하게 동일한
    카드를 적용하는 경우를 위해 `_alias_applied_in_code: true`인 설정에 한해
    `generic_2major` 프리셋으로 fallback한다.
    """
    all_presets = treatments_config.get("cancer_treatment_cards", {})
    cards_config = all_presets.get(product_type, [])
    if not cards_config and treatments_config.get("_alias_applied_in_code"):
        cards_config = all_presets.get("generic_2major", [])
    if not cards_config:
        return []

    result: list[TreatmentCard] = []

    for card_def in cards_config:
        card = TreatmentCard(
            id=card_def["id"],
            label=card_def["label"],
            icon=card_def.get("icon", "ribbon"),
            color_text=card_def.get("color_text", "#993C1D"),
        )

        # exclusive_group 단위로 "가장 큰 금액만" 선택하기 위한 버킷
        # { group_name: [ (TreatmentItem, matching_cov), ... ] }
        exclusive_buckets: dict[str, list[tuple[TreatmentItem, Coverage]]] = {}

        for contrib in card_def.get("contributions", []):
            match_re = contrib["match_coverage"]
            # 해당 담보를 coverages 리스트에서 찾기
            matching_cov = None
            for cov in coverages:
                if re.search(match_re, cov.name):
                    matching_cov = cov
                    break
            if not matching_cov:
                continue

            exclusive_group = contrib.get("exclusive_group")

            for item_def in contrib.get("items", []):
                # follow_coverage_amount=True면 담보의 실제 가입금액을 사용
                if item_def.get("follow_coverage_amount") and matching_cov.amount:
                    amt_man = matching_cov.amount // 10000
                    item = TreatmentItem(
                        coverage_name=matching_cov.name,
                        label=item_def["label"],
                        min_amount=amt_man,
                        max_amount=amt_man,
                        display=_format_man(amt_man),
                    )
                elif "min" in item_def and "max" in item_def:
                    item = TreatmentItem(
                        coverage_name=matching_cov.name,
                        label=item_def["label"],
                        min_amount=item_def["min"],
                        max_amount=item_def["max"],
                        display=item_def.get("display", f"{item_def['min']:,}만({item_def['max']:,}만)"),
                    )
                else:
                    amt = item_def.get("amount", 0)
                    item = TreatmentItem(
                        coverage_name=matching_cov.name,
                        label=item_def["label"],
                        min_amount=amt,
                        max_amount=amt,
                        display=f"{amt:,}만",
                    )

                if exclusive_group:
                    exclusive_buckets.setdefault(exclusive_group, []).append((item, matching_cov))
                else:
                    card.items.append(item)

        # 각 exclusive_group에서 max_amount가 가장 큰 항목 하나만 선택
        for group_name, candidates in exclusive_buckets.items():
            best = max(candidates, key=lambda pair: pair[0].max_amount)
            card.items.append(best[0])

        card.subtotal_min = sum(i.min_amount for i in card.items)
        card.subtotal_max = sum(i.max_amount for i in card.items)

        # 담보가 하나도 안 붙으면 카드 생략
        if card.items:
            result.append(card)

    return result


# ─────────────────────────────────────────────────────────────
# Headline calculation
# ─────────────────────────────────────────────────────────────

@dataclass
class FiveYearHeadline:
    customer_name: str
    annual_min_display: str
    annual_max_display: str
    five_year_min_display: str
    five_year_max_display: str
    kicker: str
    # min == max (= 감액 없음)일 때 템플릿이 단일 금액으로 표시할 수 있도록 힌트 제공.
    # 기존 필드는 그대로 두므로 암 분석기는 영향받지 않음.
    annual_is_range: bool = True
    five_year_is_range: bool = True


def build_headline(
    customer_name: str,
    cards: list[TreatmentCard],
    treatments_config: dict,
) -> Optional[FiveYearHeadline]:
    if not cards:
        return None

    multiplier = treatments_config.get("five_year_multiplier", 5)
    annual_min = sum(c.subtotal_min for c in cards)
    annual_max = sum(c.subtotal_max for c in cards)
    five_year_min = annual_min * multiplier
    five_year_max = annual_max * multiplier

    kicker_tpl = treatments_config.get("five_year_kicker_tpl", "")
    kicker = kicker_tpl.format(customer_name=customer_name)

    return FiveYearHeadline(
        customer_name=customer_name,
        annual_min_display=_format_man(annual_min),
        annual_max_display=_format_man(annual_max),
        five_year_min_display=_format_man(five_year_min),
        five_year_max_display=_format_man(five_year_max),
        kicker=kicker,
        annual_is_range=(annual_min != annual_max),
        five_year_is_range=(five_year_min != five_year_max),
    )


# ─────────────────────────────────────────────────────────────
# Treatment-card expansion with customer view grouping
# ─────────────────────────────────────────────────────────────
# 치료 카드 내에서 같은 담보에서 나온 items를 하나의 계층으로 묶어서 보여주기 위한 유틸

def group_items_by_coverage(card: TreatmentCard) -> list[dict]:
    """같은 담보에서 나온 items를 묶어서 ┗ 계층 표기용 구조로 변환"""
    groups: dict[str, list[TreatmentItem]] = {}
    order: list[str] = []
    for item in card.items:
        if item.coverage_name not in groups:
            groups[item.coverage_name] = []
            order.append(item.coverage_name)
        groups[item.coverage_name].append(item)

    result = []
    for cov_name in order:
        result.append({
            "coverage_name": cov_name,
            "coverage_name_short": _shorten_coverage_name(cov_name),
            "item_list": [asdict(i) for i in groups[cov_name]],
        })
    return result


def _shorten_coverage_name(name: str) -> str:
    """긴 담보명을 카드에 맞게 잘라냄. 원본 사이트는 상세 정보를 ... 으로 축약."""
    # 괄호 안 부가정보 제거
    name = re.sub(r'\(맞춤간편가입\)', '', name)
    name = re.sub(r'\(건강가입\)', '', name)
    name = re.sub(r'\(31간편가입\)', '', name)
    name = re.sub(r'\(통합간편가입\)', '', name)
    name = re.sub(r'\(암중점치료기관\(상급종합병원\s*포함\)\)', '(암중점치료기관(상급종합병원 ...', name)
    name = re.sub(r'\(비급여\(전액본인부담\s*포함\),\s*암중점치료기관\(상급종합병원\s*포함\)\)', '(비급여(전액본인부담 포함), 암중점...', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # 담보 선두의 ┗ 제거
    name = name.lstrip('┗').strip()
    if len(name) > 52:
        name = name[:48] + '...'
    return name
