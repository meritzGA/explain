"""
메리츠 가입제안서 → 고객용 이벤트 기반 보장 요약 변환기

구조:
  1. PDF 업로드
  2. extractor.extract() — PDF에서 고객·계약·담보 파싱
  3. map_to_events() — 담보를 이벤트 버킷으로 분류
  4. Jinja2 render — HTML 생성
  5. st.components.v1.html로 인라인 표시 + 다운로드

속도 목표: 업로드 ~ 화면 렌더까지 3초 이내.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

import streamlit as st
from jinja2 import Environment, FileSystemLoader

from extractor import extract, format_amount_display, Coverage
from treatment_mapper import (
    pick_product_type, build_treatment_cards, build_headline,
    group_items_by_coverage,
)

# ─────────────────────────────────────────────────────────────
# 설정 로드 (앱 시작시 1회)
# ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent


def _find_asset_dir(name: str) -> Path:
    """templates/ 또는 config/ 폴더를 현재 위치부터 상위로 순차 탐색.

    Streamlit Cloud의 작업 디렉터리 차이로 인해 BASE_DIR 상대 경로가 맞지 않을 수
    있어, 여러 후보를 시도하고 실패 시 명확한 에러를 던진다.
    """
    candidates = [
        BASE_DIR / name,                        # 기본 (app.py와 같은 위치)
        BASE_DIR.parent / name,                 # 한 단계 위
        Path.cwd() / name,                      # 현재 작업 디렉터리
        Path.cwd() / "meritz_event_converter" / name,  # 서브폴더 명시적
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    # 실패: 디버깅 정보를 포함한 에러
    tried = "\n".join(f"  - {p}" for p in candidates)
    raise FileNotFoundError(
        f"'{name}' 폴더를 찾을 수 없습니다. 다음 경로를 시도했습니다:\n{tried}\n"
        f"GitHub 레포에 '{name}/' 폴더가 올바르게 업로드되었는지 확인하세요."
    )

@st.cache_resource
def load_analyzer_registry() -> list[dict]:
    """analyzers.json에서 탭으로 표시할 분석기 목록을 로드."""
    with open(_find_asset_dir("config") / "analyzers.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["analyzers"]


@st.cache_resource
def load_config_file(filename: str) -> dict:
    """config/ 아래의 JSON 파일을 파일명으로 로드. 파일명을 캐시 키로 사용."""
    with open(_find_asset_dir("config") / filename, encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource
def load_jinja_env() -> Environment:
    env = Environment(loader=FileSystemLoader(_find_asset_dir("templates")))
    env.globals["icon_svg"] = icon_svg
    env.globals["tx_icon"] = tx_icon_svg
    return env


# ─────────────────────────────────────────────────────────────
# 아이콘 (인라인 SVG — 외부 의존성 X)
# ─────────────────────────────────────────────────────────────

ICONS = {
    "ribbon": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
    "hospital": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 12.5 12 5l7.5 7.5M6 11v8a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-8"/><path d="M12 8v4M10 10h4"/></svg>',
    "brain": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8.5 2a4.5 4.5 0 0 0-4 2.5A3.5 3.5 0 0 0 2 8a3.5 3.5 0 0 0 1 2.5A3.5 3.5 0 0 0 3 14a3.5 3.5 0 0 0 3 3.5A4 4 0 0 0 10 21a4 4 0 0 0 4-4V6a4 4 0 0 0-4-4z"/></svg>',
    "heart": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-4.35-7-10a4 4 0 0 1 7-2.65A4 4 0 0 1 19 11c0 5.65-7 10-7 10z"/></svg>',
    "pulse": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-9 4 18 3-9h4"/></svg>',
    "transplant": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4M16 2v4M4 10h16M5 6h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/></svg>',
    "shield": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 4 6v6c0 5 3.5 9 8 10 4.5-1 8-5 8-10V6z"/></svg>',
    "bone": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 2a3 3 0 0 0-3 3c0 1 .5 2 1.5 2.5C5 8.5 4 9.5 4 11c0 1 .5 2 1.5 2.5-.5 1-1.5 2-1.5 3.5a3 3 0 0 0 3 3c1.5 0 2.5-1 3-1.5.5.5 1.5 1.5 3 1.5a3 3 0 0 0 3-3c0-1.5-1-2.5-1.5-3.5 1-.5 1.5-1.5 1.5-2.5 0-1.5-1-2.5-1.5-3.5.5-.5 1.5-1.5 1.5-3a3 3 0 0 0-3-3c-1.5 0-2.5 1-3 1.5C9.5 3 8.5 2 7 2z"/></svg>',
    "bed": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 17h18M3 17v3M21 17v3M7 9V6a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v3"/></svg>',
    "mini_circle": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/></svg>',
    "coin": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 10h4a2 2 0 1 1 0 4H9"/></svg>',
    "scissors": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/></svg>',
}

def icon_svg(icon_name: str) -> str:
    return ICONS.get(icon_name, ICONS["ribbon"])


# 치료 카드용 큰 아이콘 — 스크린샷의 검은 선 일러스트 스타일
TX_ICONS = {
    # 표적항암: 과녁 + 조준선
    "target_pill": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="22"/>
      <circle cx="28" cy="28" r="14"/>
      <circle cx="28" cy="28" r="6"/>
      <circle cx="28" cy="28" r="1.5" fill="#1F1F1F"/>
      <path d="M28 2v6M28 48v6M2 28h6M48 28h6"/>
      <path d="M44 12l6-6M12 44l-6 6" stroke-width="2.2"/>
    </svg>''',

    # 면역항암: 꽃잎 패턴 (원본 스크린샷은 프로펠러/선풍기 같은 4-way pattern)
    "shield_pill": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="22"/>
      <circle cx="28" cy="28" r="3" fill="#1F1F1F"/>
      <path d="M28 12 Q22 18 28 28 Q34 18 28 12" fill="#1F1F1F" stroke="none"/>
      <path d="M28 44 Q22 38 28 28 Q34 38 28 44" fill="#1F1F1F" stroke="none"/>
      <path d="M12 28 Q18 22 28 28 Q18 34 12 28" fill="#1F1F1F" stroke="none"/>
      <path d="M44 28 Q38 22 28 28 Q38 34 44 28" fill="#1F1F1F" stroke="none"/>
    </svg>''',

    # 양성자방사선: 원자 궤도
    "beam": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="22"/>
      <ellipse cx="28" cy="28" rx="18" ry="8"/>
      <ellipse cx="28" cy="28" rx="18" ry="8" transform="rotate(60 28 28)"/>
      <ellipse cx="28" cy="28" rx="18" ry="8" transform="rotate(120 28 28)"/>
      <circle cx="28" cy="28" r="3" fill="#1F1F1F"/>
      <circle cx="46" cy="28" r="2" fill="#1F1F1F"/>
      <circle cx="18" cy="42" r="2" fill="#1F1F1F"/>
      <circle cx="18" cy="14" r="2" fill="#1F1F1F"/>
    </svg>''',

    # 암수술비: 가위 + 메스 교차
    "scalpel": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="22"/>
      <circle cx="19" cy="20" r="3"/>
      <circle cx="19" cy="36" r="3"/>
      <path d="M21.5 21.5 L38 34M21.5 34.5 L38 22"/>
      <path d="M33 28 L42 32 L44 38 L38 36 L36 30 Z" fill="#1F1F1F" stroke="none"/>
    </svg>''',

    # 다빈치 로봇수술: 다관절 로봇 팔
    "robot": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <!-- 베이스 -->
      <rect x="10" y="42" width="16" height="6" rx="1"/>
      <!-- 1관절 -->
      <path d="M18 42 L18 34"/>
      <circle cx="18" cy="32" r="2.5" fill="#FFFFFF"/>
      <!-- 2관절 팔 -->
      <path d="M18 32 L32 20"/>
      <circle cx="32" cy="20" r="2.5" fill="#FFFFFF"/>
      <!-- 3관절 손 -->
      <path d="M32 20 L44 26"/>
      <!-- 집게 그리퍼 -->
      <path d="M44 26 L48 22 M44 26 L48 30"/>
      <!-- 환자대 하단 암시 -->
      <path d="M8 48 L48 48" stroke-width="1.5"/>
    </svg>''',

    # 항암약물: IV 링거팩 + 방울
    "pill": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <!-- 링거 팩 (상단) -->
      <path d="M20 8 L36 8 L34 24 Q28 30 22 24 Z"/>
      <!-- 팩 걸이 고리 -->
      <path d="M26 4 L26 8 M30 4 L30 8"/>
      <!-- 점액 -->
      <path d="M28 24 L28 34"/>
      <!-- 방울 -->
      <path d="M28 34 Q25 38 28 42 Q31 38 28 34 Z" fill="#1F1F1F"/>
      <!-- 받침 -->
      <path d="M24 48 L32 48"/>
      <!-- 두 번째 방울 (떨어지는) -->
      <circle cx="28" cy="46" r="1" fill="#1F1F1F"/>
    </svg>''',

    # 항암방사선: 방사 삼각 패턴
    "radiation": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="2.5" fill="#1F1F1F"/>
      <path d="M28 8 L20 20 L36 20 Z"/>
      <path d="M48 28 L36 20 L36 36 Z"/>
      <path d="M28 48 L20 36 L36 36 Z"/>
      <path d="M8 28 L20 20 L20 36 Z"/>
      <circle cx="28" cy="28" r="22"/>
    </svg>''',

    # 중입자방사선: 화살 과녁 / 원자 펜던트
    "atom": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10 24 Q10 12 22 12 Q34 12 34 22" stroke-width="2.5"/>
      <circle cx="34" cy="28" r="10"/>
      <circle cx="34" cy="28" r="2" fill="#1F1F1F"/>
      <circle cx="22" cy="12" r="2" fill="#1F1F1F"/>
      <path d="M10 24 L4 24M10 24 L10 30"/>
      <path d="M44 28 L52 28"/>
    </svg>''',

    # 세기조절방사선: 사각 안 과녁
    "focus": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="6" y="6" width="44" height="44" rx="2"/>
      <circle cx="28" cy="28" r="6"/>
      <circle cx="28" cy="28" r="1.5" fill="#1F1F1F"/>
      <path d="M34 22 L44 12"/>
      <path d="M44 12 L44 18 M44 12 L38 12"/>
    </svg>''',

    "ribbon": '''<svg viewBox="0 0 56 56" width="56" height="56" fill="none" stroke="#1F1F1F" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="28" cy="28" r="22"/>
    </svg>''',
}

def tx_icon_svg(icon_name: str) -> str:
    return TX_ICONS.get(icon_name, TX_ICONS["ribbon"])


# ─────────────────────────────────────────────────────────────
# 매퍼: 담보 → 이벤트
# ─────────────────────────────────────────────────────────────

def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(re.search(p, name) for p in patterns) if patterns else False


def map_to_events(coverages: list[Coverage], events_config: dict) -> tuple[list[dict], list[Coverage]]:
    """
    담보를 이벤트 버킷에 할당. 순서가 중요: 먼저 매칭된 이벤트가 선점.
    반환: (이벤트_리스트, 매핑안된_담보_리스트)
    """
    assigned: set[int] = set()  # 이미 할당된 담보의 인덱스
    result_events: list[dict] = []

    for event_def in events_config["events"]:
        matched: list[Coverage] = []

        for idx, cov in enumerate(coverages):
            if idx in assigned:
                continue
            if not _matches_any(cov.name, event_def.get("include_any", [])):
                continue
            if _matches_any(cov.name, event_def.get("exclude_any", [])):
                continue
            matched.append(cov)
            assigned.add(idx)

        if matched:
            result_events.append(_build_event(event_def, matched))

    extras = [c for i, c in enumerate(coverages) if i not in assigned]
    return result_events, extras


def _build_event(event_def: dict, matched: list[Coverage]) -> dict:
    # 총 금액 계산
    total = sum(c.amount for c in matched if c.amount)

    # 서브그룹 분리 (있는 경우)
    subgroups_data = None
    if "subgroups" in event_def:
        subgroups_data = []
        remaining = list(matched)
        for sg_def in event_def["subgroups"]:
            pattern = sg_def["match"]
            sg_matched = [c for c in remaining if re.search(pattern, c.name)]
            for c in sg_matched:
                remaining.remove(c)
            if sg_matched:
                subgroups_data.append({
                    "label": sg_def["label"],
                    "coverages": [asdict(c) for c in sg_matched],
                    "subtotal": sum(c.amount for c in sg_matched if c.amount),
                })
        # 어디에도 안 맞는 잔여분은 "기타" 서브그룹으로
        if remaining:
            subgroups_data.append({
                "label": "기타",
                "coverages": [asdict(c) for c in remaining],
                "subtotal": sum(c.amount for c in remaining if c.amount),
            })

    return {
        "id": event_def["id"],
        "label": event_def["label"],
        "color": event_def["color"],
        "icon": event_def.get("icon", "ribbon"),
        "question": event_def.get("question", ""),
        "description": event_def.get("description", ""),
        "unit": event_def.get("unit", ""),
        "amount_display": "최대 " + format_amount_display(total) if total and not subgroups_data else format_amount_display(total),
        "total": total,
        "coverages": [asdict(c) for c in matched],
        "subgroups": subgroups_data,
    }


# ─────────────────────────────────────────────────────────────
# 캐시된 처리 파이프라인 — 2단계
#   1) parse_pdf: PDF당 1회만 (담보 추출은 비싸므로 분석기 간 공유)
#   2) build_analyzer_result: 분석기별로 매핑만 수행
# ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def parse_pdf(pdf_bytes: bytes) -> dict:
    """PDF → 고객·계약·담보 데이터. 분석기 전체가 공유."""
    data = extract(pdf_bytes)
    return {
        "customer": asdict(data.customer),
        "policy": asdict(data.policy),
        "coverages": [asdict(c) for c in data.coverages],
    }


@st.cache_data(show_spinner=False)
def build_analyzer_result(pdf_bytes: bytes, analyzer_id: str) -> dict:
    """분석기 ID별 매핑 결과. pdf_bytes + analyzer_id가 캐시 키."""
    # 레지스트리에서 이 분석기 설정 찾기
    registry = load_analyzer_registry()
    analyzer = next((a for a in registry if a["id"] == analyzer_id), None)
    if not analyzer:
        raise ValueError(f"Unknown analyzer: {analyzer_id}")

    events_config = load_config_file(analyzer["events_config"])
    treatments_config = load_config_file(analyzer["treatments_config"])

    # PDF 파싱 결과 재사용
    parsed = parse_pdf(pdf_bytes)
    coverages = [Coverage(**c) for c in parsed["coverages"]]

    # 이벤트 매핑 (참고용 extras 정리)
    mapped_events, extras = map_to_events(coverages, events_config)

    # 치료 방식별 서브카드 구성
    policy = parsed["policy"]
    combined_product_str = f"{policy.get('product_name_short', '')} {policy.get('product_name_full', '')}"
    product_type = pick_product_type(combined_product_str, treatments_config)
    treatment_cards_raw = build_treatment_cards(coverages, product_type, treatments_config) if product_type else []
    # 2대담보처럼 alias fallback이 켜져 있으면 product_type이 None이어도 시도
    if not treatment_cards_raw and treatments_config.get("_alias_applied_in_code"):
        treatment_cards_raw = build_treatment_cards(coverages, "generic_2major", treatments_config)
    headline = build_headline(parsed["customer"]["name"], treatment_cards_raw, treatments_config) if treatment_cards_raw else None

    # 템플릿용 dict 변환
    treatment_cards = []
    for card in treatment_cards_raw:
        groups = group_items_by_coverage(card)
        treatment_cards.append({
            "id": card.id,
            "label": card.label,
            "icon": card.icon,
            "color_text": card.color_text,
            "subtotal_min": card.subtotal_min,
            "subtotal_max": card.subtotal_max,
            "subtotal_display": card.subtotal_display,
            "groups": groups,
        })

    return {
        "customer": parsed["customer"],
        "policy": parsed["policy"],
        "events": mapped_events,
        "extras": [asdict(c) for c in extras],
        "coverages_all": parsed["coverages"],
        "treatment_cards": treatment_cards,
        "headline": asdict(headline) if headline else None,
        "product_type": product_type,
        # analyzers.json의 report_label이 우선. 없으면 treatments_config 값, 그것도 없으면 "치료비"
        "report_label": analyzer.get("report_label")
                        or treatments_config.get("report_title_prefix")
                        or "치료비",
        # 감액 구조(1년 미경과시 50%)가 있는지. 2대담보는 false → min/max 단일 표기 + 안내문구 숨김
        "has_deduction": treatments_config.get("has_deduction", True),
        "analyzer_id": analyzer_id,
        "tab_label": analyzer["tab_label"],
    }


def render_html(processed: dict) -> str:
    env = load_jinja_env()
    tpl = env.get_template("report.html")
    return tpl.render(**processed)


# ─────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────

def _render_analyzer_tab(result: dict, pdf_bytes: bytes, source_filename: str):
    """한 분석기의 결과를 렌더링. 인라인 HTML + 검수 expander."""
    # 파일 정보 주입
    result = dict(result)  # 캐시 내용 오염 방지 복사
    result["source_filename"] = source_filename
    kb = len(pdf_bytes) / 1024
    result["source_filesize"] = f"{kb:,.1f} KB"
    html = render_html(result)

    report_label = result.get("report_label", "분석")

    # 인라인 렌더 — 치료 카드가 없을 때는 안내
    if not result.get("treatment_cards"):
        st.warning(
            f"이 가입제안서에서 '{report_label}' 관련 담보를 찾지 못했습니다. "
            f"상품에 해당 담보가 포함되지 않았거나, 담보명 패턴이 설정과 다를 수 있습니다."
        )
    st.components.v1.html(html, height=2200, scrolling=True)

    # 검수 영역 (접혀있음) — 탭별 key 부여
    with st.expander("파싱 결과 원본 보기 (검수용)"):
        inner_tab1, inner_tab2 = st.tabs(["담보 전체", "치료 카드 매핑"])
        with inner_tab1:
            st.dataframe(
                result["coverages_all"],
                use_container_width=True,
                hide_index=True,
            )
        with inner_tab2:
            pt = result.get("product_type") or "매칭된 상품 타입 없음"
            st.caption(f"상품 타입: {pt}")
            if not result.get("treatment_cards"):
                st.warning("치료 카드가 생성되지 않았습니다.")
            for card in result.get("treatment_cards", []):
                with st.container(border=True):
                    st.markdown(f"**{card['label']}** — {card['subtotal_display'].replace(chr(10), ' ')}")
                    for g in card["groups"]:
                        st.caption(f"• {g['coverage_name_short']}")
                        for it in g["item_list"]:
                            st.caption(f"    ┗ {it['label']}: {it['display']}")


# ─────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="메리츠 보장 분석기",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # ── 프리미엄 스타일: Pretendard 폰트 + 헤드 타이틀 + 업로더 + 탭 ──
    # @import로 폰트 로드 (link 태그는 Streamlit이 제거할 수 있음).
    # triple-quoted 내부는 들여쓰기 없이 시작해야 markdown 파서가 code block으로 오인하지 않음.
    st.markdown("""<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

/* ── Pretendard를 Streamlit 전역에 강제 적용 ── */
html, body, .stApp, .stApp *,
.stMarkdown *, [data-testid="stMarkdownContainer"] *,
[data-testid="stFileUploader"] *, [data-testid="stTabs"] *,
button, input, textarea, select {
  font-family: 'Pretendard Variable', Pretendard,
               -apple-system, BlinkMacSystemFont, system-ui,
               'Segoe UI', 'Apple SD Gothic Neo', 'Noto Sans KR',
               'Malgun Gothic', sans-serif !important;
  font-feature-settings: 'tnum' on, 'ss03' on;
}

/* 배경과 여백 */
.stApp { background: #EEEEEE; }
[data-testid="stHeader"] { background: transparent; }
.block-container {
  padding-top: 2.5rem;
  padding-bottom: 2rem;
  max-width: 1240px;
}

/* ── 커다란 헤드 타이틀 ── */
.hero-title {
  font-size: 56px;
  font-weight: 800;
  letter-spacing: -2px;
  line-height: 1.05;
  color: #1F1F1F;
  margin: 0 0 8px 0;
}
.hero-title .brand {
  color: #E53935;
  letter-spacing: -2.5px;
}
.hero-sub {
  color: #6A6A6A;
  font-size: 16px;
  font-weight: 500;
  letter-spacing: -0.3px;
  margin: 0 0 32px 0;
}

/* ── 파일 업로더: 커스텀 디자인 오버레이 ──
   Streamlit 기본 문구/버튼을 모두 숨기고 아이콘+한글 문구를 덮어 그림.
   dropzone 자체 크기는 유지해서 클릭/드래그 hit area를 살림. */
[data-testid="stFileUploader"] {
  background: transparent;
  position: relative;
}

/* 외곽 dashed 박스 + 중앙에 아이콘을 background로 그림 */
[data-testid="stFileUploaderDropzone"] {
  background-color: #FFFFFF !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='68' height='68' viewBox='0 0 68 68'><rect width='68' height='68' rx='18' fill='%23FFEAEA'/><g transform='translate(16 16)' fill='none' stroke='%23E53935' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M22 2H6a2 2 0 0 0-2 2v28a2 2 0 0 0 2 2h24a2 2 0 0 0 2-2V12z'/><polyline points='22 2 22 12 32 12'/><line x1='18' y1='28' x2='18' y2='18'/><polyline points='13 23 18 18 23 23'/></g></svg>") !important;
  background-repeat: no-repeat !important;
  background-position: center calc(50% - 50px) !important;
  border: 2px dashed #D5D5D5 !important;
  border-radius: 20px !important;
  min-height: 260px !important;
  padding: 0 !important;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
  cursor: pointer;
}
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: #E53935 !important;
  background-color: #FFFAFA !important;
}

/* Streamlit 기본 dropzone 내부 요소들 모두 숨김 */
[data-testid="stFileUploaderDropzone"] > section,
[data-testid="stFileUploaderDropzone"] > div,
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] button {
  visibility: hidden !important;
}

/* 메인 문구 */
[data-testid="stFileUploaderDropzone"]::before {
  content: "제안서 파일을 이곳에 놓아주세요";
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  transform: translateY(14px);
  text-align: center;
  visibility: visible !important;
  pointer-events: none;
  font-family: 'Pretendard Variable', Pretendard, sans-serif;
  font-size: 20px;
  font-weight: 700;
  color: #1F1F1F;
  letter-spacing: -0.6px;
}

/* 서브 문구 */
[data-testid="stFileUploaderDropzone"]::after {
  content: "PDF 파일을 드래그하거나 클릭하여 시작하세요";
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  transform: translateY(46px);
  text-align: center;
  visibility: visible !important;
  pointer-events: none;
  font-family: 'Pretendard Variable', Pretendard, sans-serif;
  font-size: 14px;
  font-weight: 500;
  color: #9A9A9A;
  letter-spacing: -0.3px;
}

/* 업로더 하단 안내 문구 (별도 요소) */
.uploader-helper {
  margin-top: 18px;
  text-align: center;
  color: #8A8A8A;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: -0.2px;
}

/* ─────────────────────────────────────────────────────────
   업로드 완료 상태 — 커스텀 파일 카드 + 취소 버튼
   ─────────────────────────────────────────────────────────
   Streamlit의 file_uploader는 업로드 후 session_state로 숨겨지고,
   대신 아래 HTML 카드 + st.button으로 구성됨. */

.file-loaded-card {
  background: #FFFFFF;
  border: 1px solid #F0F0F0;
  border-radius: 20px;
  padding: 16px 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  display: flex;
  align-items: center;
  gap: 16px;
}
.file-loaded-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: #FFEAEA;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.file-loaded-icon svg {
  width: 22px;
  height: 22px;
}
.file-loaded-info {
  flex: 1;
  min-width: 0;
}
.file-loaded-name {
  font-size: 15px;
  font-weight: 600;
  color: #1F1F1F;
  letter-spacing: -0.3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-loaded-size {
  font-size: 12px;
  color: #9A9A9A;
  font-weight: 500;
  margin-top: 2px;
}

/* "파일 취소 하기" 버튼 스타일 (st.button으로 렌더됨) */
[data-testid="stButton"] button[kind="secondary"] {
  background: #F5F5F5 !important;
  color: #6A6A6A !important;
  border: none !important;
  border-radius: 999px !important;
  padding: 12px 14px !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  letter-spacing: -0.2px;
  transition: all 0.15s ease;
  height: 74px !important;
  white-space: nowrap !important;
}
[data-testid="stButton"] button[kind="secondary"]:hover {
  background: #E8E8E8 !important;
  color: #1F1F1F !important;
}

/* ── 탭 라벨 크게 ── */
.stTabs { margin-top: 24px; }
.stTabs [data-baseweb="tab-list"] {
  gap: 4px;
  border-bottom: 1.5px solid #E0E0E0;
}
.stTabs [data-baseweb="tab"] {
  font-size: 17px !important;
  font-weight: 700 !important;
  letter-spacing: -0.4px;
  padding: 14px 28px !important;
  color: #8A8A8A;
  background: transparent;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
  color: #E53935 !important;
}
.stTabs [data-baseweb="tab-highlight"] {
  background: #E53935 !important;
  height: 3px !important;
}
.stTabs [data-baseweb="tab-panel"] { padding-top: 24px; }
</style>""", unsafe_allow_html=True)

    registry = load_analyzer_registry()

    # ── 시원시원한 헤드 타이틀 ──
    st.markdown(
        '<div class="hero-title">'
        '<span class="brand">메리츠</span> 보장 분석기'
        '</div>'
        '<div class="hero-sub">'
        '가입제안서 PDF 하나로 <strong>암 · 2대담보</strong>를 한 번에 분석합니다.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 파일 업로드 상태 관리 ──
    # session_state에 PDF bytes와 파일명을 저장. 업로드 완료 상태에선 uploader를 숨김.
    if "uploaded_pdf_bytes" not in st.session_state:
        st.session_state.uploaded_pdf_bytes = None
        st.session_state.uploaded_pdf_name = None

    # 업로드 전 상태 — file_uploader 렌더
    if st.session_state.uploaded_pdf_bytes is None:
        uploaded = st.file_uploader(
            "가입제안서 PDF를 업로드하세요",
            type="pdf",
            label_visibility="collapsed",
            key="pdf_uploader",
        )
        # 업로더 하단 안내 문구
        st.markdown(
            '<div class="uploader-helper">'
            '* 가입제안서안에 있는 담보 가입금액을 꼭 계산해보고 참고용으로만 사용하세요'
            '</div>',
            unsafe_allow_html=True,
        )
        if uploaded is None:
            return  # 업로드 대기
        # 업로드 완료 → session_state에 저장 후 rerun
        st.session_state.uploaded_pdf_bytes = uploaded.read()
        st.session_state.uploaded_pdf_name = uploaded.name
        st.rerun()

    pdf_bytes = st.session_state.uploaded_pdf_bytes
    file_name = st.session_state.uploaded_pdf_name

    # ── 업로드 완료 상태 — 커스텀 파일 카드 렌더 ──
    size_kb = len(pdf_bytes) / 1024
    size_str = f"{size_kb:,.1f} KB" if size_kb < 1024 else f"{size_kb/1024:,.2f} MB"

    file_card_col, btn_col = st.columns([10, 1.5], gap="small")
    with file_card_col:
        st.markdown(
            f'''<div class="file-loaded-card">
                <div class="file-loaded-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="#E53935" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                </div>
                <div class="file-loaded-info">
                    <div class="file-loaded-name">{file_name}</div>
                    <div class="file-loaded-size">{size_str}</div>
                </div>
            </div>''',
            unsafe_allow_html=True,
        )
    with btn_col:
        if st.button("파일 취소 하기", key="cancel_upload", use_container_width=True):
            st.session_state.uploaded_pdf_bytes = None
            st.session_state.uploaded_pdf_name = None
            st.rerun()

    # 각 분석기를 순차 처리. parse_pdf는 첫 호출에서만 실제 파싱, 이후는 캐시 히트
    results: dict[str, dict] = {}
    with st.spinner("분석 중..."):
        for analyzer in registry:
            results[analyzer["id"]] = build_analyzer_result(pdf_bytes, analyzer["id"])

    # 탭 구성 — registry 순서대로
    tab_labels = [a["tab_label"] for a in registry]
    tabs = st.tabs(tab_labels)

    for tab, analyzer in zip(tabs, registry):
        with tab:
            _render_analyzer_tab(results[analyzer["id"]], pdf_bytes, file_name)


if __name__ == "__main__":
    main()
