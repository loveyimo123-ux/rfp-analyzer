import re
import json as _json
import streamlit as st
import streamlit.components.v1 as components
from hwp_parser import extract_text
from gemini_extractor import extract_rfp_info
from proposal_generator import generate_toc, generate_section, generate_matrix
from research_generator import generate_research
from checklist_generator import generate_checklist
from document_generator import generate_proposal_word
from presentation_generator import generate_ppt, generate_qa_word

st.set_page_config(
    page_title="RFP 분석기",
    page_icon="📄",
    layout="wide",
)


# ── 3단계 초안 ↔ 6단계 체크리스트 위치 하이라이트 헬퍼 ────────────────────────

def _split_paragraphs(content: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", content.strip())
    return [b for b in blocks if b.strip()]


def _inline_md(text: str) -> str:
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


def _block_to_html(block: str) -> str:
    lines_html = []
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            lines_html.append(f"<div style='font-weight:700;font-size:1.05em;margin:4px 0'>{_inline_md(stripped[4:])}</div>")
        elif stripped.startswith("## "):
            lines_html.append(f"<div style='font-weight:700;font-size:1.15em;margin:4px 0'>{_inline_md(stripped[3:])}</div>")
        elif stripped.startswith("# "):
            lines_html.append(f"<div style='font-weight:700;font-size:1.25em;margin:4px 0'>{_inline_md(stripped[2:])}</div>")
        elif stripped.startswith(("- ", "* ")):
            lines_html.append(f"<div style='margin-left:1em'>• {_inline_md(stripped[2:])}</div>")
        elif re.match(r"^\d+\.\s", stripped):
            lines_html.append(f"<div style='margin-left:1em'>{_inline_md(stripped)}</div>")
        else:
            lines_html.append(f"<div>{_inline_md(stripped)}</div>")
    return "".join(lines_html)


def _norm(s: str) -> str:
    return re.sub(r"[\s\d\.\-·]+", "", str(s or "")).lower()


def _find_quote_block_idx(blocks: list[str], quote: str) -> int | None:
    if not quote:
        return None
    q = quote.strip()
    for i, b in enumerate(blocks):
        if q in b:
            return i
    q_norm = re.sub(r"\s+", "", q)
    for i, b in enumerate(blocks):
        if q_norm and q_norm in re.sub(r"\s+", "", b):
            return i
    if len(q) >= 15:
        prefix = q[:15]
        for i, b in enumerate(blocks):
            if prefix in b:
                return i
    return None


def _highlight_quote_in_block(block: str, quote: str) -> str:
    html = _block_to_html(block)
    if not quote:
        return html
    q = quote.strip().replace("<", "&lt;").replace(">", "&gt;")
    if q in html:
        return html.replace(
            q,
            f'<span style="background:#ffeb3b;padding:0 2px;font-weight:600">{q}</span>',
            1,
        )
    return html


def _render_section_draft(title: str, content: str, jump_target: dict | None):
    """quote 기반으로 정확한 위치를 찾아 형광펜 하이라이트."""
    blocks = _split_paragraphs(content)

    target_sec = jump_target.get("section") if jump_target else None
    is_target = jump_target and (
        target_sec == title
        or _norm(target_sec) == _norm(title)
        or _norm(target_sec) in _norm(title)
        or _norm(title) in _norm(target_sec)
    )

    target_idx = None
    quote = ""
    if is_target:
        quote = (jump_target.get("quote") or "").strip()
        if quote:
            target_idx = _find_quote_block_idx(blocks, quote)
        if target_idx is None:
            para_raw = jump_target.get("para_num")
            if para_raw and 1 <= para_raw <= len(blocks):
                target_idx = para_raw - 1

    marked_once = False
    for idx, block in enumerate(blocks):
        if is_target and target_idx == idx:
            anchor = ' id="jump-mark"' if not marked_once else ""
            marked_once = True
            inner = _highlight_quote_in_block(block, quote)
            st.markdown(
                f'<div{anchor} style="background:#fff59d;padding:8px 10px;'
                f'border-radius:4px;border-left:4px solid #fbc02d;margin:6px 0">{inner}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(block)

    if is_target and not marked_once:
        # 위치 특정 실패 → 섹션 최상단에 앵커만 (하이라이트 없음)
        st.markdown('<div id="jump-mark" style="height:1px"></div>', unsafe_allow_html=True)


def _render_return_button():
    """6단계로 돌아가기 FAB + Streamlit 버튼."""
    # JS로 FAB 삽입 (스크롤만 담당, 하이라이트 원복은 Streamlit 버튼이 처리)
    components.html(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            var existing = doc.getElementById("return-fab");
            if (existing) existing.remove();

            var btn = doc.createElement("button");
            btn.id = "return-fab";
            btn.title = "6단계 체크리스트로 돌아가기";
            btn.innerHTML = "&#x2193;";
            btn.style.cssText = [
                "position:fixed",
                "right:28px",
                "bottom:32px",
                "width:56px",
                "height:56px",
                "border-radius:50%",
                "background:#1a73e8",
                "color:white",
                "border:none",
                "box-shadow:0 4px 14px rgba(0,0,0,0.35)",
                "font-size:26px",
                "font-weight:bold",
                "cursor:pointer",
                "z-index:2147483647",
                "display:flex",
                "align-items:center",
                "justify-content:center",
                "line-height:1",
                "padding:0"
            ].join(";");
            btn.onmouseover = function() { btn.style.background = "#1557b0"; };
            btn.onmouseout  = function() { btn.style.background = "#1a73e8"; };
            btn.onclick = function() {
                btn.style.display = "none";
                var anchor = doc.getElementById("checklist-anchor");
                if (anchor) anchor.scrollIntoView({behavior: "smooth", block: "start"});
                // Streamlit의 return 버튼을 자동 클릭하여 하이라이트 원복
                setTimeout(function() {
                    var stBtns = doc.querySelectorAll('button[kind="secondary"]');
                    for (var i = 0; i < stBtns.length; i++) {
                        if (stBtns[i].innerText.indexOf("하이라이트 해제") >= 0) {
                            stBtns[i].click();
                            break;
                        }
                    }
                }, 800);
            };
            doc.body.appendChild(btn);
        })();
        </script>
        """,
        height=1,
    )
    # 숨겨진 Streamlit 버튼 (FAB 클릭 시 JS가 이 버튼을 찾아 클릭)
    st.button("하이라이트 해제", key="return_to_checklist", on_click=_on_return_click,
              help="형광펜 해제 후 6단계로 복귀")


def _scroll_to_jump_mark(section_title: str):
    """JS로 해당 탭 버튼 클릭 + 앵커로 스크롤. 렌더링 타이밍 대응을 위해 재시도."""
    target_json = _json.dumps(section_title)
    components.html(
        f"""
        <script>
        (function() {{
            var doc = window.parent.document;
            var target = {target_json};

            function clickTab() {{
                var tabs = doc.querySelectorAll('[role="tab"]');
                for (var i = 0; i < tabs.length; i++) {{
                    var label = (tabs[i].innerText || tabs[i].textContent || "").trim();
                    if (label === target) {{
                        tabs[i].click();
                        return true;
                    }}
                }}
                return false;
            }}

            var tabTries = 0;
            var tabTimer = setInterval(function() {{
                if (clickTab() || ++tabTries > 15) clearInterval(tabTimer);
            }}, 200);

            // 스크롤 재시도 (최대 6초)
            var scrollTries = 0;
            var scrollTimer = setInterval(function() {{
                var mark = doc.getElementById("jump-mark");
                if (mark) {{
                    mark.scrollIntoView({{behavior: "smooth", block: "center"}});
                    // 한 번 더 (탭 전환 후 위치 재보정)
                    setTimeout(function() {{
                        var m2 = doc.getElementById("jump-mark");
                        if (m2) m2.scrollIntoView({{behavior: "smooth", block: "center"}});
                    }}, 500);
                    clearInterval(scrollTimer);
                }} else if (++scrollTries > 30) {{
                    clearInterval(scrollTimer);
                }}
            }}, 200);
        }})();
        </script>
        """,
        height=1,
    )

st.title("📄 RFP 분석기")

# ── jump 콜백 ────────────────────────────────────────────────────────────────

def _stage_header(title: str):
    st.markdown(
        f'<div style="background:#E1F5FE;color:#111111;'
        f'padding:12px 20px;border-radius:8px;font-size:1.2em;font-weight:700;'
        f'margin:8px 0 12px 0;letter-spacing:0.5px">{title}</div>',
        unsafe_allow_html=True,
    )


def _on_jump_click(sec: str, para_num: int | None, quote: str):
    st.session_state["jump_target"] = {"section": sec, "para_num": para_num, "quote": quote}
    st.session_state["_just_jumped"] = True


def _on_return_click():
    st.session_state.pop("jump_target", None)
    st.session_state["_remove_fab"] = True

# ── 사이드바: API 키 ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    _saved_key = st.secrets.get("GEMINI_API_KEY", "")
    if _saved_key and _saved_key != "여기에_API_키_입력":
        api_key = _saved_key
        st.success("API Key 로드됨 ✓", icon="🔑")
    else:
        api_key = st.text_input(
            "Gemini API Key",
            type="password",
            placeholder="AIza...",
            help=".streamlit/secrets.toml 에 저장하면 다음부터 자동 입력됩니다.",
        )

# ── 파일 업로드 ───────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader("HWP 파일을 선택하세요", type=["hwp", "hwpx"])

if uploaded_file is None:
    st.info("아직 업로드된 파일이 없습니다.")
    st.stop()

# ── 텍스트 추출 ───────────────────────────────────────────────────────────────
with st.spinner("텍스트 추출 중..."):
    file_bytes = uploaded_file.read()
    text, debug_log = extract_text(file_bytes, uploaded_file.name)

is_error = text.startswith("ERR:") or not text.strip()

if is_error:
    # 오류 코드 파싱
    ERROR_META = {
        "ENCRYPTED":   ("🔒", "암호화된 문서"),
        "CORRUPT":     ("💥", "손상된 파일"),
        "IMAGE_BASED": ("🖼️", "이미지 기반 문서"),
        "EMPTY":       ("📭", "빈 문서"),
        "OLD_FORMAT":  ("📼", "구버전 HWP"),
        "UNSUPPORTED": ("🚫", "지원하지 않는 형식"),
        "UNKNOWN":     ("⚠️", "알 수 없는 오류"),
    }
    if text.startswith("ERR:"):
        code, _, msg = text[4:].partition("|")
    else:
        code, msg = "UNKNOWN", text

    icon, label = ERROR_META.get(code, ("⚠️", "오류"))
    st.error(f"{icon} **파싱 실패 — {label}**\n\n{msg}")

    with st.expander("🔍 파싱 진단 로그"):
        for line in debug_log:
            st.code(line, language=None)
    st.stop()
else:
    st.success(f"텍스트 파싱 성공 — {len(text):,}자 추출됨 ({round(uploaded_file.size / 1024, 1)} KB)")

if not api_key:
    st.info("사이드바에 Gemini API Key를 입력해주세요.")
    st.stop()

# ── 1. RFP 분석 ───────────────────────────────────────────────────────────────
st.divider()
_stage_header("📋 1단계 — RFP 핵심 정보 추출")

if st.button("✨ RFP 분석 시작", type="primary"):
    with st.spinner("Gemini 분석 중..."):
        try:
            result, raw_response = extract_rfp_info(text, api_key)
            st.session_state["rfp_result"] = result
            st.session_state.pop("toc", None)
            st.session_state.pop("sections", None)
            st.session_state.pop("matrix", None)
        except Exception as e:
            import traceback
            st.error(f"Gemini 호출 오류: {e}")
            st.code(traceback.format_exc(), language="python")
            st.stop()

if "rfp_result" in st.session_state:
    result = st.session_state["rfp_result"]

    if not result:
        st.warning("JSON 파싱 실패.")
    else:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["📋 요구사항", "📊 평가배점", "📁 제출서류", "📅 일정"]
        )
        with tab1:
            for i, item in enumerate(result.get("requirements", []), 1):
                st.markdown(f"**{i}.** {item}")
        with tab2:
            scores = result.get("evaluation_scores", [])
            if scores:
                st.table(scores)
        with tab3:
            for i, doc in enumerate(result.get("required_documents", []), 1):
                st.markdown(f"**{i}.** {doc}")
        with tab4:
            schedule = result.get("schedule", [])
            if schedule:
                st.table(schedule)

    # ── 2. 목차 설계 ─────────────────────────────────────────────────────────
    st.divider()
    _stage_header("📑 2단계 — 목차 자동 설계")
    st.caption("배점 높은 항목을 앞에 배치하는 최적 목차를 생성합니다.")

    if st.button("목차 생성", type="primary"):
        with st.spinner("목차 설계 중..."):
            try:
                toc = generate_toc(result, api_key)
                st.session_state["toc"] = toc
                st.session_state.pop("sections", None)
                st.session_state.pop("matrix", None)
            except Exception as e:
                st.error(f"목차 생성 오류: {e}")

    if "toc" in st.session_state:
        toc = st.session_state["toc"]
        sections = toc.get("toc", [])

        if sections:
            for sec in sections:
                priority_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sec.get("priority", ""), "⚪")
                with st.expander(f"{sec['order']}. {sec['title']}  {priority_color}  `{sec.get('score_basis', '')}`"):
                    for sub in sec.get("subsections", []):
                        st.markdown(f"- {sub}")

        # ── 3. 섹션 초안 ─────────────────────────────────────────────────────
        st.divider()
        _stage_header("✍️ 3단계 — 섹션별 초안 작성")
        st.caption("목차의 각 섹션에 대해 Gemini가 초안을 생성합니다.")

        if st.button("초안 생성 시작", type="primary"):
            sections_draft = {}
            progress = st.progress(0, text="초안 작성 중...")
            for idx, sec in enumerate(sections):
                progress.progress((idx) / len(sections), text=f"[{idx+1}/{len(sections)}] {sec['title']} 작성 중...")
                try:
                    draft = generate_section(sec, result, api_key)
                    sections_draft[sec["title"]] = draft
                except Exception as e:
                    sections_draft[sec["title"]] = f"생성 오류: {e}"
            progress.progress(1.0, text="완료!")
            st.session_state["sections"] = sections_draft

        if "sections" in st.session_state:
            sections_draft = st.session_state["sections"]
            jump_target = st.session_state.get("jump_target")
            just_jumped = st.session_state.pop("_just_jumped", False)

            draft_tabs = st.tabs(list(sections_draft.keys()))
            for i, (tab, (title, content)) in enumerate(zip(draft_tabs, sections_draft.items())):
                with tab:
                    _render_section_draft(title, content, jump_target)
                    st.download_button(
                        f"📥 {title} 다운로드",
                        data=content.encode("utf-8"),
                        file_name=f"{title}.md",
                        mime="text/markdown",
                        key=f"dl_{title}_{i}",
                    )

            # ── 4. 요구사항 대응표 ───────────────────────────────────────────
            st.divider()
            _stage_header("🗂️ 4단계 — 요구사항 대응표")
            st.caption("발주처 요건과 작성된 섹션을 1:1 매핑하고 빠진 항목을 표시합니다.")

            if st.button("대응표 생성", type="primary"):
                with st.spinner("대응표 생성 중..."):
                    try:
                        matrix = generate_matrix(result, toc, api_key)
                        st.session_state["matrix"] = matrix
                    except Exception as e:
                        st.error(f"대응표 생성 오류: {e}")

            if "matrix" in st.session_state:
                matrix = st.session_state["matrix"]
                rows = matrix.get("matrix", [])
                if rows:
                    import pandas as pd
                    df = pd.DataFrame(rows)

                    # 미충족 항목 강조
                    def highlight(row):
                        if row.get("coverage") == "미충족":
                            return ["background-color: #ffe0e0"] * len(row)
                        elif row.get("coverage") == "부분충족":
                            return ["background-color: #fff7e0"] * len(row)
                        return [""] * len(row)

                    st.caption("💡 note가 끝까지 안 보일 때는 해당 칸을 더블클릭하세요.")
                    st.dataframe(
                        df.style.apply(highlight, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )

                    missing = [r for r in rows if r.get("coverage") == "미충족"]
                    partial = [r for r in rows if r.get("coverage") == "부분충족"]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("전체 요구사항", len(rows))
                    c2.metric("미충족 항목", len(missing), delta=f"-{len(missing)}" if missing else None, delta_color="inverse")
                    c3.metric("부분충족 항목", len(partial))


            # ── Phase 4-1. 자료조사 ──────────────────────────────────────────
            st.divider()
            _stage_header("🔍 5단계 — 자료조사")
            st.caption("Google Search 그라운딩으로 정책·법령·통계·유사사례·기술동향을 섹션별로 수집합니다.")

            if st.button("자료조사 시작", type="primary"):
                research_results = []
                progress = st.progress(0, text="자료조사 중...")
                for idx, sec in enumerate(sections):
                    progress.progress(idx / len(sections), text=f"[{idx+1}/{len(sections)}] {sec['title']} 조사 중...")
                    try:
                        res = generate_research(result, {"toc": [sec]}, api_key)
                        research_results.extend(res)
                    except Exception as e:
                        research_results.append({"section": sec["title"], "findings": [], "error": str(e)})
                progress.progress(1.0, text="완료!")
                st.session_state["research"] = research_results

            if "research" in st.session_state:
                CATEGORY_ICON = {
                    "정책·법령": "📜",
                    "통계·수치": "📊",
                    "유사사례": "🏛️",
                    "기술동향": "💡",
                }
                for sec_data in st.session_state["research"]:
                    findings = sec_data.get("findings", [])
                    web_sources = sec_data.get("web_sources", [])
                    with st.expander(f"**{sec_data.get('section', '')}**  — {len(findings)}건", expanded=False):
                        if sec_data.get("error"):
                            st.error(sec_data["error"])
                        if findings:
                            for i, f in enumerate(findings):
                                icon = CATEGORY_ICON.get(f.get("category", ""), "📌")
                                border = "border-top:1px solid #f0f0f0;" if i > 0 else ""
                                import urllib.parse
                                src_name = f.get("source_name") or f.get("source", "")
                                title_text = f.get("title", "")
                                query = urllib.parse.quote(f"{title_text} {src_name}".strip())
                                src_url = f"https://www.google.com/search?q={query}"
                                label = src_name or "출처 검색"
                                esc_url = src_url.replace("'", "\\'")
                                esc_label = label.replace('"', '&quot;')
                                st.markdown(f"""
<div style="padding:8px 2px;{border}">
  <div style="font-weight:600;font-size:0.92em;margin-bottom:3px">{icon} [{f.get('category','')}] {f.get('title','')}</div>
  <div style="color:#333;font-size:0.87em;line-height:1.55;margin-bottom:3px">{f.get('content','')}</div>
</div>""", unsafe_allow_html=True)
                                components.html(
                                    f'''<a href="#" onclick="window.open('{esc_url}','_blank');return false;"
                                        style="color:#1a73e8;font-size:13px;text-decoration:none;
                                        cursor:pointer;display:inline-block;padding:3px 8px;
                                        border-radius:4px;background:#e8f0fe;font-family:sans-serif">
                                        📎 {esc_label}</a>''',
                                    height=30,
                                )
                        else:
                            st.info("수집된 자료가 없습니다.")

                        # 실제 검색된 웹 출처 링크
                        if web_sources:
                            valid_ws = [ws for ws in web_sources if ws.get("url")]
                            if valid_ws:
                                links_items = "".join(
                                    f'<a href="#" onclick="window.open(\'{ws["url"]}\',\'_blank\');return false;" '
                                    f'style="display:block;color:#1a73e8;font-size:13px;'
                                    f'padding:3px 0;text-decoration:none;word-break:break-all;'
                                    f'font-family:sans-serif;cursor:pointer">'
                                    f'🔗 {ws.get("title") or ws["url"]}</a>'
                                    for ws in valid_ws
                                )
                                components.html(
                                    f'<div style="padding:8px 10px;background:#f8f9fa;border-radius:6px">'
                                    f'<div style="font-size:12px;color:#555;margin-bottom:4px">검색 참조 출처</div>'
                                    f'{links_items}</div>',
                                    height=32 + 22 * len(valid_ws),
                                )

            # ── Phase 4-2. 감점·누락 체크리스트 ─────────────────────────────
            st.divider()
            _stage_header("✅ 6단계 — 감점·누락 체크리스트")
            st.caption("평가위원 관점에서 초안을 검토하고 감점 요소와 누락 항목을 체크합니다.")

            if st.button("체크리스트 생성", type="primary"):
                with st.spinner("평가위원 관점 검토 중..."):
                    try:
                        checklist_result = generate_checklist(result, sections_draft, api_key)
                        st.session_state["checklist"] = checklist_result
                    except Exception as e:
                        st.error(f"체크리스트 생성 오류: {e}")

            if "checklist" in st.session_state:
                cl = st.session_state["checklist"]

                if cl.get("error"):
                    st.error(cl["error"])
                    if cl.get("raw"):
                        st.code(cl["raw"])
                else:
                    # 요약 및 예상 점수
                    col_s, col_sc = st.columns([3, 1])
                    with col_s:
                        st.info(cl.get("summary", ""))
                    with col_sc:
                        st.metric("예상 점수", cl.get("score_estimate", "-"))

                    # 체크리스트 테이블
                    rows = cl.get("checklist", [])
                    if rows:
                        STATUS_ICON = {"pass": "✅", "warning": "⚠️", "fail": "❌"}
                        CATEGORY_BADGE = {
                            "요구사항누락": "c0392b",
                            "분량부족":     "e67e22",
                            "형식오류":     "2980b9",
                            "차별성부족":   "8e44ad",
                            "일정·산출물":  "27ae60",
                        }

                        # 통계 요약 (최상단)
                        c1, c2, c3 = st.columns(3)
                        c1.metric("❌ 감점", sum(1 for r in rows if r.get("status") == "fail"))
                        c2.metric("⚠️ 주의", sum(1 for r in rows if r.get("status") == "warning"))
                        c3.metric("✅ 통과", sum(1 for r in rows if r.get("status") == "pass"))

                        # 6단계 섹션 앵커 (하단 return 버튼에서 스크롤 대상)
                        st.markdown('<div id="checklist-anchor"></div>', unsafe_allow_html=True)

                        for status_filter, label in [("fail", "❌ 감점 항목"), ("warning", "⚠️ 주의 항목"), ("pass", "✅ 통과 항목")]:
                            filtered = [r for r in rows if r.get("status") == status_filter]
                            if not filtered:
                                continue
                            with st.expander(f"{label}  ({len(filtered)}건)", expanded=(status_filter == "fail")):
                                for i, r in enumerate(filtered):
                                    cat = r.get("category", "")
                                    badge_color = CATEGORY_BADGE.get(cat, "888888")
                                    sec = r.get("section", "")
                                    para = r.get("paragraph", "")
                                    icon = STATUS_ICON.get(r.get("status"), "")
                                    border = "border-top:1px solid #f0f0f0;" if i > 0 else ""
                                    row_key = f"jump_{status_filter}_{i}"

                                    st.markdown(f"""
<div style="padding:8px 2px 0 2px;{border}">
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:2px">
    <span>{icon}</span>
    <span style="font-weight:600;font-size:0.95em">{r.get('item','')}</span>
    <span style="background:#{badge_color};color:white;padding:1px 8px;border-radius:10px;font-size:0.72em">{cat}</span>
  </div>
</div>""", unsafe_allow_html=True)

                                    # 통과 항목은 위치 이동 버튼 미표시
                                    if sec and status_filter != "pass":
                                        m = re.search(r"\d+", para)
                                        para_num = int(m.group()) if m else None
                                        quote_val = r.get("quote", "")
                                        loc_label = f"📍 {sec} — {para}" if para else f"📍 {sec}"
                                        st.button(
                                            loc_label,
                                            key=f"jmp_{status_filter}_{i}",
                                            on_click=_on_jump_click,
                                            args=(sec, para_num, quote_val),
                                            help="3단계 초안에서 해당 위치로 이동",
                                        )

                                    st.markdown(
                                        f'<div style="color:#444;font-size:0.85em;line-height:1.5;padding:0 2px 6px 2px">{r.get("detail","")}</div>',
                                        unsafe_allow_html=True,
                                    )


            # ── Phase 5. 산출물 생성 ─────────────────────────────────────────
            st.divider()
            _stage_header("📦 7단계 — 산출물 생성")

            base_name = uploaded_file.name.rsplit(".", 1)[0]
            col_w, col_p, col_qa = st.columns(3)

            with col_w:
                st.markdown("#### 📝 Word 제안서")
                st.caption("목차 · 섹션 초안 · 대응표 · 배점표 포함 완성형 문서")
                if st.button("Word 생성", use_container_width=True):
                    with st.spinner("Word 생성 중..."):
                        try:
                            word_bytes = generate_proposal_word(
                                base_name, result, toc, sections_draft,
                                st.session_state.get("matrix", {}),
                            )
                            st.session_state["word_bytes"] = word_bytes
                        except Exception as e:
                            st.error(f"Word 생성 오류: {e}")
                if "word_bytes" in st.session_state:
                    st.download_button(
                        "📥 제안서.docx 다운로드",
                        data=st.session_state["word_bytes"],
                        file_name=f"{base_name}_제안서.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                        key="dl_word",
                    )

            with col_p:
                st.markdown("#### 📊 PPT 발표자료")
                st.caption("Gemini가 섹션별 핵심 불릿 요약 후 슬라이드 생성")
                if st.button("PPT 생성", use_container_width=True):
                    with st.spinner("PPT 생성 중..."):
                        try:
                            ppt_bytes = generate_ppt(base_name, toc, sections_draft, result, api_key)
                            st.session_state["ppt_bytes"] = ppt_bytes
                        except Exception as e:
                            st.error(f"PPT 생성 오류: {e}")
                if "ppt_bytes" in st.session_state:
                    st.download_button(
                        "📥 발표자료.pptx 다운로드",
                        data=st.session_state["ppt_bytes"],
                        file_name=f"{base_name}_발표자료.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        use_container_width=True,
                        key="dl_ppt",
                    )

            with col_qa:
                st.markdown("#### 💬 예상 질의응답")
                st.caption("평가위원 관점 예상 질문 15개 + 모범 답변 Word 문서")
                if st.button("Q&A 생성", use_container_width=True):
                    with st.spinner("질의응답 생성 중..."):
                        try:
                            qa_bytes = generate_qa_word(result, toc, sections_draft, api_key)
                            st.session_state["qa_bytes"] = qa_bytes
                        except Exception as e:
                            st.error(f"Q&A 생성 오류: {e}")
                if "qa_bytes" in st.session_state:
                    st.download_button(
                        "📥 예상질의응답.docx 다운로드",
                        data=st.session_state["qa_bytes"],
                        file_name=f"{base_name}_예상질의응답.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True,
                        key="dl_qa",
                    )

            # ── 페이지 최하단: jump 스크롤 + FAB ──────────────────────────
            if st.session_state.pop("_remove_fab", False):
                components.html(
                    """<script>
                    var fab = window.parent.document.getElementById("return-fab");
                    if (fab) fab.remove();
                    </script>""",
                    height=1,
                )
            elif jump_target:
                if just_jumped:
                    _jt_sec = jump_target.get("section", "")
                    _scroll_title = _jt_sec
                    for t in sections_draft.keys():
                        if (t == _jt_sec
                            or _norm(t) == _norm(_jt_sec)
                            or _norm(_jt_sec) in _norm(t)
                            or _norm(t) in _norm(_jt_sec)):
                            _scroll_title = t
                            break
                    _scroll_to_jump_mark(_scroll_title)
                _render_return_button()
