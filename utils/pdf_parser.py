"""PDF 텍스트 추출 및 담보 은행 매칭"""
import re
import pdfplumber
from utils.db import get_all


def extract_text(file) -> str:
    """pdfplumber로 PDF 전 페이지 텍스트 추출"""
    pages = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    if not pages:
        raise ValueError("텍스트를 추출할 수 없습니다. DRM이 걸린 파일일 수 있습니다.")
    return "\n".join(pages)


def _norm(text: str) -> str:
    """공백 제거 — 키워드 매칭용"""
    return re.sub(r"\s+", "", text)


def _find_amount(text: str, start: int) -> str | None:
    """키워드 위치 이후 ~400자 내 한국식 금액 추출"""
    window = text[start: start + 400]
    m = re.search(r"(\d+(?:\.\d+)?)(억|천만|백만|만)(원)", window)
    return m.group(0) if m else None


def extract_info(text: str) -> dict:
    """고객명 / 월보험료 / 상품명 / 보험기간 / 컨설턴트 추출"""
    flat = re.sub(r"\s+", " ", text)

    # 피보험자명
    name = ""
    for pat in [r"피보험자\s*([가-힣]{2,5})\s*[（(]",
                r"계약자\s*([가-힣]{2,5})\s*[（(]",
                r"([가-힣]{2,5})\s*고객님을"]:
        m = re.search(pat, flat)
        if m:
            name = m.group(1)
            break

    # 월 보험료
    premium = ""
    for pat in [r"1회차보험료\(할인후\)\s*([\d,]+)\s*원",
                r"보험료\s+([\d,]+)\s*원",
                r"([\d,]+)\s*원\s*보장보험료"]:
        m = re.search(pat, flat)
        if m:
            premium = m.group(1)
            break

    # 상품명
    product = ""
    m = re.search(r"\(무\)[^\n\r]{4,90}", flat)
    if m:
        product = m.group(0).strip()

    # 보험기간
    period = ""
    m = re.search(r"(\d+년납\s*\d+년만기|\d+년납\s*\d+세만기)", text)
    if m:
        period = re.sub(r"\s+", " ", m.group(1))

    # 컨설턴트
    consultant = ""
    m = re.search(r"컨설턴트\s*(.{3,30}?)\s*(?:휴대전화|전화번호|\|)", flat)
    if m:
        consultant = m.group(1).strip()

    return dict(name=name, premium=premium, product=product,
                period=period, consultant=consultant)


def match_coverages(text: str) -> list[dict]:
    """담보 은행과 텍스트 매칭 → 매칭된 담보 리스트"""
    db = get_all()
    norm_text = _norm(text)
    results = []
    seen = set()

    for entry in db:
        title = entry["title"]
        if title in seen:
            continue
        for kw in entry.get("kw", []):
            if _norm(kw) not in norm_text:
                continue
            # 원문에서 금액 검색
            amount = None
            raw_pos = text.find(kw)
            if raw_pos != -1:
                amount = _find_amount(text, raw_pos)
            if not amount:
                pos = norm_text.find(_norm(kw))
                amount = _find_amount(norm_text, pos)

            results.append({**entry, "amount": amount or "약관 참조"})
            seen.add(title)
            break

    return results


def detect_notices(text: str) -> list[str]:
    """주의사항 자동 감지"""
    notices = []
    if re.search(r"간편심사", text) and re.search(r"3\.10\.5|통합간편심사|맞춤간편심사", text):
        notices.append("이 상품은 <b>간편심사형(유병자보험)</b>으로 일반보험보다 보험료가 높을 수 있습니다.")
    if "해약환급금미지급형(납입후50%)" in text:
        notices.append("납입 완료 후 해지 시 비교상품 해약환급금의 <b>50%</b>를 지급받습니다.")
    elif "해약환급금미지급" in text:
        notices.append("<b>해약환급금 미지급형</b>으로 납입기간 중 해지 시 환급금이 없습니다.")
    if "갱신형" in text:
        notices.append("일부 담보가 <b>갱신형</b>입니다. 갱신 시 연령·손해율에 따라 보험료가 크게 증가할 수 있습니다.")
    if "암보장개시일" in text:
        notices.append("암 보장은 <b>계약일로부터 90일 이후</b>부터 시작됩니다.")
    if "인수지침 적용 전" in text:
        notices.append("<b>인수지침 적용 전 설계서</b>입니다. 확정된 담보·보험료는 청약서를 반드시 확인하세요.")
    if "특정부위부보장" in text:
        m = re.search(r"분류번호\(.*?\).*?면책기간.*?(\d년)", text)
        notices.append(f"<b>특정부위 부보장</b>이 있습니다." + (f" ({m.group(0)[:40]})" if m else ""))
    notices.append("본 카드뉴스는 이해를 돕기 위해 요약한 것이며, 정확한 보장 내용은 약관 기준으로 합니다.")
    return notices
