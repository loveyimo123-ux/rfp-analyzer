import json
import re
from google import genai

MODEL = "gemini-3.1-flash-lite"

# ── 공통 ──────────────────────────────────────────────────────────────────────

def _client(api_key: str):
    return genai.Client(api_key=api_key)


def _call(client, prompt: str) -> str:
    response = client.models.generate_content(model=MODEL, contents=prompt)
    try:
        return response.text or ""
    except Exception:
        if response.candidates:
            parts = response.candidates[0].content.parts
            return "".join(p.text for p in parts if hasattr(p, "text"))
        return ""


def _parse_json(raw: str) -> dict | list:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    start = cleaned.find("{") if "{" in cleaned else cleaned.find("[")
    if start == -1:
        return {}
    end = cleaned.rfind("}") + 1 if cleaned[start] == "{" else cleaned.rfind("]") + 1
    try:
        return json.loads(cleaned[start:end])
    except json.JSONDecodeError:
        return {}


# ── 1단계: 목차 자동 설계 ─────────────────────────────────────────────────────

TOC_PROMPT = """당신은 공공기관 제안서 작성 전문가입니다.
아래 RFP 분석 데이터를 바탕으로 제안서 목차를 설계하세요.

규칙:
- 배점이 높은 항목일수록 앞에 배치하세요.
- 각 섹션에는 소제목(subsections)을 2~4개 포함하세요.
- 표준 제안서 섹션(사업이해, 추진전략, 수행방법, 추진일정, 품질관리, 투입조직, 기대효과 등)을 기반으로 하되, 배점 구조에 맞게 조정하세요.
- 순수 JSON만 출력하세요.

출력 형식:
{{
  "toc": [
    {{
      "order": 1,
      "title": "섹션 제목",
      "subsections": ["소제목1", "소제목2"],
      "score_basis": "관련 배점 항목 및 점수",
      "priority": "high|medium|low"
    }}
  ]
}}

RFP 데이터:
평가배점: {scores}
요구사항: {requirements}
"""


def generate_toc(rfp_result: dict, api_key: str) -> dict:
    client = _client(api_key)
    prompt = TOC_PROMPT.format(
        scores=json.dumps(rfp_result.get("evaluation_scores", []), ensure_ascii=False),
        requirements=json.dumps(rfp_result.get("requirements", []), ensure_ascii=False),
    )
    raw = _call(client, prompt)
    return _parse_json(raw)


# ── 2단계: 섹션 초안 작성 ────────────────────────────────────────────────────

SECTION_PROMPT = """당신은 공공기관 제안서 작성 전문가입니다.
아래 정보를 바탕으로 제안서의 [{title}] 섹션 초안을 작성하세요.

규칙:
- 소제목({subsections})별로 내용을 구성하세요.
- 발주처 요구사항과 평가기준을 반영하여 설득력 있게 작성하세요.
- 구체적인 방법론, 수치, 일정을 포함하세요.
- 분량: 각 소제목당 3~5문단.
- 마크다운 형식으로 작성하세요.

RFP 컨텍스트:
요구사항: {requirements}
평가기준: {scores}
일정: {schedule}

이 섹션의 배점 근거: {score_basis}
"""


def generate_section(section: dict, rfp_result: dict, api_key: str) -> str:
    client = _client(api_key)
    prompt = SECTION_PROMPT.format(
        title=section["title"],
        subsections=", ".join(section.get("subsections", [])),
        requirements=json.dumps(rfp_result.get("requirements", [])[:20], ensure_ascii=False),
        scores=json.dumps(rfp_result.get("evaluation_scores", []), ensure_ascii=False),
        schedule=json.dumps(rfp_result.get("schedule", []), ensure_ascii=False),
        score_basis=section.get("score_basis", ""),
    )
    return _call(client, prompt)


# ── 3단계: 요구사항 대응표 ────────────────────────────────────────────────────

MATRIX_PROMPT = """당신은 공공기관 제안서 검토 전문가입니다.
발주처 요구사항 목록과 작성된 제안서 섹션 목록을 대조하여 요구사항 대응표를 만드세요.

규칙:
- 각 요구사항이 어느 섹션에서 다루어지는지 매핑하세요.
- coverage: "충족" / "부분충족" / "미충족" 중 하나로 판단하세요.
- 미충족 항목에는 note에 보완 방향을 적으세요.
- 순수 JSON만 출력하세요.

출력 형식:
{{
  "matrix": [
    {{
      "requirement": "요구사항 내용",
      "section": "대응 섹션 제목 (없으면 '-')",
      "coverage": "충족|부분충족|미충족",
      "note": "보완 필요 사항 또는 비고"
    }}
  ]
}}

요구사항 목록:
{requirements}

제안서 섹션 목록:
{sections}
"""


def generate_matrix(rfp_result: dict, toc: dict, api_key: str) -> dict:
    client = _client(api_key)
    section_titles = [s["title"] for s in toc.get("toc", [])]
    prompt = MATRIX_PROMPT.format(
        requirements=json.dumps(rfp_result.get("requirements", []), ensure_ascii=False),
        sections=json.dumps(section_titles, ensure_ascii=False),
    )
    raw = _call(client, prompt)
    return _parse_json(raw)
