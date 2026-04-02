"""매칭된 담보 리스트 → 카드뉴스 HTML 생성"""
from utils.db import CATS

_TAG_STYLE = {
    "cancer":       "background:#FEE2E2;color:#991B1B",
    "cancer_treat": "background:#F3E8FF;color:#6B21A8",
    "brain":        "background:#DBEAFE;color:#1E3A8A",
    "heart":        "background:#FFE4E6;color:#9F1239",
    "surgery":      "background:#D1FAE5;color:#065F46",
    "care":         "background:#E0F2FE;color:#075985",
    "other":        "background:#F1F5F9;color:#334155",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans KR',system-ui,sans-serif;background:#F5F4F0;color:#1a1a1a;-webkit-font-smoothing:antialiased}

/* Hero */
.hero{background:linear-gradient(135deg,#1B3A5C 0%,#0F2641 100%);color:#fff;padding:26px 18px 22px}
.hero-product{font-size:10px;opacity:.55;margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hero-name{font-size:21px;font-weight:800;margin-bottom:15px;letter-spacing:-.3px}
.hero-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.hi{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.13);border-radius:9px;padding:10px;text-align:center}
.hi-l{font-size:10px;opacity:.5;margin-bottom:3px}
.hi-v{font-size:14px;font-weight:700}

/* Section */
.cards{padding:14px 13px 28px;max-width:700px;margin:0 auto}
.sec{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:700;color:#9ca3af;letter-spacing:.7px;margin:20px 0 9px;text-transform:uppercase}
.sec::after{content:'';flex:1;height:1px;background:#e4e3de}
.si{font-size:14px}

/* Card */
.card{background:#fff;border:1px solid #e4e3de;border-radius:12px;margin-bottom:8px;overflow:hidden}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;padding:13px 16px 9px;gap:8px}
.c-tag{flex-shrink:0;font-size:10px;font-weight:700;padding:3px 9px;border-radius:20px}
.c-amt{font-size:18px;font-weight:800;color:#1B3A5C;text-align:right;line-height:1.1;white-space:nowrap}
.c-amt small{display:block;font-size:9px;font-weight:400;color:#9ca3af;margin-top:1px}
.c-title{font-size:13px;font-weight:700;padding:0 16px 3px}
.c-desc{font-size:11.5px;color:#6b7280;padding:2px 16px 12px;line-height:1.72}
.c-conds{display:flex;flex-wrap:wrap;gap:4px;padding:9px 16px 13px;border-top:1px solid #f0efe9}
.cw{font-size:10px;padding:2px 8px;border-radius:20px;font-weight:600;background:#FFF7ED;color:#C2410C}
.ci{font-size:10px;padding:2px 8px;border-radius:20px;font-weight:600;background:#F4F4F0;color:#6b7280}

/* Notice */
.notice{margin:4px 13px 26px;background:#fff;border:1px solid #e4e3de;border-radius:12px;padding:15px 17px}
.nt{font-size:11px;font-weight:700;color:#6b7280;margin-bottom:10px}
.ni{font-size:11.5px;color:#6b7280;padding:5px 0 5px 14px;position:relative;border-bottom:1px solid #f4f3ee;line-height:1.68}
.ni:last-child{border-bottom:none}
.ni::before{content:'·';position:absolute;left:3px;color:#9ca3af}
.ni b{color:#374151;font-weight:700}
</style>
"""


def _hero(info: dict, cov_count: int) -> str:
    name = f"{info['name']} 고객님" if info.get("name") else "고객님"
    premium = (info.get("premium") or "") + "원" if info.get("premium") else "—"
    period = info.get("period") or "—"
    product = info.get("product") or "메리츠화재 가입설계서"
    return (
        f'<div class="hero">'
        f'<div class="hero-product">{product}</div>'
        f'<div class="hero-name">{name}의 보장 내용</div>'
        f'<div class="hero-grid">'
        f'<div class="hi"><div class="hi-l">월 보험료</div><div class="hi-v">{premium}</div></div>'
        f'<div class="hi"><div class="hi-l">보험기간</div><div class="hi-v">{period}</div></div>'
        f'<div class="hi"><div class="hi-l">매칭 담보</div><div class="hi-v">{cov_count}개</div></div>'
        f'</div></div>'
    )


def _card(cov: dict) -> str:
    cat = cov.get("cat", "other")
    tag_style = _TAG_STYLE.get(cat, _TAG_STYLE["other"])
    amount = cov.get("amount") or "약관 참조"
    tag_label = cov.get("sub") or cov["title"]

    warns = "".join(f'<span class="cw">⚠ {w}</span>' for w in cov.get("warns", []))
    info  = "".join(f'<span class="ci">{i}</span>'  for i in cov.get("info",  []))
    conds = f'<div class="c-conds">{warns}{info}</div>' if (warns or info) else ""

    return (
        f'<div class="card">'
        f'<div class="card-top">'
        f'<span class="c-tag" style="{tag_style}">{tag_label}</span>'
        f'<span class="c-amt">{amount}<small>가입금액</small></span>'
        f'</div>'
        f'<div class="c-title">{cov["title"]}</div>'
        f'<div class="c-desc">{cov.get("desc","")}</div>'
        f'{conds}</div>'
    )


def _notice(notices: list[str]) -> str:
    items = "".join(f'<div class="ni">{n}</div>' for n in notices)
    return f'<div class="notice"><div class="nt">꼭 확인하세요</div>{items}</div>'


def build_html(info: dict, coverages: list[dict], notices: list[str]) -> str:
    # 카테고리별 그룹핑 (DB 순서 유지)
    groups: dict[str, list] = {}
    for cov in coverages:
        cat = cov.get("cat", "other")
        groups.setdefault(cat, []).append(cov)

    sections = ""
    for cat, items in groups.items():
        c = CATS.get(cat, {"label": cat, "icon": ""})
        cards = "".join(_card(item) for item in items)
        sections += (
            f'<div class="sec"><span class="si">{c["icon"]}</span>'
            f'{c["label"].upper()}</div>{cards}'
        )

    return (
        f'<!DOCTYPE html><html lang="ko"><head>'
        f'<meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'{_CSS}</head><body>'
        f'{_hero(info, len(coverages))}'
        f'<div class="cards">{sections}</div>'
        f'{_notice(notices)}'
        f'</body></html>'
    )
