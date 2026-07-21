import json
import re
from openai import OpenAI

MODEL = "gpt-5.6-luna"

CHECKLIST_PROMPT = """당신은 공공기관 제안서 평가위원입니다.
아래 RFP 요구사항과 평가배점을 기준으로 제안서 초안을 검토하고, 감점 및 누락 체크리스트를 작성하세요.

검토 관점:
1. 요구사항 누락 — RFP에 명시된 요구사항이 초안에 빠져 있는지
2. 배점 대비 분량 — 배점이 높은 항목의 초안이 충분히 상세한지
3. 형식 오류 — 구체성 부족, 수치 미제시, 모호한 표현
4. 차별성 — 경쟁사 대비 차별화 포인트가 명확한지
5. 일정·산출물 — 일정과 산출물이 구체적으로 제시되었는지

중요:
- "section" 필드는 반드시 아래 [섹션 제목 목록]에 있는 문자열 중 하나와 글자 단위로 정확히 일치해야 합니다. 소제목, 요약, 의역한 이름을 절대 사용하지 마세요.
- 각 항목에서 문제가 감지된 위치를 섹션명과 단락 번호로 정확히 명시하세요.
- 단락 번호는 해당 섹션 내에서 위에서부터 순서대로 1번 단락, 2번 단락 형식으로 표기하세요.
- 아래 제공된 제안서 초안은 완전한 텍스트입니다. 문장이나 문단이 임의로 잘려 있지 않으므로 "문장 마무리 미비"·"내용 잘림" 같은 지적은 하지 마세요.
- 실제로 문장 부호가 없거나 서술이 중간에 끊어진 경우에만 "형식 오류"로 판단하세요.

[섹션 제목 목록] (section 필드는 반드시 이 중 하나와 정확히 일치):
{section_titles}

출력 형식 (JSON만):
{{
  "summary": "전반적인 초안 품질 평가 (2~3문장)",
  "score_estimate": "예상 평가 점수 (예: 80/100)",
  "checklist": [
    {{
      "category": "요구사항누락|분량부족|형식오류|차별성부족|일정·산출물",
      "status": "pass|warning|fail",
      "item": "체크 항목",
      "section": "해당 섹션명",
      "paragraph": "몇 번째 단락 (예: 3번째 단락, 또는 섹션 전체)",
      "quote": "문제가 감지된 원문에서 정확히 복사한 20~80자 스니펫 (반드시 초안 원문과 글자 단위로 일치. status가 pass인 경우 빈 문자열)",
      "detail": "구체적인 지적 내용 및 개선 방향"
    }}
  ]
}}

RFP 요구사항:
{requirements}

평가배점:
{scores}

제안서 초안:
{draft}
"""


def generate_checklist(rfp_result: dict, sections_draft: dict, api_key: str) -> dict:
    client = OpenAI(api_key=api_key)

    draft_text = ""
    for title, content in sections_draft.items():
        draft_text += f"\n\n## {title}\n{content}"

    section_titles = "\n".join(f"- {t}" for t in sections_draft.keys())

    prompt = CHECKLIST_PROMPT.format(
        requirements=json.dumps(rfp_result.get("requirements", []), ensure_ascii=False),
        scores=json.dumps(rfp_result.get("evaluation_scores", []), ensure_ascii=False),
        draft=draft_text,
        section_titles=section_titles,
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        return {"error": str(e), "checklist": []}

    parsed = _parse_json(raw)
    return parsed if parsed else {"error": "JSON 파싱 실패", "raw": raw, "checklist": []}


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
