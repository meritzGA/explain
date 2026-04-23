# 메리츠 보장 분석기 (통합 탭 버전)

메리츠 가입제안서 PDF를 **한 번** 업로드하면 **암 보장**과 **2대담보**를 탭으로 나눠 자동 분석하는 통합 도구입니다. 지점장이 상담 현장에서 고객의 암 치료비와 2대담보 치료비를 모두 보여드릴 수 있도록 설계되었습니다.

## 빠른 시작

```bash
pip install -r requirements.txt
streamlit run app.py
```

PDF를 올리시면 자동으로 **[암 보장 분석]**, **[2대담보 분석]** 두 탭이 생성됩니다. 탭 전환은 캐시되어 있어 즉시 전환됩니다.

## 파일 구조

```
meritz_unified/
├── app.py                           # Streamlit UI + 탭 처리 + 캐싱
├── extractor.py                     # pypdf PDF 파서 (분석기 공용)
├── treatment_mapper.py              # 카드 생성 로직 (generic_2major fallback 지원)
├── config/
│   ├── analyzers.json               # ★ 탭 레지스트리 — 여기에 항목 추가하면 탭 추가
│   ├── events_cancer.json           # 암 분석용 이벤트 매핑
│   ├── treatments_cancer.json       # 암 치료 카드 프리셋 (4개 상품 타입)
│   ├── events_2major.json           # 2대담보 이벤트 매핑
│   └── treatments_2major.json       # 2대담보 치료 카드 프리셋
├── templates/
│   └── report.html                  # Jinja2 템플릿 (report_label 변수로 공유)
├── smoke_test.py                    # streamlit 런타임 없이 돌리는 E2E 테스트
└── requirements.txt
```

## 작동 방식

1. **PDF 업로드** → `parse_pdf(pdf_bytes)` 호출
   - `@st.cache_data` 적용으로 **PDF당 1회만 파싱** (pypdf, 약 2초)
2. **분석기별 매핑** → 레지스트리를 돌면서 각 분석기마다 `build_analyzer_result(pdf_bytes, analyzer_id)` 호출
   - 캐시 키: `(pdf_bytes, analyzer_id)` — 분석기별로 따로 캐싱
   - `parse_pdf`는 이 시점에 이미 캐시되어 있어 즉시 반환 → 매핑 연산만 수행
3. **탭 렌더** → `st.tabs(tab_labels)`로 탭 구성. 각 탭 안에서 Jinja2로 `report.html` 렌더
4. **다운로드 버튼** → 탭마다 별도 제공

## 탭 추가하는 법

현재는 암 / 2대담보 두 탭이지만, 향후 "간병·입원 분석" 같은 탭을 추가하려면 `config/analyzers.json`에 항목 하나 추가하고 해당 config 파일 2개(events_*, treatments_*)만 작성하면 됩니다. `app.py` 수정 불필요.

```json
{
  "id": "caregiving",
  "tab_label": "간병·입원 분석",
  "report_label": "간병 입원비",
  "events_config": "events_caregiving.json",
  "treatments_config": "treatments_caregiving.json"
}
```

## 스모크 테스트 결과

`python smoke_test.py`로 Streamlit 런타임 없이 파이프라인 E2E 테스트 가능. 12개 mock 담보(암 2개 + 뇌혈관 4개 + 심장 5개 + 관계없는 상해사망 1개) 기준:

| 분석기 | 카드 수 | 5년 헤드라인 |
|--------|---------|--------------|
| 암 보장 | 3개 (표적/면역/양성자) | 2억 2,500만원 ~ 4억 5,000만원 |
| 2대담보 | 8개 (진단/수술/혈전/CABG/스텐트 등) | 5억 500만원 |

암 분석 헤드라인은 업로드하신 박진서 샘플 이미지 수치와 정확히 일치합니다.

## 주의사항

- `treatment_mapper.py`는 2대담보 fallback이 추가된 버전입니다. `_alias_applied_in_code: true` 플래그가 있는 config(= `treatments_2major.json`)에서만 `generic_2major` 프리셋으로 fallback합니다. 기존 암 분석기 동작은 그대로입니다.
- `report.html`은 `report_label` 변수를 사용합니다. 암 탭에서는 "암 치료비", 2대담보 탭에서는 "2대담보 치료비"로 자동 표시됩니다.
- `st.cache_resource`로 로드되는 config는 Streamlit 앱 재시작 시에만 새로 읽습니다. `config/*.json`을 수정했으면 Streamlit을 재시작하세요.
- 치료 카드가 0개일 때: 해당 상품에 분석기가 다루는 담보가 없을 수 있습니다. 탭 상단에 안내 메시지가 표시됩니다 (예: 암 전용 상품에서는 2대담보 탭이 비게 됨).

## 두 분석기의 차이

| 항목 | 암 분석 | 2대담보 분석 |
|------|---------|--------------|
| 카드 분해 기준 | 치료 방식 (표적/면역/양성자) | 치료 단계 (진단/수술/혈전/스텐트) |
| 상품 매칭 | 4개 상품 타입별 프리셋 | `generic_2major` 단일 프리셋 (fallback) |
| 감액 표기 | `min(max)` 형태 | 단일 금액 (follow_coverage_amount) |
| 카드 색상 | 적색 계열 | 뇌혈관=남색 / 심장=적색 |

## 배포

Streamlit Cloud 배포 시 폴더 전체를 GitHub 레포에 push하고 `app.py`를 엔트리포인트로 지정하면 됩니다. `config/` 및 `templates/` 하위 폴더는 `app.py`의 `_find_asset_dir()`가 자동으로 탐색합니다.
