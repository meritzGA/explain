"""
담보 리스트를 '치료 방식별 서브카드'로 분해하는 매퍼.

동작 방식:
  1. 상품명에서 product_matcher 결정 → 어떤 치료 카드 프리셋을 쓸지 선택
  2. 각 치료 카드의 contributions를 순회하며 매칭되는 담보를 찾아 금액 합산
     - 담보가 가이드(비통치/암통치/순통치) 매트릭스에 해당하면 tier 조회로
       세부 항목 금액을 동적 결정 (guide_amounts.json)
  3. 실제로 담보가 존재하는 치료 카드만 반환 (담보 없으면 카드 생략)
  4. 5년 헤드라인 금액 계산 (전체 min/max 합계 × 5)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from extractor import Coverage


# ─────────────────────────────────────────────────────────────
# Guide amounts loader (singleton cache)
# ─────────────────────────────────────────────────────────────

_GUIDE_CACHE: Optional[dict] = None


def _load_guide_amounts() -> dict:
    """config/guide_amounts.json을 1회 로드하여 메모리에 캐시."""
    global _GUIDE_CACHE
    if _GUIDE_CACHE is not None:
        return _GUIDE_CACHE
    path = Path(__file__).parent / "config" / "guide_amounts.json"
    if not path.exists():
        _GUIDE_CACHE = {}
        return _GUIDE_CACHE
    with open(path, "r", encoding="utf-8") as f:
        _GUIDE_CACHE = json.load(f)
    return _GUIDE_CACHE


def _match_guide_group(coverage_name: str, guide: dict) -> Optional[str]:
    """담보명이 어느 가이드 그룹에 매칭되는지 반환 (bitonchi_premium 등)."""
    for key, group in guide.items():
        if key.startswith("_"):
            continue
        # exclude 먼저 체크
        excludes = group.get("exclude_if_name_contains", [])
        if any(ex in coverage_name for ex in excludes):
            continue
        for pat in group.get("match_patterns", []):
            if re.search(pat, coverage_name):
                return key
    return None


def _pick_tier(cap_man: int, group: dict) -> Optional[str]:
    """가입금액(만원)에 정확히 일치하는 tier key를 반환. 없으면 None."""
    tiers = group.get("tiers", {})
    if str(cap_man) in tiers:
        return str(cap_man)
    return None


def resolve_coverage_to_guide(cov: Coverage) -> Optional[tuple[str, str, dict]]:
    """담보를 가이드 tier에 매핑.

    Returns:
        (group_key, tier_key, items_dict) or None.
        items_dict: 해당 tier의 세부 치료 항목 → 금액(만원) 매핑.
    """
    guide = _load_guide_amounts()
    group_key = _match_guide_group(cov.name, guide)
    if not group_key:
        return None
    group = guide[group_key]
    cap_man = (cov.amount or 0) // 10000
    if cap_man == 0:
        return None
    # cancer_integrated_III는 tier 조회 대신 cap 그대로 사용
    if group_key == "cancer_integrated_III":
        return (group_key, "special", {"cap_man": cap_man})
    tier_key = _pick_tier(cap_man, group)
    if not tier_key:
        return None
    items = group["tiers"][tier_key]
    return (group_key, tier_key, items)


# 카드 id → (라벨 템플릿, 가이드 items의 어떤 key들을 합산할지) 매핑.
# 가이드 key가 복수인 경우(예: surgery_cancer_per_time + surgery_pseudo_per_time)
# 별도 item으로 각각 표시.
_CARD_TO_GUIDE_ITEMS: dict[str, list[dict]] = {
    "targeted": [
        {"keys": ["targeted"], "label_tpl": "(연1회) 비급여 표적항암약물 치료비"},
    ],
    "immune": [
        {"keys": ["immune"], "label_tpl": "(연1회) 비급여 면역항암약물 치료비"},
    ],
    "proton": [
        {"keys": ["proton"], "label_tpl": "(연1회) 비급여 항암양성자방사선 치료비"},
    ],
    "surgery": [
        {"keys": ["surgery_cancer_per_time"], "label_tpl": "(매회) 암 수술비"},
        {"keys": ["surgery_pseudo_per_time"], "label_tpl": "(매회) 유사암 수술비"},
    ],
    "davinci": [
        {"keys": ["davinci_cancer"], "label_tpl": "(연1회) 비급여 다빈치로봇암수술비 (일반암)"},
        {"keys": ["davinci_specific_cancer"], "label_tpl": "(연1회) 비급여 다빈치로봇암수술비 (전립선암·갑상선암)"},
    ],
    "chemo": [
        {"keys": ["chemo_cancer"], "label_tpl": "(연1회) 암 항암약물치료비"},
        {"keys": ["chemo_skin_thyroid"], "label_tpl": "(연1회) 기타피부암·갑상선암 항암약물치료비"},
    ],
    "radiation": [
        {"keys": ["radiation_cancer"], "label_tpl": "(연1회) 암 항암방사선치료비"},
        {"keys": ["radiation_skin_thyroid"], "label_tpl": "(연1회) 기타피부암·갑상선암 항암방사선치료비"},
    ],
    "imrt": [
        {"keys": ["imrt"], "label_tpl": "(연1회) 항암세기조절방사선 치료비"},
    ],
    # carbon_ion은 별도 담보(165번)에서만 오므로 가이드에서 제공하지 않음 → 기존 contributions 사용

    # ── 2대담보 탭의 특정순환계질환 통합치료비 카드 (순통치) ──
    # 한 카드 안에 순통치의 세부 치료 항목을 전부 펼쳐서 표시.
    "circulatory_integrated": [
        {"keys": ["surgery_per_time"],   "label_tpl": "(수술 1회당) 수술"},
        {"keys": ["thrombolysis"],       "label_tpl": "(연1회) 혈전용해치료"},
        {"keys": ["icu"],                "label_tpl": "(연1회) 종합병원 중환자실치료"},
        {"keys": ["ecmo"],               "label_tpl": "(연1회) 에크모(부분체외순환치료)"},
        {"keys": ["crrt"],               "label_tpl": "(연1회) 지속적신대체요법(CRRT)"},
        {"keys": ["ventilator"],         "label_tpl": "(연1회) 인공호흡기치료(12시간초과)"},
        {"keys": ["hypothermia"],        "label_tpl": "(연1회) 저체온요법치료"},
    ],
}


def _build_guide_items_for_card(
    card_id: str,
    cov: Coverage,
) -> Optional[list["TreatmentItem"]]:
    """담보를 가이드에 매칭하여 특정 카드에 해당하는 TreatmentItem 리스트 반환.

    Returns:
        - None: 이 담보는 가이드 매칭 대상이 아님 (→ 기존 하드코딩 items 사용)
        - []: 가이드 매칭은 됐지만 이 카드에 해당하는 항목이 없음 (빈 기여 → 스킵)
        - [items...]: 가이드 tier에서 뽑아낸 이 카드용 items
    """
    resolved = resolve_coverage_to_guide(cov)
    if not resolved:
        return None
    group_key, tier_key, items_dict = resolved

    # 특수 케이스: cancer_integrated_III (116번)
    # → 표적항암 or 양성자방사선 카드에만 cap 추가
    if group_key == "cancer_integrated_III":
        cap_man = items_dict.get("cap_man", 0)
        if cap_man == 0:
            return []
        if card_id == "targeted":
            return [TreatmentItem(
                coverage_name=cov.name,
                label=f"(연간 치료횟수 2회시) 표적항암약물 치료 전액 추가",
                min_amount=cap_man,
                max_amount=cap_man,
                display=_format_man(cap_man),
            )]
        if card_id == "proton":
            return [TreatmentItem(
                coverage_name=cov.name,
                label=f"(연간 치료횟수 2회시) 항암양성자방사선 치료 전액 추가",
                min_amount=cap_man,
                max_amount=cap_man,
                display=_format_man(cap_man),
            )]
        return []  # 다른 카드엔 기여 없음

    # 일반 tier 조회
    card_mapping = _CARD_TO_GUIDE_ITEMS.get(card_id)
    if not card_mapping:
        return []  # 이 카드는 가이드에서 표현 불가 → 빈 기여

    result: list["TreatmentItem"] = []
    for map_entry in card_mapping:
        for gkey in map_entry["keys"]:
            amt = items_dict.get(gkey)
            if amt is None or amt == 0:
                continue
            result.append(TreatmentItem(
                coverage_name=cov.name,
                label=map_entry["label_tpl"],
                min_amount=amt,
                max_amount=amt,
                display=f"{amt:,}만",
            ))
    return result


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
    items: list = field(default_factory=list)
    subtotal_min: int = 0
    subtotal_max: int = 0
    # True(기본): 매년 반복 지급 가능 → 5년 헤드라인 계산시 × 5
    # False: 최초 1회한 지급(진단비 등) → 5년 헤드라인에서 1회만 합산
    recurring: bool = True

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
            recurring=card_def.get("recurring", True),
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

            # ▼ 가이드 우회: 매칭된 담보가 가이드(비통치/암통치/순통치)에 해당하면
            # 하드코딩된 items 대신 가이드 tier 값으로 이 카드 전용 item을 생성.
            guide_override_items = _build_guide_items_for_card(
                card_def["id"], matching_cov
            )
            if guide_override_items is not None:
                # 가이드에서 이 카드에 해당하는 항목이 있으면 그것들을 사용
                for item in guide_override_items:
                    if exclusive_group:
                        exclusive_buckets.setdefault(exclusive_group, []).append((item, matching_cov))
                    else:
                        card.items.append(item)
                continue  # 기존 items 루프 건너뛰기

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
                        display=item_def.get("display", f"{amt:,}만"),
                    )

                if exclusive_group:
                    exclusive_buckets.setdefault(exclusive_group, []).append((item, matching_cov))
                else:
                    card.items.append(item)

        # 각 exclusive_group에서 max_amount가 가장 큰 항목 하나만 선택
        for group_name, candidates in exclusive_buckets.items():
            best = max(candidates, key=lambda pair: pair[0].max_amount)
            card.items.append(best[0])

        # ▼ 가이드 자동 기여: contributions에 명시되지 않았더라도, 담보가
        # 가이드(비통치/암통치/순통치)에 매칭되고 해당 카드에 해당하는
        # 항목이 있으면 자동으로 편입. 이미 편입된 담보는 건너뜀.
        # (예: treatments_cancer.json에 '(실속형)' 매칭 패턴이 없어도
        # guide_amounts.json에 amtonchi_economy 정의가 있으면 자동 기여.)
        already_contributed_cov_names = {it.coverage_name for it in card.items}
        for cov in coverages:
            if cov.name in already_contributed_cov_names:
                continue
            auto_items = _build_guide_items_for_card(card_def["id"], cov)
            if auto_items:
                for it in auto_items:
                    card.items.append(it)

        # Subtotal 계산 — 기본은 items 단순 합.
        # subtotal_mode: "coverage_cap"이면 담보 가입금액을 상한(cap)으로 사용.
        # 예: 특정순환계질환 통합치료비 — 세부 치료 항목을 나열하지만
        # 연간 총 지급액은 담보 가입금액을 넘지 않음(예: 5,000만원 한도).
        subtotal_mode = card_def.get("subtotal_mode", "sum")
        if subtotal_mode == "coverage_cap":
            # 이 카드에 매칭된 담보 중 가장 큰 가입금액을 cap으로 사용
            caps = [
                cov.amount // 10000
                for contrib in card_def.get("contributions", [])
                for cov in coverages
                if cov.amount and re.search(contrib["match_coverage"], cov.name)
            ]
            if caps:
                cap_man = max(caps)
                card.subtotal_min = cap_man
                card.subtotal_max = cap_man
            else:
                card.subtotal_min = sum(i.min_amount for i in card.items)
                card.subtotal_max = sum(i.max_amount for i in card.items)
        else:
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

    # 연간 합계는 "매년 받을 수 있는 반복 지급 금액"만 포함
    # 1회한(진단비 등)은 annual에서 제외 — 5년으로 곱해지면 안 됨
    recurring_cards = [c for c in cards if c.recurring]
    onetime_cards = [c for c in cards if not c.recurring]

    annual_min = sum(c.subtotal_min for c in recurring_cards)
    annual_max = sum(c.subtotal_max for c in recurring_cards)

    # 1회한 카드 합 (평생 1회만 더해짐)
    onetime_min = sum(c.subtotal_min for c in onetime_cards)
    onetime_max = sum(c.subtotal_max for c in onetime_cards)

    # 5년 최대 = (연간 반복금액 × 5년) + (1회한 전체)
    five_year_min = annual_min * multiplier + onetime_min
    five_year_max = annual_max * multiplier + onetime_max

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
