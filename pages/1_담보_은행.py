import streamlit as st
import json
from utils.db import (
    init, get_all, search, add, update, delete,
    export_json, import_json, stats, CATS,
)

st.set_page_config(page_title="담보 은행 관리", page_icon="🏦", layout="wide")

init()

# ── 사이드바 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ 보장 카드뉴스")
    st.divider()
    st.page_link("app.py",                label="🏠 홈",         icon="🏠")
    st.page_link("pages/1_담보_은행.py",   label="🏦 담보 은행",  icon="🏦")
    st.page_link("pages/2_PDF_분석.py",    label="📄 PDF 분석",   icon="📄")
    st.divider()

    # JSON 내보내기 / 가져오기
    st.markdown("**JSON 관리**")
    st.download_button(
        "⬇️ JSON 내보내기",
        data=export_json(),
        file_name="coverage_db.json",
        mime="application/json",
        use_container_width=True,
        help="현재 담보 은행을 JSON으로 다운로드. 레포에 넣으면 영구 저장됩니다.",
    )
    uploaded_json = st.file_uploader(
        "⬆️ JSON 가져오기", type=["json"],
        help="수정한 JSON 파일을 업로드하면 담보 은행을 교체합니다.",
    )
    if uploaded_json:
        try:
            import_json(uploaded_json.read().decode("utf-8"))
            st.success("✅ JSON 가져오기 완료!")
            st.rerun()
        except Exception as e:
            st.error(f"오류: {e}")

# ── 헤더 ──────────────────────────────────────────────────────────────────
st.title("🏦 담보 은행 관리")
st.caption("담보를 추가·수정·삭제할 수 있습니다. 변경 후 사이드바에서 JSON으로 내보내세요.")

# ── 통계 ──────────────────────────────────────────────────────────────────
s = stats()
cols = st.columns(len(CATS) + 1)
cols[0].metric("전체 담보", f"{s['total']}개")
for i, (cat, info) in enumerate(CATS.items()):
    cols[i + 1].metric(f"{info['icon']} {info['label']}", f"{s['by_cat'].get(cat, 0)}개")

st.divider()

# ── 도구 모음 ─────────────────────────────────────────────────────────────
tc1, tc2, tc3 = st.columns([4, 2, 1.4])
with tc1:
    q = st.text_input("🔍 담보명 / 키워드 검색", placeholder="예) 암진단비, 간병인, 뇌혈관...",
                      label_visibility="collapsed")
with tc2:
    cat_opts = {"": "전체 카테고리"} | {k: f"{v['icon']} {v['label']}" for k, v in CATS.items()}
    cat_sel = st.selectbox("카테고리", list(cat_opts.keys()),
                           format_func=lambda x: cat_opts[x],
                           label_visibility="collapsed")
with tc3:
    if st.button("➕ 새 담보 추가", use_container_width=True, type="primary"):
        st.session_state["show_add"] = not st.session_state.get("show_add", False)
        st.session_state["edit_idx"] = -1

# ── 새 담보 추가 폼 ────────────────────────────────────────────────────────
if st.session_state.get("show_add", False):
    with st.container(border=True):
        st.markdown("#### ➕ 새 담보 추가")
        _add_form()

def _add_form():
    with st.form("add_form", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        title  = fc1.text_input("담보명 *", placeholder="예) 암 진단비")
        sub    = fc2.text_input("부제목 (태그)", placeholder="예) 유사암 제외")
        cat    = fc1.selectbox("카테고리 *", list(CATS.keys()),
                               format_func=lambda x: f"{CATS[x]['icon']} {CATS[x]['label']}")
        kw_raw = fc2.text_area("검색 키워드 * (한 줄에 하나씩)",
                               placeholder="암진단비(유사암제외)\n암진단및치료비[암진단비(유사암제외)]",
                               height=80)
        desc   = st.text_area("보장 설명 *", height=80,
                              placeholder="고객에게 표시할 설명 문장.")
        wc1, wc2 = st.columns(2)
        warns_raw = wc1.text_area("주의사항 (한 줄에 하나씩, 주황 태그)",
                                  placeholder="90일 면책\n소액암 1년미만 50%", height=70)
        info_raw  = wc2.text_area("안내사항 (한 줄에 하나씩, 회색 태그)",
                                  placeholder="최초 1회 지급\n갱신형", height=70)
        submitted = st.form_submit_button("저장", use_container_width=True, type="primary")
        if submitted:
            if not title or not kw_raw or not desc:
                st.error("담보명, 키워드, 설명은 필수 항목입니다.")
            else:
                kws = [k.strip() for k in kw_raw.splitlines() if k.strip()]
                ws  = [w.strip() for w in warns_raw.splitlines() if w.strip()]
                ins = [i.strip() for i in info_raw.splitlines()  if i.strip()]
                add({"cat": cat, "title": title, "sub": sub, "kw": kws,
                     "desc": desc, "warns": ws, "info": ins})
                st.session_state["show_add"] = False
                st.success(f"✅ '{title}' 추가 완료!")
                st.rerun()

# 폼 함수를 선언 후 조건부 실행
if st.session_state.get("show_add", False):
    with st.container(border=True):
        st.markdown("#### ➕ 새 담보 추가")
        _add_form()

st.divider()

# ── 담보 목록 ─────────────────────────────────────────────────────────────
results = search(q or "", cat_sel)

if not results:
    st.info("검색 결과가 없습니다.")
    st.stop()

st.markdown(f"**{len(results)}개** 담보")

for orig_idx, cov in results:
    cat  = cov.get("cat", "other")
    cat_info = CATS.get(cat, {"label": cat, "icon": "📋"})

    with st.container(border=True):
        hc1, hc2, hc3 = st.columns([6, 1, 1])

        with hc1:
            st.markdown(
                f"**{cov['title']}**"
                + (f"  <span style='font-size:11px;color:#6b7280'>— {cov['sub']}</span>" if cov.get("sub") else ""),
                unsafe_allow_html=True,
            )
            st.caption(f"{cat_info['icon']} {cat_info['label']}")

        with hc2:
            if st.button("✏️ 수정", key=f"edit_{orig_idx}", use_container_width=True):
                # 토글
                if st.session_state.get("edit_idx") == orig_idx:
                    st.session_state["edit_idx"] = -1
                else:
                    st.session_state["edit_idx"] = orig_idx
                    st.session_state["show_add"] = False
                st.rerun()

        with hc3:
            if st.button("🗑️ 삭제", key=f"del_{orig_idx}", use_container_width=True):
                st.session_state[f"del_confirm_{orig_idx}"] = True
                st.rerun()

        # 삭제 확인
        if st.session_state.get(f"del_confirm_{orig_idx}"):
            st.warning(f"**'{cov['title']}'** 을(를) 삭제하시겠습니까?")
            dc1, dc2, _ = st.columns([1, 1, 4])
            if dc1.button("삭제 확인", key=f"delok_{orig_idx}", type="primary"):
                delete(orig_idx)
                st.session_state.pop(f"del_confirm_{orig_idx}", None)
                st.success("삭제 완료!")
                st.rerun()
            if dc2.button("취소", key=f"delno_{orig_idx}"):
                st.session_state.pop(f"del_confirm_{orig_idx}", None)
                st.rerun()

        # 상세 정보 (항상 표시)
        with st.expander("상세 보기"):
            dc1, dc2 = st.columns(2)
            dc1.markdown("**설명**")
            dc1.write(cov.get("desc", "—"))
            dc1.markdown("**검색 키워드**")
            for kw in cov.get("kw", []):
                dc1.code(kw, language=None)
            dc2.markdown("**주의사항 (⚠ 주황)**")
            for w in cov.get("warns", []):
                dc2.markdown(f"- {w}")
            if not cov.get("warns"):
                dc2.caption("없음")
            dc2.markdown("**안내사항 (회색)**")
            for i in cov.get("info", []):
                dc2.markdown(f"- {i}")
            if not cov.get("info"):
                dc2.caption("없음")

        # ── 수정 폼 ───────────────────────────────────────────────────────
        if st.session_state.get("edit_idx") == orig_idx:
            with st.form(f"edit_form_{orig_idx}"):
                st.markdown("**✏️ 담보 수정**")
                ec1, ec2 = st.columns(2)
                new_title = ec1.text_input("담보명", value=cov["title"])
                new_sub   = ec2.text_input("부제목", value=cov.get("sub", ""))
                new_cat   = ec1.selectbox(
                    "카테고리", list(CATS.keys()),
                    index=list(CATS.keys()).index(cat) if cat in CATS else 0,
                    format_func=lambda x: f"{CATS[x]['icon']} {CATS[x]['label']}",
                )
                new_kw_raw = ec2.text_area(
                    "키워드 (한 줄에 하나씩)",
                    value="\n".join(cov.get("kw", [])), height=90,
                )
                new_desc = st.text_area("설명", value=cov.get("desc", ""), height=80)
                wc1, wc2 = st.columns(2)
                new_w_raw = wc1.text_area(
                    "주의사항", value="\n".join(cov.get("warns", [])), height=70,
                )
                new_i_raw = wc2.text_area(
                    "안내사항", value="\n".join(cov.get("info", [])), height=70,
                )
                sb1, sb2 = st.columns(2)
                if sb1.form_submit_button("💾 저장", use_container_width=True, type="primary"):
                    if not new_title or not new_kw_raw or not new_desc:
                        st.error("담보명, 키워드, 설명은 필수입니다.")
                    else:
                        update(orig_idx, {
                            "cat": new_cat, "title": new_title, "sub": new_sub,
                            "kw":  [k.strip() for k in new_kw_raw.splitlines() if k.strip()],
                            "desc": new_desc,
                            "warns": [w.strip() for w in new_w_raw.splitlines() if w.strip()],
                            "info":  [i.strip() for i in new_i_raw.splitlines() if i.strip()],
                        })
                        st.session_state["edit_idx"] = -1
                        st.success("✅ 수정 완료!")
                        st.rerun()
                if sb2.form_submit_button("취소", use_container_width=True):
                    st.session_state["edit_idx"] = -1
                    st.rerun()
