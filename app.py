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
def load_events_config() -> dict:
    with open(_find_asset_dir("config") / "events.json", encoding="utf-8") as f:
        return json.load(f)

@st.cache_resource
def load_treatments_config() -> dict:
    with open(_find_asset_dir("config") / "treatments.json", encoding="utf-8") as f:
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
        page_title="암 치료비 보장금액 분석",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # ─────────────────────────────────────────────────────────────
    # 전역 스타일: Pretendard + Hero 헤더 + 파일 업로더 재디자인
    # ─────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
      @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

      :root {
        --font-sans: 'Pretendard Variable', Pretendard,
                     -apple-system, BlinkMacSystemFont, system-ui,
                     'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
        --red: #E53935;
        --red-hl: #FECDD3;
        --red-soft: #FEE8EC;
        --red-border: #FCD4D4;
        --ink: #1F1F1F;
        --muted: #6A6A6A;
        --bg: #F5F5F5;
      }

      /* ── 폰트 전역 적용 ── */
      html, body, [class*="st-"], [class*="css-"],
      [data-testid="stAppViewContainer"] *,
      button, input, textarea, select {
        font-family: var(--font-sans) !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        text-rendering: optimizeLegibility;
        font-feature-settings: 'tnum' on, 'lnum' on;
      }

      /* ── 기본 레이아웃 ── */
      .stApp { background: var(--bg); }
      [data-testid="stHeader"] { background: transparent; }
      .block-container {
        padding-top: 3rem !important;
        padding-bottom: 3rem !important;
        max-width: 1160px !important;
      }

      /* ── Hero 헤더 ── */
      .hero-wrap { text-align: center; margin-bottom: 36px; }

      .hero-badge {
        display: inline-flex; align-items: center; gap: 7px;
        background: #FFFFFF;
        border: 1.5px solid var(--red);
        color: var(--red);
        font-size: 13px; font-weight: 600;
        padding: 7px 18px;
        border-radius: 999px;
        margin-bottom: 22px;
        letter-spacing: -0.01em;
      }
      .hero-badge::before {
        content: '';
        width: 13px; height: 13px;
        border: 1.5px solid var(--red);
        border-radius: 50%;
        background: radial-gradient(circle, var(--red) 0 35%, transparent 36%);
      }

      .hero-title {
        font-size: 60px; font-weight: 800;
        letter-spacing: -0.045em; line-height: 1.15;
        color: var(--ink); margin: 0 0 18px 0;
      }
      .hero-title .hl {
        color: var(--red);
        background: linear-gradient(transparent 55%, var(--red-hl) 55%, var(--red-hl) 92%, transparent 92%);
        padding: 0 6px;
      }

      .hero-subtitle {
        font-size: 16px; color: var(--muted);
        line-height: 1.75; margin: 0; font-weight: 500;
        letter-spacing: -0.015em;
      }
      .hero-subtitle b { color: var(--ink); font-weight: 700; }

      /* ── 파일 업로더: 전면 재디자인 ── */
      [data-testid="stFileUploader"] label { display: none !important; }
      [data-testid="stFileUploader"] section { padding: 0 !important; }

      /* 드롭존 본체 — 큰 점선 카드. 내부는 건드리지 않고 배경+오버레이로만 표현 */
      [data-testid="stFileUploaderDropzone"] {
        position: relative !important;
        background-color: #FFFFFF !important;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='76' height='76' viewBox='0 0 76 76' fill='none'><rect width='76' height='76' rx='18' fill='%23FEE8EC'/><path d='M25 48v4a2 2 0 0 0 2 2h22a2 2 0 0 0 2-2v-4' stroke='%23E53935' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/><path d='M38 44V26M31 33l7-7 7 7' stroke='%23E53935' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/></svg>") !important;
        background-repeat: no-repeat !important;
        background-position: center 60px !important;
        border: 2px dashed var(--red-border) !important;
        border-radius: 24px !important;
        min-height: 340px !important;
        cursor: pointer !important;
        transition: all 0.2s ease !important;
      }
      [data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--red) !important;
        background-color: #FFFAFA !important;
      }

      /* 드롭존 내부 기본 UI(아이콘/문구/Browse 버튼)를 모조리 투명화.
         opacity: 0은 클릭·드래그 이벤트는 정상 수신되므로 기능은 유지됨. */
      [data-testid="stFileUploaderDropzone"] > *,
      [data-testid="stFileUploaderDropzone"] > * * {
        opacity: 0 !important;
      }

      /* 커스텀 2줄 안내 — absolute 포지셔닝으로 오버레이 */
      [data-testid="stFileUploaderDropzone"]::before {
        content: '제안서 파일을 이곳에 놓아주세요';
        position: absolute;
        top: 160px; left: 0; right: 0;
        text-align: center;
        font-size: 19px; font-weight: 700;
        color: var(--ink);
        letter-spacing: -0.025em;
        pointer-events: none;
        opacity: 1 !important;
        z-index: 1;
      }
      [data-testid="stFileUploaderDropzone"]::after {
        content: 'PDF 파일을 드래그하거나 클릭하여 시작하세요';
        position: absolute;
        top: 196px; left: 0; right: 0;
        text-align: center;
        font-size: 14px; font-weight: 500;
        color: #8A8A8A;
        letter-spacing: -0.01em;
        pointer-events: none;
        opacity: 1 !important;
        z-index: 1;
      }

      /* ── 업로드 후 파일 칩 ── */
      [data-testid="stFileUploaderFile"] {
        background: #FFFFFF !important;
        border: 1px solid #E8E8E8 !important;
        border-radius: 14px !important;
        padding: 16px 22px !important;
        margin-top: 0 !important;
        align-items: center !important;
      }
      [data-testid="stFileUploaderFile"] [data-testid="stFileUploaderFileName"] {
        font-size: 15px; font-weight: 600; color: var(--ink);
        letter-spacing: -0.015em;
      }

      /* 삭제(X) 버튼을 "파일 취소 하기" 라벨로 교체 */
      [data-testid="stFileUploaderDeleteBtn"] {
        background: #F5F5F5 !important;
        border: 1px solid #E0E0E0 !important;
        border-radius: 999px !important;
        padding: 9px 18px !important;
        color: var(--muted) !important;
      }
      [data-testid="stFileUploaderDeleteBtn"] svg { display: none !important; }
      [data-testid="stFileUploaderDeleteBtn"]::after {
        content: '파일 취소 하기';
        font-size: 13px; font-weight: 500;
        letter-spacing: -0.01em;
      }

      /* ── 하단 안내문 ── */
      .hero-footnote {
        text-align: center;
        font-size: 12px; color: #9A9A9A;
        margin-top: 24px;
        letter-spacing: -0.01em;
      }

      /* ── 헤딩 선명도 ── */
      h1, h2, h3 { font-weight: 700 !important; letter-spacing: -0.025em; }

      /* ── 반응형 ── */
      @media (max-width: 768px) {
        .hero-title { font-size: 40px; }
        [data-testid="stFileUploaderDropzone"] {
          min-height: 280px !important;
          background-position: center 44px !important;
        }
        [data-testid="stFileUploaderDropzone"]::before {
          top: 136px;
          font-size: 17px;
        }
        [data-testid="stFileUploaderDropzone"]::after {
          top: 168px;
          font-size: 13px;
        }
      }
    </style>
    """, unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────
    # Hero 헤더
    # ─────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="hero-wrap">
      <div class="hero-badge">메리츠화재 "비공식" 매니저 분석지원</div>
      <h1 class="hero-title"><span class="hl">암 치료비</span> 보장금액 분석</h1>
      <p class="hero-subtitle">
        가입제안서 PDF를 업로드하면,<br>
        보장내역 중 <b>암 치료비 파트만</b> 추출 합니다
      </p>
    </div>
    """, unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "가입제안서 PDF를 업로드하세요",
        type="pdf",
        label_visibility="collapsed",
    )

    if not uploaded:
        st.markdown(
            '<p class="hero-footnote">'
            '* 가입제안서안에 있는 담보 가입금액을 꼭 계산해보고 참고용으로만 사용하세요'
            '</p>',
            unsafe_allow_html=True,
        )
        return

    pdf_bytes = uploaded.read()

    # ── 업로드 후: 드롭존을 축소하여 "다른 제안서" 업로드 가능하게 유지 ──
    st.markdown("""
    <style>
      [data-testid="stFileUploaderDropzone"] {
        min-height: 0 !important;
        max-height: 56px !important;
        padding: 0 24px !important;
        overflow: hidden !important;
        background-image: none !important;
        border: 1px solid #E0E0E0 !important;
        border-radius: 14px !important;
        border-style: solid !important;
        cursor: pointer !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
      }
      [data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--red) !important;
        background-color: #FFFAFA !important;
      }
      [data-testid="stFileUploaderDropzone"] > *,
      [data-testid="stFileUploaderDropzone"] > * * {
        opacity: 0 !important;
      }
      [data-testid="stFileUploaderDropzone"]::before {
        content: '다른 제안서 분석하기';
        position: absolute;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        font-size: 14px; font-weight: 600;
        color: var(--muted);
        letter-spacing: -0.015em;
        pointer-events: none;
        opacity: 1 !important;
        z-index: 1;
      }
      [data-testid="stFileUploaderDropzone"]::after {
        display: none !important;
      }
    </style>
    """, unsafe_allow_html=True)

    with st.spinner("분석 중..."):
        processed = process_pdf(pdf_bytes)
        processed["source_filename"] = uploaded.name
        kb = len(pdf_bytes) / 1024
        processed["source_filesize"] = f"{kb:,.1f} KB"
        html = render_html(processed)

    # 인라인 렌더
    st.components.v1.html(html, height=2400, scrolling=True)


if __name__ == "__main__":
    main()
