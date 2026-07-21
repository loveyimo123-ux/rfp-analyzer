import json
import re
from google import genai

MODEL = "gemini-3.1-flash-lite"

PROMPT = """다음은 RFP(제안요청서) 문서 텍스트입니다.
아래 4가지 항목을 추출해서 JSON만 반환하세요. 코드블록(```)도 빼고 순수 JSON만 출력하세요.

추출 항목:
1. requirements       : 기술/기능/사업 요구사항 목록 (문자열 배열)
2. evaluation_scores  : 평가 항목과 배점 (객체 배열, 키: item / score)
3. required_documents : 필수 제출서류 목록 (문자열 배열)
4. schedule           : 주요 일정 (객체 배열, 키: date / event)

출력 형식 (이것만 출력):
{
  "requirements": ["...", "..."],
  "evaluation_scores": [{"item": "...", "score": "..."}],
  "required_documents": ["...", "..."],
  "schedule": [{"date": "...", "event": "..."}]
}

문서 텍스트:
"""


def extract_rfp_info(text: str, api_key: str) -> tuple[dict, str]:
    client = genai.Client(api_key=api_key)

    contents = PROMPT + text[:30000]

    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
    )

    try:
        raw = response.text or ""
    except Exception:
        if response.candidates:
            parts = response.candidates[0].content.parts
            raw = "".join(p.text for p in parts if hasattr(p, "text"))
        else:
            raw = ""
    parsed = _parse_json(raw)
    return parsed, raw


def _parse_json(raw: str) -> dict:
    # 코드블록 제거
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

    # { } 범위 추출
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        return {}

    json_str = cleaned[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}
