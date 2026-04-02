"""PDF 텍스트 추출 / 담보 은행 매칭 / 전체 담보 후보 추출"""
import re
from pypdf import PdfReader
from utils.db import get_all

# 담보명이 아닌 설명 텍스트를 걸러내는 패턴
_DESC_RE = re.compile(
    r'진단확정되었을\s*때'
    r'|가입금액\s*지급'
    r'|최초\s*1회한'
    r'|보험기간\s*중'
    r'|암보장개시일\s*이후'
    r'|계약일부터'
    r'|보험료자동납입'
    r'|\d+일\s*이상'
    r'|이\s*계약'
    r'|지급하지\s*않'
)


# ──────────────────────────────────────────────
# 제거 패턴 (가입 유형 접미사)
# ──────────────────────────────────────────────
_SUFFIX_RE = re.compile(
    r'\s*\(통합간편가입\)'
    r'|\s*\(맞춤간편가입\)'
    r'|\s*\(건강가입\)'
    r'|\s*\[기본계약\]'
    r'|\s*\(2\.0\)'
)
_PREFIX_RE = re.compile(r'^\s*(?:\d+년갱신\s*)?갱신형\s+')

_CAT_RULES = [
    ("cancer_treat", ['치료비', '항암', '중입자', '표적항암', '방사선약물', '생활비', '비급여 암']),
    ("cancer",       ['암진단', '암종별', '유사암진단', '유사암']),
    ("brain",        ['뇌혈관', '뇌졸중', '혈전용해']),
    ("heart",        ['심장', '허혈']),
    ("surgery",      ['수술', '이식수술']),
    ("care",         ['간병', '입원일당', '중환자실', '간호·간병', '간호간병']),
]


def auto_cat(name: str) -> str:
    for cat, kws in _CAT_RULES:
        if any(k in name for k in kws):
            return cat
    return "other"


def clean_kw(raw: str) -> str:
    """raw 담보명 → 키워드 (접미사 제거 + 공백 제거)"""
    s = _SUFFIX_RE.sub('', raw)
    s = _PREFIX_RE.sub('', s)
    return re.sub(r'\s+', '', s.strip())


def clean_title(raw: str) -> str:
    """표시용 제목 (접미사 제거, 공백 유지)"""
    s = _SUFFIX_RE.sub('', raw)
    s = _PREFIX_RE.sub('', s)
    return re.sub(r'\s+', ' ', s.strip())


# ──────────────────────────────────────────────
# PDF 텍스트 추출
# ──────────────────────────────────────────────

def extract_text(file) -> str:
    reader = PdfReader(file)
    pages = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            pages.append(t)
    if not pages:
        raise ValueError("텍스트를 추출할 수 없습니다. DRM이 걸린 파일일 수 있습니다.")
    return "\n".join(pages)


# ──────────────────────────────────────────────
# 전체 담보 후보 추출 (담보 은행 비교용)
# ──────────────────────────────────────────────

def extract_all_candidates(text: str) -> list[dict]:
    """
    PDF에서 모든 담보 후보 추출.
    pypdf 패턴: 숫자 단독 줄 → 다음 줄에 담보명 → 금액 줄
    """
    lines = [l.strip() for l in text.split('\n')]
    results = []
    seen = set()
    i = 0

    while i < len(lines):
        line = lines[i]
        nm = re.match(r'^(\d{1,3})$', line)
        if not nm:
            i += 1
            continue

        num = int(nm.group(1))
        if not (1 <= num <= 600):
            i += 1
            continue

        j = i + 1
        name_parts = []

        while j < len(lines) and len(name_parts) < 3:
            nl = re.sub(r'^[┗\s]+', '', lines[j]).strip()
            if (nl
                    and re.match(r'^[가-힣\(]', nl)
                    and not re.match(r'^\d+[만천백억]원', nl)
                    and not re.match(r'^\d+년', nl)
                    and not _DESC_RE.search(nl)
                    and '보장보험료' not in nl
                    and '담보사항' not in nl
                    and '주의사항' not in nl
                    and '고객콜센터' not in nl
                    and len(nl) > 4
                    and len(nl) <= 80):
                name_parts.append(nl)
                j += 1
            elif name_parts:
                break
            else:
                break

        if not name_parts:
            i += 1
            continue

        raw = ' '.join(name_parts)
        norm = re.sub(r'\s+', '', raw)

        if len(raw) < 6 or norm in seen:
            i = j
            continue
        seen.add(norm)

        # 금액 추출
        amount = None
        for k in range(j, min(j + 4, len(lines))):
            m = re.match(r'^(\d+(?:\.\d+)?(?:만|천만|백만|억)원)', lines[k].strip())
            if m:
                amount = m.group(1)
                break

        results.append({
            'num':    num,
            'raw':    raw,
            'amount': amount,
            'kw':     clean_kw(raw),
            'title':  clean_title(raw),
            'cat':    auto_cat(raw),
        })
        i = j

    return results


def find_new_candidates(all_candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    전체 후보를 담보 은행과 비교 → (이미_있음, 새것) 분리
    kw가 기존 bank kw에 포함되거나 포함하면 '이미 있음'
    """
    db = get_all()
    bank_kws = set()
    for entry in db:
        for kw in entry.get('kw', []):
            bank_kws.add(re.sub(r'\s+', '', kw))

    existing, new = [], []
    for cand in all_candidates:
        ck = cand['kw']
        # 부분 포함 여부로 판단
        matched = any(
            ck in bk or bk in ck
            for bk in bank_kws
            if len(ck) >= 5 and len(bk) >= 5
        )
        if matched:
            existing.append(cand)
        else:
            new.append(cand)
    return existing, new


# ──────────────────────────────────────────────
# 기존 담보 매칭 (카드뉴스 생성용)
# ──────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _find_amount(text: str, start: int) -> str | None:
    window = text[start: start + 400]
    m = re.search(r"(\d+(?:\.\d+)?)(억|천만|백만|만)(원)", window)
    return m.group(0) if m else None


def match_coverages(text: str) -> list[dict]:
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


# ──────────────────────────────────────────────
# 고객 정보 추출
# ──────────────────────────────────────────────

def extract_info(text: str) -> dict:
    flat = re.sub(r"\s+", " ", text)
    name = ""
    for pat in [r"피보험자\s*([가-힣]{2,5})\s*[（(]",
                r"계약자\s*([가-힣]{2,5})\s*[（(]",
                r"([가-힣]{2,5})\s*고객님을"]:
        m = re.search(pat, flat)
        if m:
            name = m.group(1)
            break
    premium = ""
    for pat in [r"1회차보험료\(할인후\)\s*([\d,]+)\s*원",
                r"보험료\s+([\d,]+)\s*원",
                r"([\d,]+)\s*원\s*보장보험료"]:
        m = re.search(pat, flat)
        if m:
            premium = m.group(1)
            break
    product = ""
    m = re.search(r"\(무\)[^\n\r]{4,90}", flat)
    if m:
        product = m.group(0).strip()
    period = ""
    m = re.search(r"(\d+년납\s*\d+년만기|\d+년납\s*\d+세만기)", text)
    if m:
        period = re.sub(r"\s+", " ", m.group(1))
    return dict(name=name, premium=premium, product=product, period=period)


def detect_notices(text: str) -> list[str]:
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
