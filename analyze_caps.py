"""
3개 PDF에서 통합치료비 담보별 가입금액 분포 분석.
가이드와 매칭되는지 확인.
"""
import sys, types
from pathlib import Path

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

from extractor import extract

PDFS = [
    ('LI GUANG XUN (The건강한 5.10.5)', 'test_li.pdf'),
    ('박시연 (내Mom대로 5.10.5)', 'test_park.pdf'),
    ('이유상 (통합간편건강 연만기)', 'test_lee.pdf'),
]

# 가이드 tier 정의
GUIDE_TIERS = {
    'bitonchi_premium': {
        'label': '비통치 고급형 (비급여 암통합치료비Ⅱ)',
        'pattern': lambda n: '암 통합치료비Ⅱ' in n or '암통합치료비Ⅱ' in n or (
            '암 통합치료비' in n and '비급여' in n and '전액본인부담' in n
        ),
        'available_caps_man': [10000, 7000, 4000]
    },
    'bitonchi_main_only': {
        'label': '비통치 주요치료형',
        'pattern': lambda n: False,  # 실제 상품명 모름. 필요시 추가
        'available_caps_man': [7000, 5000, 2000]
    },
    'amtonchi_basic': {
        'label': '암통치 기본형 (암 통합치료비 기본형)',
        'pattern': lambda n: ('암 통합치료비' in n or '암통합치료비' in n) and '기본형' in n,
        'available_caps_man': [10000, 8000, 4000]
    },
    'amtonchi_economy': {
        'label': '암통치 실속형',
        'pattern': lambda n: ('암 통합치료비' in n or '암통합치료비' in n) and '실속형' in n,
        'available_caps_man': [7000, 5000, 3000, 1000]
    },
    'suntonchi': {
        'label': '순통치 (특정순환계질환 통합치료비)',
        # "통합치료 생활비"는 제외 — 그건 조건부 추가지급 담보로 별개.
        'pattern': lambda n: '특정순환계질환' in n and '통합치료비' in n and '생활비' not in n,
        'available_caps_man': [10000, 8000, 5000, 3000, 2000]
    },
}

all_findings = {}
for customer, pdf in PDFS:
    with open(pdf, 'rb') as f:
        data = extract(f.read())

    print(f'\n━━━ {customer} ━━━')
    for c in data.coverages:
        amt_m = (c.amount // 10000) if c.amount else 0
        for guide_key, guide in GUIDE_TIERS.items():
            if guide['pattern'](c.name):
                hit = '✓ 가이드 있음' if amt_m in guide['available_caps_man'] else '✗ 가이드 없음 (약관 필요)'
                print(f'  [{guide["label"]}]  {amt_m}만원  {hit}')
                print(f'    ↳ {c.name!r}')
                all_findings.setdefault(guide_key, []).append((customer, amt_m, c.name, amt_m in guide['available_caps_man']))

print(f'\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
print('📊 가이드 tier 매칭 요약')
print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
for key, findings in all_findings.items():
    info = GUIDE_TIERS[key]
    print(f'\n● {info["label"]}')
    print(f'  가이드 available tier: {info["available_caps_man"]}')
    for cust, amt, name, hit in findings:
        mark = '✓' if hit else '✗ 약관필요'
        print(f'    {mark}  {cust}  →  {amt}만원')
