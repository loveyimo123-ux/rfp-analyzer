import json
import re
from openai import OpenAI

MODEL = "gpt-5.6-luna"

RESEARCH_PROMPT = """당신은 공공기관 제안서 작성을 위한 자료조사 전문가입니다.
아래 제안서 섹션에 필요한 자료를 조사하세요.

[검색 기준]
- 반드시 최신 자료 (2023년 이후) 우선
- 공식 출처 우선: 정부부처 공식사이트(.go.kr), 국회/법제처, 통계청, 한국행정연구원, 공공기관 보고서
- 법령·고시는 국가법령정보센터(law.go.kr) 기준
- 통계는 KOSIS(kosis.kr), e-나라지표(index.go.kr) 등 공식 통계 포털 기준
- 뉴스·블로그·개인 사이트는 출처로 사용 금지

[수집 항목] 섹션당 아래 4가지 각 1~2건:
1. 정책·법령: 관련 법률명, 조항, 정부 지침·고시
2. 통계·수치: 최신 공식 통계 (연도 명시 필수)
3. 유사사례: 타 기관 유사 사업 공식 보고서·백서
4. 기술동향: 관련 기술 표준, 국가 R&D 보고서

출력 형식 (JSON만, 코드블록 없이):
{{
  "section": "{section_title}",
  "findings": [
    {{
      "category": "정책·법령|통계·수치|유사사례|기술동향",
      "title": "자료 제목",
      "content": "핵심 내용 (2~3문장, 수치·연도 포함)",
      "source_name": "기관명 (예: 국토교통부, 통계청)",
      "source_url": "실제 원문 URL (반드시 https://로 시작하는 직접 링크)"
    }}
  ]
}}

섹션명: {section_title}
소제목: {subsections}
RFP 요구사항: {requirements}
"""


def generate_research(rfp_result: dict, toc: dict, api_key: str) -> list[dict]:
    """각 섹션별 자료조사."""
    client = OpenAI(api_key=api_key)
    sections = toc.get("toc", [])
    results = []

    for sec in sections:
        prompt = RESEARCH_PROMPT.format(
            section_title=sec["title"],
            subsections=", ".join(sec.get("subsections", [])),
            requirements=json.dumps(rfp_result.get("requirements", [])[:15], ensure_ascii=False),
        )
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""
            parsed = _parse_json(raw)
            if not parsed:
                parsed = {"section": sec["title"], "findings": []}
        except Exception as e:
            parsed = {"section": sec["title"], "findings": [], "error": str(e)}

        results.append(parsed)

    return results


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    start = cleaned.find("{")
    if start == -1:
        return {}
    end = cleaned.rfind("}") + 1
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError:
        return {}
