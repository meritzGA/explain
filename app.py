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

@st.cache_resource
def load_events_config() -> dict:
    with open(BASE_DIR / "config" / "events.json", encoding="utf-8") as f:
        return json.load(f)

@st.cache_resource
def load_treatments_config() -> dict:
    with open(BASE_DIR / "config" / "treatments.json", encoding="utf-8") as f:
        return json.load(f)

@st.cache_resource
def load_jinja_env() -> Environment:
    env = Environment(loader=FileSystemLoader(BASE_DIR / "templates"))
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


# 치료 카드용 아이콘 (검은 테두리 원 안에 들어가는 작은 아이콘)
TX_ICONS = {
    "target_pill": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.5" fill="#1F1D2B"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke-linecap="round"/></svg>',
    "shield_pill": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><path d="M12 3 4 7v5c0 5 3.5 8 8 9 4.5-1 8-4 8-9V7z"/><path d="M8 11h8M10 8l4 6M14 8l-4 6" stroke-linecap="round"/></svg>',
    "beam": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7" stroke-dasharray="2 2"/><path d="M12 5v-2M12 21v-2M5 12h-2M21 12h-2M7 7l-1.5-1.5M17 17l1.5 1.5M7 17l-1.5 1.5M17 7l1.5-1.5" stroke-linecap="round"/></svg>',
    "scalpel": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 3.5 20 9l-10 10H4v-6z"/><path d="M6 13h4M8 11v4"/></svg>',
    "robot": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="8" width="14" height="10" rx="2"/><circle cx="9" cy="13" r="1" fill="#1F1D2B"/><circle cx="15" cy="13" r="1" fill="#1F1D2B"/><path d="M12 8V5M10 5h4M7 18v3M17 18v3"/></svg>',
    "pill": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><rect x="3" y="8" width="18" height="8" rx="4"/><path d="M12 8v8" stroke-linecap="round"/></svg>',
    "radiation": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><circle cx="12" cy="12" r="2.5" fill="#1F1D2B"/><path d="M12 3a9 9 0 0 0-7.8 4.5L12 12zM20.8 7.5A9 9 0 0 0 12 3v9zM12 21a9 9 0 0 0 7.8-4.5L12 12zM4.2 16.5A9 9 0 0 0 12 21v-9z" stroke-linejoin="round"/></svg>',
    "atom": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><circle cx="12" cy="12" r="1.5" fill="#1F1D2B"/><ellipse cx="12" cy="12" rx="10" ry="4"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(120 12 12)"/></svg>',
    "focus": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><circle cx="12" cy="12" r="2" fill="#1F1D2B"/><circle cx="12" cy="12" r="6"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke-linecap="round"/></svg>',
    "ribbon": '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1F1D2B" stroke-width="1.5"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" stroke-linejoin="round"/></svg>',
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
# 캐시된 전체 처리 파이프라인
# ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def process_pdf(pdf_bytes: bytes) -> dict:
    """파일 해시를 키로 캐싱. 같은 PDF 두 번째 업로드시 즉시 반환."""
    data = extract(pdf_bytes)
    events_config = load_events_config()
    treatments_config = load_treatments_config()

    mapped_events, extras = map_to_events(data.coverages, events_config)

    # 치료 방식별 서브카드 구성
    combined_product_str = f"{data.policy.product_name_short} {data.policy.product_name_full}"
    product_type = pick_product_type(combined_product_str, treatments_config)
    treatment_cards_raw = build_treatment_cards(data.coverages, product_type, treatments_config) if product_type else []
    headline = build_headline(data.customer.name, treatment_cards_raw, treatments_config) if treatment_cards_raw else None

    # 템플릿에 넣을 dict 형태로 변환 (같은 담보의 items를 그룹핑)
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
        "customer": asdict(data.customer),
        "policy": asdict(data.policy),
        "events": mapped_events,
        "extras": [asdict(c) for c in extras],
        "coverages_all": [asdict(c) for c in data.coverages],
        "treatment_cards": treatment_cards,
        "headline": asdict(headline) if headline else None,
        "product_type": product_type,
    }


def render_html(processed: dict) -> str:
    env = load_jinja_env()
    tpl = env.get_template("report.html")
    return tpl.render(**processed)


# ─────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="메리츠 제안서 → 고객용 요약",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown("""
    <style>
      .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1100px; }
      h1 { font-size: 26px !important; font-weight: 500 !important; }
    </style>
    """, unsafe_allow_html=True)

    st.title("메리츠 가입제안서 → 고객용 보장 요약")
    st.caption("PDF 제안서를 올리면 이벤트 기반 보장 요약을 자동으로 만들어 드립니다.")

    uploaded = st.file_uploader(
        "제안서 PDF를 올려주세요",
        type="pdf",
        help="메리츠 가입제안서 PDF를 업로드하면 자동으로 변환됩니다.",
    )

    if not uploaded:
        st.info("왼쪽 상단에 PDF를 업로드하시면 자동으로 요약이 생성됩니다.")
        return

    pdf_bytes = uploaded.read()
    file_hash = hashlib.md5(pdf_bytes).hexdigest()[:8]

    with st.spinner("변환 중..."):
        processed = process_pdf(pdf_bytes)
        html = render_html(processed)

    col_left, col_right = st.columns([3, 1])
    with col_left:
        st.subheader(f"{processed['customer']['name']} 고객 보장 요약")
    with col_right:
        st.download_button(
            "HTML 다운로드",
            data=html.encode("utf-8"),
            file_name=f"{processed['customer']['name']}_보장요약.html",
            mime="text/html",
            use_container_width=True,
        )

    # 렌더된 HTML 표시
    st.components.v1.html(html, height=2400, scrolling=True)

    # 디버그/검수용 원본 데이터
    with st.expander("파싱 결과 원본 보기 (검수용)"):
        tab1, tab2, tab3 = st.tabs(["요약", "담보 전체", "이벤트 매핑"])

        with tab1:
            c1, c2, c3 = st.columns(3)
            c1.metric("담보 개수", len(processed["coverages_all"]))
            c2.metric("매핑된 이벤트", len(processed["events"]))
            c3.metric("그 밖에 보장", len(processed["extras"]))

            st.write("**고객 정보**")
            st.json(processed["customer"])
            st.write("**계약 정보**")
            st.json(processed["policy"])

        with tab2:
            st.dataframe(
                processed["coverages_all"],
                use_container_width=True,
                hide_index=True,
            )

        with tab3:
            for ev in processed["events"]:
                with st.container(border=True):
                    st.markdown(f"**{ev['label']}** — {ev['amount_display']}")
                    st.caption(f"매칭된 담보 {len(ev['coverages'])}개 · 합계 {ev['total']:,}원")
                    for c in ev["coverages"]:
                        st.caption(f"• [{c['code']}] {c['name']} ({c['amount_display']})")
            if processed["extras"]:
                with st.container(border=True):
                    st.markdown(f"**그 밖에 보장** — {len(processed['extras'])}개")
                    for c in processed["extras"]:
                        st.caption(f"• [{c['code']}] {c['name']} ({c['amount_display']})")


if __name__ == "__main__":
    main()
