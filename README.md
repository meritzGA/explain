# 메리츠 가입제안서 → 고객용 보장 요약 변환기

메리츠 가입제안서 PDF를 업로드하면 **이벤트 기반 고객용 보장 요약**을
자동으로 HTML로 만들어주는 도구입니다. 지점장이 상담 자료로 바로 쓸 수
있도록 설계되었습니다.

## 빠른 시작

```bash
# 의존성 설치
pip install -r requirements.txt

# 실행
streamlit run app.py
```

브라우저가 자동으로 열리면 PDF를 드래그 앤 드롭해서 올리시면 됩니다.

## 파일 구조

```
meritz_event_converter/
├── app.py                  # Streamlit UI + 이벤트 매퍼 + 렌더러
├── extractor.py            # pypdf 기반 PDF 파서
├── config/
│   └── events.json         # 이벤트 매핑 룰 (담보명 → 이벤트 버킷)
├── templates/
│   └── report.html         # Jinja2 HTML 템플릿 (출력 디자인)
└── requirements.txt
```

## 작동 방식

1. **PDF 업로드** (`app.py`)
2. **담보 추출** (`extractor.py`) — pypdf로 텍스트 추출 후 정규식으로
   고객정보, 계약정보, 담보 리스트(이름·가입금액·보험료)를 뽑아냅니다.
   담보 테이블이 여러 페이지에 걸친 경우(박주영 건: 3~5페이지)도 처리합니다.
3. **이벤트 매핑** (`app.py::map_to_events`) — `config/events.json`의
   이벤트 순서대로 담보명 정규식 매칭을 시도합니다. 먼저 매칭되는
   이벤트가 담보를 선점합니다.
4. **HTML 렌더링** (`templates/report.html`) — Jinja2로 디자인된
   템플릿에 데이터를 주입합니다.
5. **결과 표시 및 다운로드** — Streamlit 내부에 HTML을 inline으로
   렌더링하고, HTML 파일 다운로드 버튼을 제공합니다.

## 성능

5개 실제 제안서로 테스트한 결과:

| PDF | 담보 개수 | 페이지 | 처리 시간 |
|-----|----------|--------|----------|
| 박주영 (5.10.5) | 62 | 25 | 3.0초 |
| LI GUANG XUN (5.10.5) | 12 | 15 | 1.3초 |
| 김기현 (간편31) | 12 | 13 | 1.2초 |
| 김태은 (통합간편) | 18 | 16 | 2.0초 |
| 변상규 (암보험) | 20 | - | 2.0초 |

두 번째 업로드부터는 파일 해시 캐싱으로 즉시 재렌더됩니다.

## 이벤트 매핑 룰 (`config/events.json`)

13개 이벤트 버킷이 정의되어 있고, **순서가 중요**합니다:

1. **minor_cancer** (유사암) — "유사암진단비", "유사암수술비"
2. **brain_vascular** (뇌혈관) — "뇌혈관", "뇌졸중", "뇌출혈"
3. **ischemic_heart** (허혈성심장) — "허혈성심장", "급성심근경색"
4. **circulatory_system** (특정순환계)
5. **cancer_treatment** (암 치료) — "암 통합치료비", "항암", "다빈치로봇", "표적항암"
6. **cancer_diagnosis** (암 진단) — "암진단비", "통합암진단비"
7. **transplant** (장기이식)
8. **fracture_burn** (골절·화상)
9. **hospital_stay** (입원)
10. **injury_death_disability** (상해 사망·후유장해)
11. **premium_waiver** (보험료 납입지원)
12. **benign_tumor** (양성뇌종양)
13. **general_surgery** (일반 수술비)

각 이벤트는 `include_any`(정규식 리스트 중 하나라도 매칭되면 포함),
`exclude_any`(매칭되면 제외)로 담보 할당 조건을 정의합니다.

새로운 담보가 등장하거나 매핑이 틀리면 `events.json`만 고치면 됩니다.

## 알려진 이슈 및 개선사항

**MVP에서는 의도적으로 단순화한 부분들:**

1. **배타 담보 합산 문제** — 김기현 건의 "통합암진단비" 5개 카테고리는
   실제로는 한 가지 암 진단시 하나만 지급되지만, 현재는 단순 합산해서
   "최대 1억원"으로 표기됩니다. 실제로는 "어떤 암이든 2,000만원" 구조.
   `calculation_mode: "max_of_alternatives"` 같은 플래그 추가로 해결 예정.

2. **보험료 납입지원** — 김기현 건의 "유사암 진단시 월 21,455원" 같은
   특수 지급 구조가 현재는 "0원"으로 표시됩니다.
   special handling 필요.

3. **"안내참조" 금액 담보** — 금액이 "안내참조"인 담보들은 세부 페이지에
   실제 금액이 기재되어 있지만, 현재는 파싱하지 않습니다.

4. **중복 지급 vs 배타 지급** — 같은 이벤트 내에서 모든 담보가
   중복 지급되는 것처럼 단순 합산되지만, 실제로는 일부 담보가 배타적입니다.
   예: 간병인 담보 vs 간호간병통합서비스. `exclusive_pairs` 필드가
   정의는 되어 있지만 계산 로직에서 아직 사용하지 않습니다.

5. **컨셉 설명 히어로 섹션** — 김기현 건 디자인 iteration에서 만든
   "이 제안서가 담고 있는 이야기" 상단 컨셉 박스가 아직 없습니다.
   Day 2에서 `config/products.json` + `templates.json`로 추가 예정.

## Day 2, Day 3 계획

- **Day 2**: 상품별 컨셉 템플릿 매칭 (`config/products.json`,
  `config/templates.json`). 상단 히어로 박스와 각 카드의 "이 보장의 의미"
  추가. 하이라이트 박스(납입면제 혜택 등) 자동 생성.

- **Day 3**: `@media print` CSS 고도화 (페이지 나눔, 흑백 옵션),
  PDF 다운로드 기능 (WeasyPrint 사용), Streamlit Cloud 배포.

## 배포 (Day 3 예정)

```bash
# GitHub 리포 생성 후 push
git init
git add .
git commit -m "Day 1 MVP"
git remote add origin https://github.com/<user>/meritz_event_converter
git push -u origin main

# Streamlit Cloud에서 리포 연결
# → 자동 배포
```

배포시 `packages.txt`에 CJK 폰트 추가 필요할 수 있음 (WeasyPrint 사용시):
```
fonts-noto-cjk
```

## 로컬 테스트 (CLI)

extractor만 따로 테스트하려면:

```bash
python extractor.py /path/to/proposal.pdf
```

JSON 형식으로 고객·계약·담보 정보가 출력됩니다.
