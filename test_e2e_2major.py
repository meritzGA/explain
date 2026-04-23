"""2대담보 분석기 가이드 override 결과."""
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

import app as app_mod
app_mod._find_asset_dir = lambda name: Path('.') / name
from app import build_analyzer_result

for customer, pdf in [
    ('LI GUANG XUN', 'test_li.pdf'),
    ('박시연', 'test_park.pdf'),
]:
    with open(pdf, 'rb') as f:
        r = build_analyzer_result(f.read(), 'two_major')
    print(f'\n━━━━━━━━━━ {customer} / 2대담보 분석기 ━━━━━━━━━━')
    for card in r.get('treatment_cards', []):
        print(f'\n▶ {card["label"]}  [subtotal {card["subtotal_min"]:,}~{card["subtotal_max"]:,}만]  recurring={card["recurring"]}')
        for g in card["groups"]:
            print(f'  └ {g["coverage_name_short"]}')
            for it in g["item_list"]:
                print(f'      · {it["label"]}  [{it["display"]}]')
