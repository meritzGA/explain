import streamlit as st
import streamlit.components.v1 as components
from utils.db import init, CATS, stats
from utils.pdf_parser import extract_text, match_coverages, extract_info, detect_notices
from utils.card_renderer import build_html

st.set_page_config(page_title="PDF 분석", page_icon="📄", layout="centered")

init()

# ── 사이드바 ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ 보장 카드뉴스")
    st.divider()
    st.page_link("app.py",                label="🏠 홈",        icon="🏠")
    st.page_link("pages/1_담보_은행.py",   label="🏦 담보 은행", icon="🏦")
    st.page_link("pages/2_PDF_분석.py",    label="📄 PDF 분석",  icon="📄")
    st.divider()
    s = stats()
    st.caption(f"담보 은행: {s['total']}개 담보 등록됨")

# ── 헤더 ──────────────────────────────────────────────────────────────────
st.title("📄 PDF 분석")
st.caption("가입설계서 PDF를 업로드하면 담보 은행에서 즉시 매칭해 카드뉴스를 생성합니다.")
st.divider()

# ── 업로드 ────────────────────────────────────────────────────────────────
uploaded = st.file_uploader(
    "가입설계서 PDF 업로드",
    type=["pdf"],
    help="메리츠화재 가입설계서 PDF만 지원합니다. 30MB 이하.",
    label_visibility="collapsed",
)

if not uploaded:
    # 업로드 안내
    with st.container(border=True):
        st.markdown("""
        #### 사용 방법
        1. 위 영역에 가입설계서 PDF를 드래그하거나 클릭해서 파일을 선택합니다.
        2. 담보 은행에 등록된 담보와 자동으로 매칭합니다.
        3. 카드뉴스를 확인하고 HTML 파일로 다운로드할 수 있습니다.
        """)
        st.info(f"💡 현재 담보 은행에 **{stats()['total']}개** 담보가 등록되어 있습니다. "
                "[담보 은행 관리](pages/1_담보_은행.py)에서 추가·수정할 수 있습니다.")
    st.stop()

# ── PDF 처리 ──────────────────────────────────────────────────────────────
raw_text = None

with st.spinner("📑 PDF 텍스트 추출 중..."):
    try:
        raw_text = extract_text(uploaded)
    except Exception as e:
        st.error(
            f"**PDF 읽기 오류:** {e}\n\n"
            "회사 사내망 DRM이 걸린 파일은 직접 읽을 수 없습니다. "
            "Excel에서 다시 저장하거나 암호화 해제 후 재저장한 파일을 사용하세요."
        )
        with st.expander("디버그: 원시 오류"):
            st.exception(e)
        st.stop()

with st.spinner("🔍 담보 은행과 매칭 중..."):
    info      = extract_info(raw_text)
    coverages = match_coverages(raw_text)
    notices   = detect_notices(raw_text)

# ── 결과 없음 ─────────────────────────────────────────────────────────────
if not coverages:
    st.warning(
        "담보 정보를 찾을 수 없습니다.\n\n"
        "- 메리츠화재 가입설계서 PDF인지 확인하세요.\n"
        "- 텍스트가 추출되지 않는 스캔 PDF일 수 있습니다.\n"
        "- 새 담보 유형이면 [담보 은행](pages/1_담보_은행.py)에 키워드를 추가하세요."
    )
    with st.expander("추출된 텍스트 미리보기 (디버그)"):
        st.text(raw_text[:3000])
    st.stop()

# ── 결과 요약 ─────────────────────────────────────────────────────────────
st.success(f"✅ **{len(coverages)}개** 담보 매칭 완료")

mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("매칭 담보", f"{len(coverages)}개")
mc2.metric("피보험자", info.get("name") or "—")
mc3.metric("월 보험료", f"{info.get('premium', '')}원" if info.get("premium") else "—")
mc4.metric("보험기간",   info.get("period") or "—")

# 카테고리별 분류 요약
cat_counts: dict[str, int] = {}
for c in coverages:
    cat_counts[c.get("cat", "other")] = cat_counts.get(c.get("cat", "other"), 0) + 1

matched_cats = [(cat, CATS[cat], cnt) for cat, cnt in cat_counts.items() if cat in CATS]
if matched_cats:
    tags_html = " ".join(
        f'<span style="display:inline-block;background:#f0f0eb;'
        f'border-radius:20px;padding:3px 10px;font-size:12px;margin:2px;">'
        f'{info["icon"]} {info["label"]} {cnt}개</span>'
        for cat, info, cnt in matched_cats
    )
    st.markdown(tags_html, unsafe_allow_html=True)

st.divider()

# ── 카드뉴스 ──────────────────────────────────────────────────────────────
html = build_html(info, coverages, notices)

# 높이 동적 계산
num_cats = len(cat_counts)
estimated_h = len(coverages) * 178 + num_cats * 55 + 370
components.html(html, height=estimated_h, scrolling=False)

# ── 다운로드 / 액션 ───────────────────────────────────────────────────────
st.divider()
name = info.get("name") or "고객"
dl_col, txt_col = st.columns([1, 3])
dl_col.download_button(
    label="⬇️ HTML 저장",
    data=html.encode("utf-8"),
    file_name=f"{name}_보장카드뉴스.html",
    mime="text/html",
    use_container_width=True,
    type="primary",
)
txt_col.caption(
    f"저장된 HTML 파일을 브라우저로 열면 동일한 카드뉴스를 볼 수 있습니다.\n"
    f"카톡·슬랙 등으로 파일을 공유하거나 인쇄할 수 있습니다."
)

# 원문 텍스트 (디버그)
with st.expander("🔍 추출된 텍스트 보기 (디버그)"):
    st.text(raw_text[:5000])
    if len(raw_text) > 5000:
        st.caption(f"... (전체 {len(raw_text):,}자 중 5,000자 표시)")
