"""3개 PDF 담보가 guide_amounts.json에 올바르게 매칭되는지 검증."""
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
from treatment_mapper import resolve_coverage_to_guide

PDFS = [
    ('LI GUANG XUN', 'test_li.pdf'),
    ('박시연',         'test_park.pdf'),
    ('이유상',         'test_lee.pdf'),
]

INTEREST_PATTERNS = ['통합치료비', '특정순환계']

for name, pdf in PDFS:
    with open(pdf, 'rb') as f:
        data = extract(f.read())
    print(f'\n━━━ {name} ━━━')
    for c in data.coverages:
        if not any(p in c.name for p in INTEREST_PATTERNS):
            continue
        result = resolve_coverage_to_guide(c)
        amt_m = (c.amount or 0) // 10000
        if result:
            gkey, tier, items = result
            item_preview = ', '.join(f'{k}={v}' for k, v in list(items.items())[:4]) + (' ...' if len(items) > 4 else '')
            print(f'  ✓ {amt_m:>5}만  [{gkey} tier={tier}]  {c.name[:55]}')
            print(f'       items: {item_preview}')
        else:
            print(f'  ✗ {amt_m:>5}만  [match fail]  {c.name[:60]}')
