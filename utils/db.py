"""
담보 은행 데이터 관리
- JSON 파일을 최초 1회 로드 → session_state에 유지
- 모든 CRUD는 session_state["db"] 에 반영
- 변경사항은 JSON 내보내기로 레포에 반영
"""
import json
from pathlib import Path
import streamlit as st

_DB_PATH = Path(__file__).parent.parent / "data" / "coverage_db.json"

CATS: dict = {
    "cancer":       {"label": "암 진단",       "icon": "🎗"},
    "cancer_treat": {"label": "암 치료비",      "icon": "💊"},
    "brain":        {"label": "뇌혈관 질환",   "icon": "🧠"},
    "heart":        {"label": "심장 질환",      "icon": "❤"},
    "surgery":      {"label": "수술비",          "icon": "🏥"},
    "care":         {"label": "간병·입원일당", "icon": "🛏"},
    "other":        {"label": "기타 진단",      "icon": "📋"},
}


# ──────────────────────────────────────────────
# 초기화
# ──────────────────────────────────────────────

def init():
    """세션 스테이트에 DB 초기화 (최초 1회만 파일 로드)"""
    if "db" not in st.session_state:
        with open(_DB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        st.session_state["db"] = data["coverages"]
    # 편집 상태 초기화
    if "edit_idx" not in st.session_state:
        st.session_state["edit_idx"] = -1
    if "show_add" not in st.session_state:
        st.session_state["show_add"] = False


# ──────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────

def get_all() -> list[dict]:
    init()
    return st.session_state["db"]


def get_by_cat(cat: str) -> list[dict]:
    return [c for c in get_all() if c["cat"] == cat]


def search(query: str, cat_filter: str = "") -> list[tuple[int, dict]]:
    """(원본 인덱스, 담보) 튜플 리스트 반환"""
    q = query.strip().lower()
    results = []
    for i, cov in enumerate(get_all()):
        if cat_filter and cov["cat"] != cat_filter:
            continue
        if q:
            searchable = " ".join([
                cov["title"], cov.get("sub", ""), cov.get("desc", ""),
                " ".join(cov.get("kw", [])),
            ]).lower()
            if q not in searchable:
                continue
        results.append((i, cov))
    return results


def stats() -> dict:
    db = get_all()
    counts = {}
    for c in db:
        counts[c["cat"]] = counts.get(c["cat"], 0) + 1
    return {"total": len(db), "by_cat": counts}


# ──────────────────────────────────────────────
# 추가 / 수정 / 삭제
# ──────────────────────────────────────────────

def add(entry: dict):
    init()
    st.session_state["db"].append(entry)


def update(idx: int, entry: dict):
    init()
    st.session_state["db"][idx] = entry


def delete(idx: int):
    init()
    st.session_state["db"].pop(idx)


# ──────────────────────────────────────────────
# 내보내기 / 가져오기
# ──────────────────────────────────────────────

def export_json() -> str:
    data = {"coverages": get_all(), "cats": CATS}
    return json.dumps(data, ensure_ascii=False, indent=2)


def import_json(raw: str):
    data = json.loads(raw)
    if "coverages" in data:
        st.session_state["db"] = data["coverages"]
    elif isinstance(data, list):
        st.session_state["db"] = data
    else:
        raise ValueError("올바른 형식이 아닙니다. {coverages: [...]} 또는 [...] 형식이어야 합니다.")
