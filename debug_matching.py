"""
3개 PDF에 대해 각 분석기(암/2대담보)가 어떤 담보를 매칭/미매칭했는지 전부 출력.
"""
import sys, types
from pathlib import Path

# Streamlit stub
stub = types.ModuleType('streamlit')
def _id(*a, **k):
    if a and callable(a[0]): return a[0]
    return lambda fn: fn
stub.cache_data = _id; stub.cache_resource = _id
comp = types.ModuleType('streamlit.components')
v1 = types.ModuleType('streamlit.components.v1')
v1.html = lambda *a, **k: None
comp.v1 = v1; stub.components = comp
sys.modules['streamlit'] = stub
sys.modules['streamlit.components'] = comp
sys.modules['streamlit.components.v1'] = v1
sys.path.insert(0, '.')

import app as app_mod
app_mod._find_asset_dir = lambda name: Path('.') / name

from app import build_analyzer_result

PDFS = [
    ('LI GUANG XUN', 'test_li.pdf'),
    ('박시연', 'test_park.pdf'),
    ('이유상', 'test_lee.pdf'),
]

# 기본담보/사망후유/수술비 등은 암·2대 분석 대상이 아니므로 제외하고 리포트
EXCLUDE_CATEGORIES = {'기본계약', '사망후유', '수술', '골절/화상', '기타', '재물/배상'}

# extras (사망/보험료자동납입/상해 등 치료 무관) 패턴
EXCLUDE_NAME_PATTERNS = [
    r'^보험료자동납입',
    r'일반상해',
    r'수술비Ⅱ',
    r'131대질병수술비\(다빈도',
    r'131대질병수술비\(특정다빈도',
    r'131대질병수술비\(백내장',
    r'131대질병수술비\(관절염',
    r'131대질병수술비\(후각',
    r'131대질병수술비\(치핵',
    r'131대질병수술비\(유방',
    r'131대질병수술비\(편도',
    r'131대질병수술비\(특정31대',
    r'질병수술비',
    r'상해수술비',
    r'골절',
    r'5대골절',
    r'깁스치료비',
    r'신화상치료비',
    r'상급종합병원 질병수술비',
    r'가족일상생활중배상',
]

import re

def is_excluded(cov):
    if cov.get('category') in EXCLUDE_CATEGORIES:
        # 하지만 131대 심장/뇌혈관은 포함 (2대담보 관련)
        n = cov['name']
        if '131대질병수술비(심장' in n or '131대질병수술비(뇌' in n:
            return False
        return True
    for pat in EXCLUDE_NAME_PATTERNS:
        if re.search(pat, cov['name']):
            return True
    return False


def run(analyzer_id: str, pdf_path: str):
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    r = build_analyzer_result(pdf_bytes, analyzer_id)
    cov_to_card = {}
    for card in r.get('treatment_cards', []):
        for g in card['groups']:
            cov_to_card.setdefault(g['coverage_name'], []).append(card['label'])
    return r['coverages_all'], cov_to_card, r.get('product_type')


for customer, pdf in PDFS:
    print(f'\n{"="*80}')
    print(f'  {customer}  ({pdf})')
    print(f'{"="*80}')

    for analyzer in ['cancer', 'two_major']:
        covs, mapping, pt = run(analyzer, pdf)
        tab_name = '암 분석기' if analyzer == 'cancer' else '2대담보 분석기'
        print(f'\n[{tab_name}]  상품타입: {pt}')

        unmatched = []
        matched = []
        for c in covs:
            if is_excluded(c):
                continue
            if c['name'] in mapping:
                matched.append((c, mapping[c['name']]))
            else:
                unmatched.append(c)

        if matched:
            print(f'  ✓ 매칭된 담보 ({len(matched)}개)')
            for c, cards in matched:
                amt_m = (c.get('amount', 0) or 0) // 10000
                print(f'    {c.get("code",""):>4}  {c["name"][:60]:60s}  {amt_m:>6}만  →  {", ".join(cards)}')

        if unmatched:
            print(f'  ✗ 미매칭 담보 ({len(unmatched)}개)')
            for c in unmatched:
                amt_m = (c.get('amount', 0) or 0) // 10000
                print(f'    {c.get("code",""):>4}  {c["name"][:60]:60s}  {amt_m:>6}만')
        else:
            print(f'  (미매칭 없음)')
