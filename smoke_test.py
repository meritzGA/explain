"""Smoke test for the unified analyzer: mock coverages → run both cancer and
2대담보 pipelines → render HTML for each.

Stubs out streamlit to avoid needing the full Streamlit runtime.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ── Stub streamlit module so we can import app.py without the runtime ─────
stub = types.ModuleType("streamlit")

def _identity(*args, **kwargs):
    def wrap(fn):
        return fn
    # support both @cache_data and @cache_data(show_spinner=False)
    if args and callable(args[0]):
        return args[0]
    return wrap

stub.cache_data = _identity
stub.cache_resource = _identity
# components submodule
comp = types.ModuleType("streamlit.components")
v1 = types.ModuleType("streamlit.components.v1")
v1.html = lambda *a, **k: None
comp.v1 = v1
stub.components = comp
sys.modules["streamlit"] = stub
sys.modules["streamlit.components"] = comp
sys.modules["streamlit.components.v1"] = v1

# Now we can import from app
sys.path.insert(0, str(Path(__file__).parent))
from app import build_analyzer_result, render_html, load_analyzer_registry  # noqa
from extractor import Coverage  # noqa
from dataclasses import asdict  # noqa

# Monkey-patch parse_pdf & build_analyzer_result to bypass pdf extraction
# (we'll inject mock coverages directly by patching extract in extractor)
import extractor

from extractor import Customer, Policy  # noqa: E402

class _MockExtracted:
    def __init__(self, customer, policy, coverages):
        self.customer = customer
        self.policy = policy
        self.coverages = coverages

def _make_customer():
    return Customer(name="홍길동", age=45, gender="M", birth="1980-01-01", job="사무직", job_grade="A")

def _make_policy():
    return Policy(
        product_name_full="메리츠 통합간편건강보험",
        product_name_short="통합간편",
        premium_monthly=50000,
        premium_total_expected=None,
        period_description="",
        start_date="2025-04-23",
        end_date=None,
    )

# Mock coverages — mix of cancer + 2대담보 담보
MOCK_COVERAGES = [
    # Cancer
    Coverage(code="C001", name="암진단및치료비[암 통합치료비Ⅲ(비급여(전액본인부담 포함))]", category="3대진단",
             amount=30_000_000, amount_display="3천만원(1,500만)", premium=5000),
    Coverage(code="C002", name="유사암진단비", category="3대진단", amount=5_000_000, amount_display="5백만원", premium=300),
    # 2대담보
    Coverage(code="B001", name="뇌혈관질환진단비(통합간편가입)", category="3대진단",
             amount=20_000_000, amount_display="2천만원", premium=1500),
    Coverage(code="B002", name="뇌졸중진단비", category="3대진단", amount=10_000_000, amount_display="1천만원", premium=900),
    Coverage(code="B003", name="뇌혈관질환수술비", category="수술", amount=10_000_000, amount_display="1천만원", premium=700),
    Coverage(code="B004", name="혈전용해치료비(뇌졸중)", category="치료비", amount=3_000_000, amount_display="3백만원", premium=250),
    Coverage(code="H001", name="허혈성심장질환진단비(통합간편가입)", category="3대진단",
             amount=20_000_000, amount_display="2천만원", premium=1600),
    Coverage(code="H002", name="허혈성심장질환수술비", category="수술", amount=10_000_000, amount_display="1천만원", premium=750),
    Coverage(code="H003", name="혈전용해치료비(특정심장질환)", category="치료비", amount=3_000_000, amount_display="3백만원", premium=300),
    Coverage(code="H004", name="관상동맥우회술치료비", category="수술", amount=20_000_000, amount_display="2천만원", premium=1200),
    Coverage(code="H005", name="관상동맥 스텐트삽입술 치료비", category="수술", amount=5_000_000, amount_display="5백만원", premium=500),
    # Irrelevant
    Coverage(code="X001", name="일반상해사망", category="기본계약", amount=100_000_000, amount_display="1억원", premium=2000),
]

def _mock_extract(pdf_bytes):
    return _MockExtracted(_make_customer(), _make_policy(), MOCK_COVERAGES)

# Patch inside app module (where `from extractor import extract` bound the name)
import app as app_mod
app_mod.extract = _mock_extract

# Also stub find_asset_dir so config/templates resolution works from anywhere
def _stub_find(name):
    return Path(__file__).parent / name
app_mod._find_asset_dir = _stub_find

# Run pipeline for both analyzers
registry = load_analyzer_registry()
print(f"Registry loaded: {len(registry)} analyzers")
for a in registry:
    print(f"  - [{a['id']}] {a['tab_label']} ({a['report_label']})")

print()
print("Running analyzers on mock PDF...")
for a in registry:
    print(f"\n=== {a['tab_label']} ===")
    result = build_analyzer_result(b"fake pdf bytes", a["id"])
    print(f"  report_label: {result['report_label']}")
    print(f"  product_type: {result['product_type']}")
    print(f"  treatment_cards: {len(result['treatment_cards'])}")
    for card in result["treatment_cards"]:
        print(f"    [{card['id']}] {card['label']}: {card['subtotal_display'].replace(chr(10), ' ')}")
    if result.get("headline"):
        print(f"  headline: {result['headline']['five_year_min_display']} ~ {result['headline']['five_year_max_display']}")

    # Render HTML for each
    result["source_filename"] = "test.pdf"
    result["source_filesize"] = "100 KB"
    html = render_html(result)
    out = Path(f"/tmp/unified_{a['id']}.html")
    out.write_text(html, encoding="utf-8")
    print(f"  → HTML: {out} ({out.stat().st_size:,} bytes)")

print("\n✓ All analyzers ran end-to-end.")
