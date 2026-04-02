import streamlit as st
from utils.db import init, stats, CATS

st.set_page_config(
    page_title="보장 카드뉴스",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="expanded",
)

init()

# ── 사이드바 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ 보장 카드뉴스")
    st.caption("메리츠화재 GA3 보조 도구")
    st.divider()
    st.page_link("pages/1_담보_은행.py",  label="🏦 담보 은행 관리", icon="🏦")
    st.page_link("pages/2_PDF_분석.py",   label="📄 PDF 분석",      icon="📄")

# ── 메인 ──────────────────────────────────────────────────────────────────
st.title("🛡️ 보장 카드뉴스 생성기")
st.markdown("메리츠화재 가입설계서 PDF를 업로드하면 **담보 은행**에서 즉시 매칭해 카드뉴스로 변환합니다.")
st.divider()

# 요약 통계
s = stats()
cols = st.columns(len(CATS) + 1)
cols[0].metric("📦 전체 담보", f"{s['total']}개")
for i, (cat, info) in enumerate(CATS.items()):
    count = s["by_cat"].get(cat, 0)
    cols[i + 1].metric(f"{info['icon']} {info['label']}", f"{count}개")

st.divider()

# 메뉴 카드
c1, c2 = st.columns(2)
with c1:
    st.markdown("""
    ### 🏦 담보 은행 관리
    등록된 담보를 조회·추가·수정·삭제합니다.  
    변경 후 JSON으로 내보내 레포에 반영하면 영구 저장됩니다.
    """)
    if st.button("담보 은행 바로가기 →", use_container_width=True):
        st.switch_page("pages/1_담보_은행.py")

with c2:
    st.markdown("""
    ### 📄 PDF 분석
    가입설계서 PDF를 업로드하면 담보 은행과 즉시 매칭해 카드뉴스를 생성합니다.  
    완성된 카드뉴스는 HTML로 다운로드할 수 있습니다.
    """)
    if st.button("PDF 분석 바로가기 →", use_container_width=True):
        st.switch_page("pages/2_PDF_분석.py")

st.caption("ℹ️ 왼쪽 사이드바의 메뉴를 통해서도 이동할 수 있습니다.")
