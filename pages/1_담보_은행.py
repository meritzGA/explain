import streamlit as st
import re
from utils.db import (
    init, get_all, add, update, delete,
    export_json, import_json, stats, CATS,
)
from utils.pdf_parser import extract_text, extract_all_candidates, find_new_candidates

st.set_page_config(page_title="담보 은행 관리", page_icon="🏦", layout="wide")
init()

# ── 사이드바 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ 보장 카드뉴스")
    st.divider()
    st.page_link("app.py",                label="🏠 홈",        icon="🏠")
    st.page_link("pages/1_담보_은행.py",   label="🏦 담보 은행", icon="🏦")
    st.page_link("pages/2_PDF_분석.py",    label="📄 PDF 분석",  icon="📄")
    st.divider()
    st.download_button(
        "⬇️ JSON 내보내기",
        data=export_json(),
        file_name="coverage_db.json",
        mime="application/json",
        use_container_width=True,
        help="현재 담보 은행을 JSON으로 다운로드. 레포에 커밋하면 영구 저장됩니다.",
    )
    uj = st.file_uploader("⬆️ JSON 가져오기", type=["json"])
    if uj:
        try:
            import_json(uj.read().decode("utf-8"))
            st.success("✅ JSON 가져오기 완료!")
            st.rerun()
        except Exception as e:
            st.error(f"오류: {e}")

# ── 헤더 & 통계 ───────────────────────────────────────────────────────────
st.title("🏦 담보 은행 관리")
s = stats()
cols = st.columns(len(CATS) + 1)
cols[0].metric("전체", f"{s['total']}개")
for i, (cat, info) in enumerate(CATS.items()):
    cols[i + 1].metric(f"{info['icon']} {info['label']}", f"{s['by_cat'].get(cat, 0)}개")

st.divider()

# ── 탭 ────────────────────────────────────────────────────────────────────
tab_pdf, tab_list = st.tabs(["📄 PDF로 담보 추가", "📋 담보 목록 관리"])


# ══════════════════════════════════════════════════════════════════════════
# TAB 1 : PDF로 담보 추가
# ══════════════════════════════════════════════════════════════════════════
with tab_pdf:
    st.markdown("가입설계서 PDF를 업로드하면 담보 은행에 없는 담보를 자동으로 찾아냅니다.")
    st.caption("✔ 이미 등록된 담보는 자동으로 제외되고, 새 담보만 추가 후보로 표시됩니다.")

    # ── 파일 업로드 ────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        "가입설계서 PDF 업로드",
        type=["pdf"],
        label_visibility="collapsed",
        key="bank_pdf_upload",
    )

    if not uploaded:
        st.info("PDF를 업로드하면 담보 은행과 비교해 새 담보 후보를 보여줍니다.")
        st.stop()

    # ── 처리 ───────────────────────────────────────────────────────────────
    # 파일이 바뀌면 캐시 초기화
    file_key = f"{uploaded.name}_{uploaded.size}"
    if st.session_state.get("_bank_file_key") != file_key:
        st.session_state["_bank_file_key"] = file_key
        st.session_state.pop("_bank_candidates", None)

    if "_bank_candidates" not in st.session_state:
        with st.spinner("PDF 분석 중..."):
            try:
                raw_text = extract_text(uploaded)
                all_cands = extract_all_candidates(raw_text)
                existing, new_cands = find_new_candidates(all_cands)
                st.session_state["_bank_candidates"] = {
                    "all": all_cands,
                    "existing": existing,
                    "new": new_cands,
                }
            except Exception as e:
                st.error(f"PDF 읽기 오류: {e}")
                st.stop()

    cdata = st.session_state["_bank_candidates"]
    existing = cdata["existing"]
    new_cands = cdata["new"]

    # ── 요약 ───────────────────────────────────────────────────────────────
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("PDF에서 추출된 담보", f"{len(cdata['all'])}개")
    sc2.metric("✅ 이미 등록된 담보",  f"{len(existing)}개",  delta_color="off")
    sc3.metric("🆕 새 담보 후보",      f"{len(new_cands)}개",
               delta=f"+{len(new_cands)}" if new_cands else "없음")

    # ── 이미 등록된 담보 (접혀 있음) ────────────────────────────────────────
    if existing:
        with st.expander(f"✅ 이미 등록된 담보 {len(existing)}개", expanded=False):
            for c in existing:
                st.markdown(f"- `{c['num']}` {c['title']}")

    st.divider()

    # ── 새 담보 후보 ────────────────────────────────────────────────────────
    if not new_cands:
        st.success("🎉 모든 담보가 이미 담보 은행에 등록되어 있습니다!")
        st.stop()

    st.markdown(f"### 🆕 새 담보 후보 {len(new_cands)}개")
    st.caption("추가할 담보를 선택하고 내용을 검토한 후 '선택한 담보 추가' 버튼을 누르세요.")

    # 체크박스 상태 초기화
    if "bank_checks" not in st.session_state:
        st.session_state["bank_checks"] = {}

    # 전체 선택/해제
    sel_col, _ = st.columns([2, 5])
    if sel_col.button("☑️ 전체 선택", use_container_width=True):
        for i in range(len(new_cands)):
            st.session_state["bank_checks"][i] = True
        st.rerun()

    # ── 후보 카드 ────────────────────────────────────────────────────────────
    for idx, cand in enumerate(new_cands):
        with st.container(border=True):
            hc1, hc2 = st.columns([1, 9])

            checked = hc1.checkbox(
                "선택",
                value=st.session_state["bank_checks"].get(idx, True),
                key=f"chk_{idx}",
                label_visibility="collapsed",
            )
            st.session_state["bank_checks"][idx] = checked

            with hc2:
                cc1, cc2 = st.columns([5, 2])
                with cc1:
                    st.markdown(f"**{cand['title']}**")
                    st.caption(f"PDF 원문: `{cand['raw'][:60]}`")
                with cc2:
                    st.markdown(
                        f"<span style='background:#E0F2FE;color:#075985;"
                        f"padding:2px 10px;border-radius:20px;font-size:12px;font-weight:600'>"
                        f"{cand['amount'] or '금액 미확인'}</span>",
                        unsafe_allow_html=True,
                    )

            with st.expander("✏️ 추가 전 내용 수정", expanded=False):
                ea, eb = st.columns(2)
                new_title = ea.text_input(
                    "담보명", value=cand["title"], key=f"t_{idx}",
                )
                new_cat = eb.selectbox(
                    "카테고리", list(CATS.keys()),
                    index=list(CATS.keys()).index(cand["cat"]) if cand["cat"] in CATS else 0,
                    format_func=lambda x: f"{CATS[x]['icon']} {CATS[x]['label']}",
                    key=f"cat_{idx}",
                )
                new_kw = st.text_input(
                    "검색 키워드",
                    value=cand["kw"],
                    key=f"kw_{idx}",
                    help="공백 없이 입력. 이 문자열이 PDF 텍스트에서 검색됩니다.",
                )
                new_desc = st.text_area(
                    "설명 (비워두면 나중에 수정 가능)",
                    value="",
                    key=f"desc_{idx}",
                    height=68,
                    placeholder="고객에게 표시할 보장 설명을 입력하세요.",
                )
                # 수정값 저장
                st.session_state[f"edit_{idx}"] = {
                    "title": new_title,
                    "cat":   new_cat,
                    "kw":    new_kw,
                    "desc":  new_desc,
                }

    st.divider()

    # ── 추가 버튼 ───────────────────────────────────────────────────────────
    selected_indices = [i for i in range(len(new_cands))
                        if st.session_state["bank_checks"].get(i, True)]

    btn_label = f"✅ 선택한 담보 {len(selected_indices)}개 추가"
    if st.button(btn_label, type="primary", use_container_width=True,
                 disabled=len(selected_indices) == 0):
        added = 0
        for i in selected_indices:
            cand = new_cands[i]
            overrides = st.session_state.get(f"edit_{i}", {})
            title = overrides.get("title") or cand["title"]
            cat   = overrides.get("cat")   or cand["cat"]
            kw    = overrides.get("kw")    or cand["kw"]
            desc  = overrides.get("desc",  "")

            if not title or not kw:
                continue

            add({
                "cat":   cat,
                "title": title,
                "sub":   "",
                "kw":    [kw],
                "desc":  desc or f"{title}으로 진단확정 또는 치료 시 지급합니다.",
                "warns": [],
                "info":  [],
            })
            added += 1

        # 상태 초기화
        st.session_state.pop("_bank_candidates", None)
        st.session_state.pop("bank_checks", None)
        for i in range(len(new_cands)):
            for k in [f"chk_{i}", f"t_{i}", f"cat_{i}", f"kw_{i}", f"desc_{i}", f"edit_{i}"]:
                st.session_state.pop(k, None)

        st.success(f"✅ {added}개 담보를 추가했습니다! 사이드바에서 JSON으로 내보내 레포에 반영하세요.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# TAB 2 : 담보 목록 관리
# ══════════════════════════════════════════════════════════════════════════
with tab_list:
    # ── 도구 모음 ─────────────────────────────────────────────────────────
    tc1, tc2, tc3 = st.columns([4, 2, 1.5])
    with tc1:
        q = st.text_input("🔍 검색", placeholder="담보명, 키워드...", label_visibility="collapsed")
    with tc2:
        cat_opts = {"": "전체 카테고리"} | {k: f"{v['icon']} {v['label']}" for k, v in CATS.items()}
        cat_sel = st.selectbox("카테고리", list(cat_opts.keys()),
                               format_func=lambda x: cat_opts[x], label_visibility="collapsed")
    with tc3:
        if st.button("➕ 직접 추가", use_container_width=True, type="primary"):
            st.session_state["list_show_add"] = not st.session_state.get("list_show_add", False)
            st.session_state["list_edit_idx"] = -1

    # ── 직접 추가 폼 ───────────────────────────────────────────────────────
    if st.session_state.get("list_show_add", False):
        with st.container(border=True):
            st.markdown("#### ➕ 직접 추가")
            with st.form("add_form", clear_on_submit=True):
                fa, fb = st.columns(2)
                t_  = fa.text_input("담보명 *")
                sb_ = fb.text_input("부제목 (태그)", placeholder="예) 유사암 제외")
                c_  = fa.selectbox("카테고리 *", list(CATS.keys()),
                                   format_func=lambda x: f"{CATS[x]['icon']} {CATS[x]['label']}")
                k_  = fb.text_area("검색 키워드 * (한 줄에 하나씩)", height=80)
                d_  = st.text_area("보장 설명 *", height=70)
                wa, wi = st.columns(2)
                w_ = wa.text_area("주의사항 (한 줄에 하나씩)", height=65)
                i_ = wi.text_area("안내사항 (한 줄에 하나씩)", height=65)
                if st.form_submit_button("저장", use_container_width=True, type="primary"):
                    if not t_ or not k_ or not d_:
                        st.error("담보명, 키워드, 설명은 필수입니다.")
                    else:
                        add({"cat": c_, "title": t_, "sub": sb_,
                             "kw":  [x.strip() for x in k_.splitlines() if x.strip()],
                             "desc": d_,
                             "warns": [x.strip() for x in w_.splitlines() if x.strip()],
                             "info":  [x.strip() for x in i_.splitlines() if x.strip()]})
                        st.session_state["list_show_add"] = False
                        st.success("✅ 추가 완료!")
                        st.rerun()

    # ── 담보 목록 ─────────────────────────────────────────────────────────
    from utils.db import search as db_search
    results = db_search(q or "", cat_sel)

    if not results:
        st.info("검색 결과가 없습니다.")
        st.stop()

    st.markdown(f"**{len(results)}개** 담보")

    for orig_idx, cov in results:
        cat = cov.get("cat", "other")
        cat_info = CATS.get(cat, {"label": cat, "icon": "📋"})
        with st.container(border=True):
            hc1, hc2, hc3 = st.columns([6, 1, 1])
            with hc1:
                st.markdown(
                    f"**{cov['title']}**"
                    + (f"  <span style='font-size:11px;color:#6b7280'> — {cov['sub']}</span>"
                       if cov.get("sub") else ""),
                    unsafe_allow_html=True,
                )
                st.caption(f"{cat_info['icon']} {cat_info['label']}")
            with hc2:
                if st.button("✏️", key=f"e_{orig_idx}", use_container_width=True, help="수정"):
                    cur = st.session_state.get("list_edit_idx", -1)
                    st.session_state["list_edit_idx"] = -1 if cur == orig_idx else orig_idx
                    st.session_state["list_show_add"] = False
                    st.rerun()
            with hc3:
                if st.button("🗑️", key=f"d_{orig_idx}", use_container_width=True, help="삭제"):
                    st.session_state[f"del_c_{orig_idx}"] = True
                    st.rerun()

            # 삭제 확인
            if st.session_state.get(f"del_c_{orig_idx}"):
                st.warning(f"**'{cov['title']}'** 삭제하시겠습니까?")
                dc1, dc2, _ = st.columns([1, 1, 4])
                if dc1.button("삭제 확인", key=f"dok_{orig_idx}", type="primary"):
                    delete(orig_idx)
                    st.session_state.pop(f"del_c_{orig_idx}", None)
                    st.success("삭제 완료!")
                    st.rerun()
                if dc2.button("취소", key=f"dno_{orig_idx}"):
                    st.session_state.pop(f"del_c_{orig_idx}", None)
                    st.rerun()

            # 상세
            with st.expander("상세 보기"):
                da, db_ = st.columns(2)
                da.markdown("**설명**")
                da.write(cov.get("desc", "—"))
                da.markdown("**키워드**")
                for kw in cov.get("kw", []):
                    da.code(kw, language=None)
                db_.markdown("**주의사항 ⚠**")
                for w in cov.get("warns", []) or ["없음"]:
                    db_.markdown(f"- {w}")
                db_.markdown("**안내사항**")
                for ii in cov.get("info", []) or ["없음"]:
                    db_.markdown(f"- {ii}")

            # 수정 폼
            if st.session_state.get("list_edit_idx") == orig_idx:
                with st.form(f"ef_{orig_idx}"):
                    ea, eb = st.columns(2)
                    nt = ea.text_input("담보명", value=cov["title"])
                    ns = eb.text_input("부제목", value=cov.get("sub", ""))
                    nc = ea.selectbox("카테고리", list(CATS.keys()),
                                      index=list(CATS.keys()).index(cat) if cat in CATS else 0,
                                      format_func=lambda x: f"{CATS[x]['icon']} {CATS[x]['label']}")
                    nk = eb.text_area("키워드", value="\n".join(cov.get("kw", [])), height=80)
                    nd = st.text_area("설명", value=cov.get("desc", ""), height=70)
                    wa_, wi_ = st.columns(2)
                    nw = wa_.text_area("주의사항", value="\n".join(cov.get("warns", [])), height=65)
                    ni = wi_.text_area("안내사항", value="\n".join(cov.get("info", [])), height=65)
                    sb1, sb2 = st.columns(2)
                    if sb1.form_submit_button("💾 저장", use_container_width=True, type="primary"):
                        if not nt or not nk or not nd:
                            st.error("담보명, 키워드, 설명은 필수입니다.")
                        else:
                            update(orig_idx, {
                                "cat": nc, "title": nt, "sub": ns,
                                "kw":  [x.strip() for x in nk.splitlines() if x.strip()],
                                "desc": nd,
                                "warns": [x.strip() for x in nw.splitlines() if x.strip()],
                                "info":  [x.strip() for x in ni.splitlines() if x.strip()],
                            })
                            st.session_state["list_edit_idx"] = -1
                            st.success("✅ 수정 완료!")
                            st.rerun()
                    if sb2.form_submit_button("취소", use_container_width=True):
                        st.session_state["list_edit_idx"] = -1
                        st.rerun()
