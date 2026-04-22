"""
Meritz 가입제안서 PDF에서 고객정보, 계약정보, 담보 리스트를 추출.

설계 원칙:
- pypdf plain text 기반 (pdfplumber 대비 5~10배 빠름)
- 담보 테이블은 "코드 → 이름 → 가입금액 → 보험료" 4-토큰 블록 구조
- 이름이 여러 줄에 걸치는 경우(괄호 안에서 끊김)도 처리
- "안내참조", "세부보장 참조" 같은 특수 금액 문자열도 Coverage로 보존
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from pypdf import PdfReader


# ─────────────────────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────────────────────

@dataclass
class Coverage:
    code: str
    name: str
    category: str  # 기본계약, 3대진단, 수술, 치료비 등
    amount: Optional[int]  # 원 단위. "안내참조" 등은 None
    amount_display: str  # 원본 금액 표기 그대로 (예: "2천만원", "안내참조")
    premium: int  # 월 보험료 (원)


@dataclass
class Customer:
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    birth: Optional[str] = None
    job: Optional[str] = None
    job_grade: Optional[str] = None


@dataclass
class Policy:
    product_name_full: str
    product_name_short: str
    premium_monthly: int
    premium_total_expected: Optional[int] = None
    period_description: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class ExtractedData:
    customer: Customer
    policy: Policy
    coverages: list[Coverage] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# 금액 파서
# ─────────────────────────────────────────────────────────────

def parse_korean_amount(s: str) -> Optional[int]:
    """'2천만원' → 20_000_000, '1백만원' → 1_000_000, '1억원' → 100_000_000"""
    if not s:
        return None
    s = s.strip()
    if s in ("안내참조", "세부보장참조", "세부보장 참조"):
        return None
    s_clean = s.replace(" ", "").replace(",", "")

    # "2억 3,000만원" 같은 복합 → 2억 + 3000만 = 230_000_000
    total = 0
    m = re.match(r'^(\d+)억', s_clean)
    if m:
        total += int(m.group(1)) * 100_000_000
        s_clean = s_clean[m.end():]
    m = re.match(r'^(\d+)천만', s_clean)
    if m:
        total += int(m.group(1)) * 10_000_000
        s_clean = s_clean[m.end():]
    m = re.match(r'^(\d+)백만', s_clean)
    if m:
        total += int(m.group(1)) * 1_000_000
        s_clean = s_clean[m.end():]
    m = re.match(r'^(\d+)만', s_clean)
    if m:
        total += int(m.group(1)) * 10_000
        s_clean = s_clean[m.end():]

    if total > 0:
        return total

    # "1,000,000원" 같은 숫자 원
    m = re.match(r'^([\d,]+)원?$', s_clean)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def format_amount_display(amount: Optional[int]) -> str:
    """10_000_000 → '1,000만원', 230_000_000 → '2억 3,000만원'"""
    if amount is None:
        return "-"
    eok = amount // 100_000_000
    rest = amount % 100_000_000
    man = rest // 10_000
    won = rest % 10_000
    if eok and man:
        return f"{eok}억 {man:,}만원"
    if eok:
        return f"{eok}억원"
    if man:
        return f"{man:,}만원"
    return f"{amount:,}원"


# ─────────────────────────────────────────────────────────────
# PDF 텍스트 추출
# ─────────────────────────────────────────────────────────────

def _read_all_text(pdf_bytes: bytes) -> list[str]:
    """각 페이지를 리스트로 반환."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


# ─────────────────────────────────────────────────────────────
# 담보 테이블 파서
# ─────────────────────────────────────────────────────────────

CATEGORY_WORDS = {
    "기본계약", "사망후유", "3대진단", "수술", "치료비", "입원", "치료",
    "상해", "질병", "배상", "실손", "간병", "기타", "장기이식",
    "후유장해", "진단", "골절", "화상", "재활",
}

# 가입금액 라인 감지: "2천만원", "1백만원", "1억원", "50만원", "10,000,000원", "안내참조", "세부보장 참조"
AMOUNT_LINE_RE = re.compile(
    r'^(?:\d+(?:억|천만|백만|만)원|[\d,]+원|안내참조|세부보장\s*참조)$'
)

# 보험료 라인: 숫자 또는 콤마 숫자만
PREMIUM_LINE_RE = re.compile(r'^\d{1,3}(?:,\d{3})*$')

# 담보 코드 라인: 1-4자리 정수만
CODE_LINE_RE = re.compile(r'^\d{1,4}$')

# 노이즈 라인 (무시해야 할 패턴들)
NOISE_PATTERNS = [
    re.compile(r'^page\s*:\s*\d+/\d+$'),
    re.compile(r'^고객콜센터'),
    re.compile(r'^www\.'),
    re.compile(r'^영업담당자$'),
    re.compile(r'^발행정보$'),
    re.compile(r'^\d{4}\.\d{2}\.\d{2}'),
    re.compile(r'^가입담보$'),
    re.compile(r'^가입금액$'),
    re.compile(r'^보험료\(원\)$'),
    re.compile(r'^납기/만기$'),
    re.compile(r'^담보사항$'),
    re.compile(r'^보장보험료\s*합계'),
    re.compile(r'^\d{1,3}(?:,\d{3})*\s*원$'),  # 보험료 합계 액수
    re.compile(r'^갱신종료\s*:'),
    re.compile(r'^\d+년\s*/\s*\d+'),  # 납기/만기 "30년 / 30년"
    re.compile(r'^선택계약$'),  # 페이지 5+ 세부 뷰의 구역 헤더
    re.compile(r'^\[피보험자'),
    re.compile(r'^보험료자동납입특약$'),  # 납입 특약은 담보가 아님
]


def _is_noise(line: str) -> bool:
    if not line:
        return True
    return any(p.search(line) for p in NOISE_PATTERNS)


def _parse_coverages(pages_text: list[str]) -> list[Coverage]:
    """
    모든 페이지 텍스트에서 담보 블록을 찾아 Coverage 리스트로 반환.

    알고리즘:
      1. 담보 요약 테이블 영역을 모든 페이지에서 추출하여 하나로 합침
         - 시작: 첫 번째 "보장보험료 합계"
         - 끝: "보험료 납입면제 관련 안내" 또는 "가입담보 및 보장내용" (세부 설명의 시작)
      2. 카테고리 헤더 발견 시 현재 카테고리 갱신
      3. 코드 라인(순수 숫자) 발견 시 look-ahead로 가입금액 라인 탐색
      4. 코드~금액 사이 모든 라인을 name으로 concat (줄바꿈 정리)
      5. 금액 다음 라인을 보험료로 파싱
    """
    full_text = '\n'.join(pages_text)

    start_idx = full_text.find('보장보험료 합계')
    if start_idx < 0:
        start_idx = 0

    # 종료 마커: "보험료 납입면제 관련 안내" 또는 세부 설명 테이블 시작
    # 둘 중 먼저 등장하는 쪽을 종료점으로 삼음
    cutoff_markers = [
        '보험료 납입면제 관련 안내',
        '가입담보 및 보장내용',  # 세부 설명 테이블 헤더
        '보험료 납입면제에 관한 사항',
    ]
    end_idx = len(full_text)
    for mk in cutoff_markers:
        idx = full_text.find(mk, start_idx + 1)
        if idx > 0:
            end_idx = min(end_idx, idx)

    text = full_text[start_idx:end_idx]

    lines = [l.strip() for l in text.split('\n')]
    coverages: list[Coverage] = []
    current_category: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        if _is_noise(line):
            i += 1
            continue

        if line in CATEGORY_WORDS or line.rstrip('/') in CATEGORY_WORDS:
            current_category = line.rstrip('/')
            i += 1
            continue

        # '골절/화상' 같은 복합 카테고리 처리
        if '/' in line and all(p.strip() in CATEGORY_WORDS for p in line.split('/')):
            current_category = line
            i += 1
            continue

        if CODE_LINE_RE.match(line):
            # look-ahead 최대 8줄 내에서 금액 라인 찾기
            amount_idx = None
            for j in range(i + 1, min(i + 9, len(lines))):
                lj = lines[j]
                if _is_noise(lj):
                    continue
                if AMOUNT_LINE_RE.match(lj):
                    amount_idx = j
                    break
                # 다음 코드가 먼저 오면 이 "코드"는 오탐
                if CODE_LINE_RE.match(lj) and j > i + 1:
                    break

            if amount_idx is None:
                i += 1
                continue

            code = line
            name_parts = []
            for k in range(i + 1, amount_idx):
                if _is_noise(lines[k]):
                    continue
                name_parts.append(lines[k])
            name = ''.join(name_parts).strip()

            # 이름 후처리: 괄호 사이 줄바꿈 제거, 중복 공백 정리
            name = re.sub(r'\s+', ' ', name)
            name = name.replace('( ', '(').replace(' )', ')')

            amount_str = lines[amount_idx]
            amount = parse_korean_amount(amount_str)

            # 다음 줄에서 보험료 찾기
            premium = 0
            scan_from = amount_idx + 1
            for j in range(scan_from, min(scan_from + 3, len(lines))):
                if _is_noise(lines[j]):
                    continue
                if PREMIUM_LINE_RE.match(lines[j]):
                    premium = int(lines[j].replace(',', ''))
                    scan_from = j + 1
                    break

            coverages.append(Coverage(
                code=code,
                name=name,
                category=current_category or "기타",
                amount=amount,
                amount_display=amount_str,
                premium=premium,
            ))
            i = scan_from
            continue

        i += 1

    return coverages


# ─────────────────────────────────────────────────────────────
# 고객/계약 정보 파서
# ─────────────────────────────────────────────────────────────

def _parse_customer(pages_text: list[str]) -> Customer:
    full = '\n'.join(pages_text)

    # 이름, 성별, 생년월일, 나이
    # "피보험자 | 연령\n김기현 (여, 1982. 11. 24 ) | 43세"
    m = re.search(
        r'피보험자\s*\|\s*연령\s*\n?([^\n(]+?)\s*\((남|여)\s*,\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\s*\)\s*\|\s*(\d+)\s*세',
        full
    )
    name, gender, birth, age = None, None, None, None
    if m:
        name = m.group(1).strip()
        gender = m.group(2)
        birth = m.group(3).strip().replace(' ', '')
        age = int(m.group(4))

    # 직업 + 직업급수
    job, job_grade = None, None
    m = re.search(r'피보험자\s*직업\s*\n?([^,\n]+?)\s*\(\d+\)\s*,\s*(\d+급)', full)
    if m:
        job = m.group(1).strip()
        job_grade = m.group(2)

    # fallback: 피보험자 이름만이라도 (가입제안서 첫 페이지)
    if not name:
        m = re.search(r'피보험자\s*\n?([^\n(|]+?)(?:\(|\n)', full)
        if m:
            name = m.group(1).strip()

    return Customer(
        name=name or "고객",
        age=age,
        gender=gender,
        birth=birth,
        job=job,
        job_grade=job_grade,
    )


def _parse_policy(pages_text: list[str]) -> Policy:
    full = '\n'.join(pages_text)

    # 상품명 (1페이지: "(무)메리츠The건강한5.10.5보장보험2604 (...)")
    product_full = ""
    m = re.search(r'(\(무\)[^\n]*?메리츠[^\n]+?보험[^\n]*?\))', full)
    if m:
        product_full = m.group(1).strip()
    else:
        m = re.search(r'(\(무\)[^\n]+?(?:보험|건강보험)[^\n]*)', full)
        if m:
            product_full = m.group(1).strip()

    # 짧은 이름 (괄호 제거 + "메리츠 XXX" 형태로 다듬기)
    product_short = re.sub(r'\(무\)\s*', '', product_full)
    product_short = re.sub(r'\([^)]*\)', '', product_short).strip()
    product_short = re.sub(r'\s+', ' ', product_short)
    if not product_short.startswith('메리츠'):
        product_short = '메리츠 ' + product_short
    # 2604 같은 코드 제거
    product_short = re.sub(r'\s*\d{4}$', '', product_short).strip()

    # 월 보험료
    premium_monthly = 0
    for pat in [r'1회차보험료\(할인후\)\s*\n?([\d,]+)\s*원',
                r'2회차이후보험료\s*\n?([\d,]+)\s*원',
                r'보험료\s*\n?([\d,]+)\s*원']:
        m = re.search(pat, full)
        if m:
            premium_monthly = int(m.group(1).replace(',', ''))
            break

    # 총 납입예상 보험료
    total = None
    m = re.search(r'총납입예상보험료\s*\n?([\d,]+)\s*원', full)
    if m:
        total = int(m.group(1).replace(',', ''))

    # 계약사항: 기간 설명
    period = ""
    start_date, end_date = None, None
    m = re.search(
        r'계약사항\s*:?\s*([^\|\n]+?)\s*\|[^\n]*?(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*~\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일',
        full
    )
    if m:
        period = m.group(1).strip()
        start_date = f"{m.group(2)}.{m.group(3)}"
        end_date = f"{m.group(5)}.{m.group(6)}"

    return Policy(
        product_name_full=product_full,
        product_name_short=product_short,
        premium_monthly=premium_monthly,
        premium_total_expected=total,
        period_description=period,
        start_date=start_date,
        end_date=end_date,
    )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def extract(pdf_bytes: bytes) -> ExtractedData:
    pages_text = _read_all_text(pdf_bytes)
    return ExtractedData(
        customer=_parse_customer(pages_text),
        policy=_parse_policy(pages_text),
        coverages=_parse_coverages(pages_text),
    )


# ─────────────────────────────────────────────────────────────
# CLI 테스트용
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/4.pdf"
    with open(path, 'rb') as f:
        data = extract(f.read())
    print(json.dumps({
        "customer": asdict(data.customer),
        "policy": asdict(data.policy),
        "coverages": [asdict(c) for c in data.coverages],
    }, ensure_ascii=False, indent=2))
