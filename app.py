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
from database import save_record, update_record, list_records, load_record, delete_record

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
    # 1) 완전 일치
    for i, b in enumerate(blocks):
        if q in b:
            return i
    # 2) 공백 제거 일치
    q_norm = re.sub(r"\s+", "", q)
    for i, b in enumerate(blocks):
        if q_norm and q_norm in re.sub(r"\s+", "", b):
            return i
    # 3) 앞 15자 일치
    if len(q) >= 15:
        for i, b in enumerate(blocks):
            if q[:15] in b:
                return i
    # 4) 뒤 15자 일치
    if len(q) >= 15:
        for i, b in enumerate(blocks):
            if q[-15:] in b:
                return i
    # 5) 단어 단위 부분 일치 (공백 제거 후 앞 10자)
    if len(q_norm) >= 10:
        for i, b in enumerate(blocks):
            if q_norm[:10] in re.sub(r"\s+", "", b):
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

    for idx, block in enumerate(blocks):
        if is_target and target_idx == idx:
            inner = _highlight_quote_in_block(block, quote)
            st.markdown(
                f'<div style="background:#fff59d;padding:8px 10px;'
                f'border-radius:4px;border-left:4px solid #fbc02d;margin:6px 0">{inner}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(block)


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


st.title("📄 RFP 분석기")

# ── jump 콜백 ────────────────────────────────────────────────────────────────

def _stage_header(title: str):
    st.markdown(
        f'<div style="background:#E1F5FE;color:#111111;'
        f'padding:12px 20px;border-radius:8px;font-size:1.2em;font-weight:700;'
        f'margin:8px 0 12px 0;letter-spacing:0.5px">{title}</div>',
        unsafe_allow_html=True,
    )


def _on_jump_click(sec: str, para_num: int | None, quote: str, checklist_group: str):
    st.session_state["jump_target"] = {"section": sec, "para_num": para_num, "quote": quote}
    # 위치 이동으로 화면이 다시 그려져도, 6단계에서 열어 둔 그룹을 기억한다.
    st.session_state["_open_checklist_group"] = checklist_group
    st.session_state["_just_jumped"] = True
    st.session_state["_jump_seq"] = st.session_state.get("_jump_seq", 0) + 1


def _on_return_click():
    st.session_state.pop("jump_target", None)
    st.session_state["_restore_checklist_group"] = True
    st.session_state["_remove_fab"] = True


def _render_memo_widget():
    """드래그 → 우클릭 → 메모 저장/조회 기능. localStorage 기반으로 세션 영향 없음."""
    components.html(
        """
        <script>
        (function() {
            var doc = window.parent.document;
            var STORAGE_KEY = 'rfp_memos';

            // 이미 이벤트를 등록한 뒤 다시 그려진 경우에는 리스너를 중복 등록하지 않고
            // 사라진 메모 마커만 다시 그린다.
            if (doc.__rfpMemoReady) {
                if (typeof doc.__rfpRenderMemos === 'function') {
                    setTimeout(doc.__rfpRenderMemos, 150);
                }
                return;
            }
            doc.__rfpMemoReady = true;

            function loadMemos() {
                try { return JSON.parse(window.parent.localStorage.getItem(STORAGE_KEY) || '[]'); } catch(e) { return []; }
            }
            function saveMemos(memos) {
                try {
                    window.parent.localStorage.setItem(STORAGE_KEY, JSON.stringify(memos));
                } catch(e) {
                    console.warn('메모 저장에 실패했습니다.', e);
                }
            }

            // ── 마커 렌더링 ──
            function renderMarkers() {
                doc.querySelectorAll('.rfp-memo-marker').forEach(function(el) { el.remove(); });
                var memos = loadMemos();
                memos.forEach(function(m, idx) {
                    var container = null;
                    try {
                        var walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
                        var node;
                        while (node = walker.nextNode()) {
                            if (node.textContent.includes(m.quote.substring(0, 15))) {
                                container = node.parentElement;
                                break;
                            }
                        }
                    } catch(e) {}

                    var span = doc.createElement('span');
                    span.className = 'rfp-memo-marker';
                    span.style.cssText = 'color:#e74c3c;font-weight:bold;cursor:pointer;font-size:1.1em;user-select:none;display:inline';
                    span.textContent = ' ✱';
                    span.title = (m.comments && m.comments[0]) || m.memo || '';
                    ;(function(capturedIdx) {
                        span.onclick = function(e) {
                            e.stopPropagation();
                            var cx = e.clientX, cy = e.clientY;
                            showMemoPopup(loadMemos()[capturedIdx], cx, cy, capturedIdx);
                        };
                    })(idx);

                    if (container) {
                        container.appendChild(span);
                    } else {
                        span.style.cssText += ';position:fixed;right:' + (20 + idx * 22) + 'px;top:60px;z-index:2147483640';
                        doc.body.appendChild(span);
                    }
                });
            }
            // 다음 Streamlit 재실행 때도 이 함수를 호출할 수 있도록 부모 문서에 보관한다.
            doc.__rfpRenderMemos = renderMarkers;

            // ── 팝업 공통 ──
            function createPopup(x, y) {
                closePopup();
                var popup = doc.createElement('div');
                popup.id = 'rfp-memo-popup';
                var pw = 290;
                var px = Math.min(x, (window.parent.innerWidth || 800) - pw - 16);
                var py = Math.min(y, (window.parent.innerHeight || 600) - 320);
                popup.style.cssText = [
                    'position:fixed','left:'+px+'px','top:'+py+'px',
                    'width:'+pw+'px','background:white',
                    'border:1px solid #ddd','border-radius:12px',
                    'box-shadow:0 6px 24px rgba(0,0,0,0.18)',
                    'padding:14px','z-index:2147483647','font-family:sans-serif'
                ].join(';');
                doc.body.appendChild(popup);
                return popup;
            }
            function closePopup() {
                var p = doc.getElementById('rfp-memo-popup');
                if (p) p.remove();
                var m = doc.getElementById('rfp-context-menu');
                if (m) m.remove();
            }

            // ── 메모 조회 팝업 ──
            function showMemoPopup(m, x, y, idx) {
                if (!m) return;
                var popup = createPopup(x, y);

                var hdr = doc.createElement('div');
                hdr.style.cssText = 'font-weight:700;font-size:13px;color:#1a73e8;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #eee';
                hdr.textContent = '💬 메모';
                popup.appendChild(hdr);

                var qd = doc.createElement('div');
                qd.style.cssText = 'background:#fff9c4;border-left:3px solid #fbc02d;padding:5px 8px;font-size:11px;color:#666;margin-bottom:10px;border-radius:3px';
                qd.textContent = '"' + (m.quote||'').substring(0,80) + '"';
                popup.appendChild(qd);

                var list = doc.createElement('div');
                list.style.cssText = 'max-height:160px;overflow-y:auto;margin-bottom:10px';
                (m.comments || [m.memo]).forEach(function(c) {
                    var item = doc.createElement('div');
                    item.style.cssText = 'background:#f8f9fa;border-radius:8px;padding:7px 10px;margin-bottom:6px;font-size:12px;color:#222;line-height:1.5';
                    item.textContent = c;
                    list.appendChild(item);
                });
                popup.appendChild(list);

                var row = doc.createElement('div');
                row.style.cssText = 'display:flex;gap:6px';
                var inp = doc.createElement('textarea');
                inp.placeholder = '댓글 추가...';
                inp.rows = 2;
                inp.style.cssText = 'flex:1;border:1px solid #ddd;border-radius:6px;padding:5px 8px;font-size:12px;resize:none;font-family:sans-serif';
                var addBtn = doc.createElement('button');
                addBtn.textContent = '추가';
                addBtn.style.cssText = 'background:#1a73e8;color:white;border:none;border-radius:6px;padding:5px 10px;cursor:pointer;font-size:12px;align-self:flex-end';
                addBtn.onclick = function() {
                    var txt = inp.value.trim();
                    if (!txt) return;
                    var memos = loadMemos();
                    if (!memos[idx]) return;
                    if (!memos[idx].comments) memos[idx].comments = [memos[idx].memo];
                    memos[idx].comments.push(txt);
                    saveMemos(memos);
                    showMemoPopup(memos[idx], x, y, idx);
                    renderMarkers();
                };
                row.appendChild(inp);
                row.appendChild(addBtn);
                popup.appendChild(row);

                var delBtn = doc.createElement('button');
                delBtn.textContent = '메모 삭제';
                delBtn.style.cssText = 'margin-top:8px;background:none;border:none;color:#e74c3c;cursor:pointer;font-size:11px;padding:0';
                delBtn.onclick = function() {
                    var memos = loadMemos();
                    memos.splice(idx, 1);
                    saveMemos(memos);
                    closePopup();
                    renderMarkers();
                };
                popup.appendChild(delBtn);
            }

            // ── 새 메모 작성 팝업 ──
            function showNewMemoPopup(quote, x, y) {
                var popup = createPopup(x, y);

                var hdr = doc.createElement('div');
                hdr.style.cssText = 'font-weight:700;font-size:13px;color:#1a73e8;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #eee';
                hdr.textContent = '📝 새 메모';
                popup.appendChild(hdr);

                var qd = doc.createElement('div');
                qd.style.cssText = 'background:#fff9c4;border-left:3px solid #fbc02d;padding:5px 8px;font-size:11px;color:#666;margin-bottom:10px;border-radius:3px';
                qd.textContent = '"' + quote.substring(0,80) + '"';
                popup.appendChild(qd);

                var ta = doc.createElement('textarea');
                ta.placeholder = '메모를 입력하세요...';
                ta.rows = 4;
                ta.style.cssText = 'width:100%;border:1px solid #ddd;border-radius:6px;padding:6px 8px;font-size:12px;resize:none;font-family:sans-serif;box-sizing:border-box';
                popup.appendChild(ta);

                var btnRow = doc.createElement('div');
                btnRow.style.cssText = 'display:flex;gap:6px;margin-top:10px;justify-content:flex-end';

                var cancelBtn = doc.createElement('button');
                cancelBtn.textContent = '취소';
                cancelBtn.style.cssText = 'background:#f5f5f5;border:1px solid #ddd;border-radius:6px;padding:5px 14px;cursor:pointer;font-size:12px';
                cancelBtn.onclick = closePopup;

                var saveBtn = doc.createElement('button');
                saveBtn.textContent = '저장';
                saveBtn.style.cssText = 'background:#1a73e8;color:white;border:none;border-radius:6px;padding:5px 16px;cursor:pointer;font-size:13px;font-weight:600';
                saveBtn.onclick = function() {
                    var txt = ta.value.trim();
                    if (!txt) return;
                    var memos = loadMemos();
                    memos.push({ quote: quote, memo: txt, comments: [txt] });
                    saveMemos(memos);
                    closePopup();
                    renderMarkers();
                };

                btnRow.appendChild(cancelBtn);
                btnRow.appendChild(saveBtn);
                popup.appendChild(btnRow);
                setTimeout(function() { ta.focus(); }, 50);
            }

            // ── 우클릭 이벤트 ──
            doc.addEventListener('contextmenu', function(e) {
                var sel = doc.getSelection ? doc.getSelection() : null;
                var quote = sel ? sel.toString().trim() : '';
                if (!quote || quote.length < 2) return;

                e.preventDefault();
                closePopup();

                var cx = e.clientX, cy = e.clientY;
                var menu = doc.createElement('div');
                menu.id = 'rfp-context-menu';
                menu.style.cssText = [
                    'position:fixed','left:'+cx+'px','top:'+cy+'px',
                    'background:white','border:1px solid #ddd',
                    'border-radius:8px','box-shadow:0 3px 12px rgba(0,0,0,0.15)',
                    'z-index:2147483647','overflow:hidden','font-family:sans-serif'
                ].join(';');

                var item = doc.createElement('div');
                item.textContent = '💬 메모';
                item.style.cssText = 'padding:10px 18px;cursor:pointer;font-size:13px;color:#222;white-space:nowrap';
                item.onmouseenter = function() { item.style.background = '#e8f0fe'; };
                item.onmouseleave = function() { item.style.background = 'white'; };
                ;(function(capturedQuote, capturedX, capturedY) {
                    item.onclick = function(ev) {
                        ev.stopPropagation();
                        menu.remove();
                        showNewMemoPopup(capturedQuote, capturedX, capturedY);
                    };
                })(quote, cx, cy);

                menu.appendChild(item);
                doc.body.appendChild(menu);

                setTimeout(function() {
                    function _close(ev) {
                        if (!menu.contains(ev.target)) {
                            menu.remove();
                            doc.removeEventListener('click', _close);
                        }
                    }
                    doc.addEventListener('click', _close);
                }, 100);
            });

            // 팝업 외부 클릭 닫기
            doc.addEventListener('click', function(e) {
                var popup = doc.getElementById('rfp-memo-popup');
                if (popup && !popup.contains(e.target)) closePopup();
            });

            // 초기 마커 렌더링
            setTimeout(renderMarkers, 800);
        })();
        </script>
        """,
        height=1,
    )

# ── 사이드바: API 키 + 업로드 기록 ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    _saved_key = st.secrets.get("OPENAI_API_KEY", "")
    if _saved_key and _saved_key != "여기에_API_키_입력":
        api_key = _saved_key
        st.success("API Key 로드됨 ✓", icon="🔑")
    else:
        api_key = st.text_input(
            "OpenAI API Key",
            type="password",
            placeholder="sk-...",
            help=".streamlit/secrets.toml 에 저장하면 다음부터 자동 입력됩니다.",
        )

    st.divider()
    st.subheader("📂 업로드 기록")
    records = list_records(20)
    if records:
        for rec in records:
            col_a, col_b = st.columns([4, 1])
            with col_a:
                if st.button(
                    f"📄 {rec['filename']}\n{rec['upload_time']}",
                    key=f"rec_{rec['id']}",
                    use_container_width=True,
                ):
                    st.session_state["load_record_id"] = rec["id"]
                    st.rerun()
            with col_b:
                if st.button("🗑️", key=f"del_{rec['id']}", help="삭제"):
                    delete_record(rec["id"])
                    st.rerun()
    else:
        st.caption("저장된 기록이 없습니다.")

# ── 저장된 기록 불러오기 ──────────────────────────────────────────────────────
if "load_record_id" in st.session_state:
    _rid = st.session_state.pop("load_record_id")
    _rec = load_record(_rid)
    if _rec:
        st.session_state.pop("rfp_result", None)
        st.session_state.pop("toc", None)
        st.session_state.pop("sections", None)
        st.session_state.pop("matrix", None)
        st.session_state.pop("research", None)
        st.session_state.pop("checklist", None)
        if _rec.get("rfp_result"):
            st.session_state["rfp_result"] = _rec["rfp_result"]
        if _rec.get("toc"):
            st.session_state["toc"] = _rec["toc"]
        if _rec.get("sections"):
            st.session_state["sections"] = _rec["sections"]
        if _rec.get("matrix"):
            st.session_state["matrix"] = _rec["matrix"]
        if _rec.get("research"):
            st.session_state["research"] = _rec["research"]
        if _rec.get("checklist"):
            st.session_state["checklist"] = _rec["checklist"]
        if _rec.get("memos"):
            st.session_state["memos"] = _rec["memos"]
        st.session_state["_record_id"] = _rid
        st.session_state["_record_filename"] = _rec["filename"]
        st.success(f"'{_rec['filename']}' 기록을 불러왔습니다.")

# ── 파일 업로드 ───────────────────────────────────────────────────────────────
uploaded_file = st.file_uploader("HWP 파일을 선택하세요", type=["hwp", "hwpx"])

if uploaded_file is None:
    if "rfp_result" not in st.session_state:
        st.info("아직 업로드된 파일이 없습니다.")
        st.stop()
    # 기록에서 불러온 경우 — 가상 파일명으로 진행
    uploaded_file = None
    text = ""
    debug_log = []
    _from_record = True
else:
    _from_record = False

if not _from_record:
    # ── 텍스트 추출 ──────────────────────────────────────────────────────────
    with st.spinner("텍스트 추출 중..."):
        file_bytes = uploaded_file.read()
        text, debug_log = extract_text(file_bytes, uploaded_file.name)

is_error = not _from_record and (text.startswith("ERR:") or not text.strip())

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
elif _from_record:
    _rec_name = st.session_state.get("_record_filename", "불러온 파일")
    st.info(f"📂 저장된 기록: **{_rec_name}**")
else:
    st.success(f"텍스트 파싱 성공 — {len(text):,}자 추출됨 ({round(uploaded_file.size / 1024, 1)} KB)")
    # 신규 업로드 → DB에 기록 저장
    if st.session_state.get("_last_uploaded") != uploaded_file.name:
        rid = save_record(uploaded_file.name, uploaded_file.size, len(text))
        st.session_state["_record_id"] = rid
        st.session_state["_last_uploaded"] = uploaded_file.name

if not api_key:
    st.info("사이드바에 OpenAI API Key를 입력해주세요.")
    st.stop()

# ── 1. RFP 분석 ───────────────────────────────────────────────────────────────
st.divider()
_stage_header("📋 1단계 — RFP 핵심 정보 추출")

if st.button("✨ RFP 분석 시작", type="primary"):
    with st.spinner("OpenAI 분석 중..."):
        try:
            result, raw_response = extract_rfp_info(text, api_key)
            st.session_state["rfp_result"] = result
            st.session_state.pop("toc", None)
            st.session_state.pop("sections", None)
            st.session_state.pop("matrix", None)
            if "_record_id" in st.session_state:
                update_record(st.session_state["_record_id"], rfp_result=result)
        except Exception as e:
            import traceback
            st.error(f"OpenAI 호출 오류: {e}")
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
                if "_record_id" in st.session_state:
                    update_record(st.session_state["_record_id"], toc=toc)
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
        st.caption("목차의 각 섹션에 대해 AI가 초안을 생성합니다.")

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
            if "_record_id" in st.session_state:
                update_record(st.session_state["_record_id"], sections=sections_draft)

        if "sections" in st.session_state:
            sections_draft = st.session_state["sections"]
            jump_target = st.session_state.get("jump_target")
            just_jumped = st.session_state.pop("_just_jumped", False)

            # ── 점프: quote 기반으로 실제 섹션 결정 + 탭 자동 전환 ──
            if jump_target:
                _jt_sec = jump_target.get("section", "")
                _jt_quote = (jump_target.get("quote") or "").strip()
                _jt_quote_norm = re.sub(r"\s+", "", _jt_quote)
                _resolved_title = None

                if _jt_quote:
                    for _t, _c in sections_draft.items():
                        _c_norm = re.sub(r"\s+", "", _c)
                        if (_jt_quote in _c
                                or _jt_quote_norm in _c_norm
                                or (len(_jt_quote) >= 12 and _jt_quote[:12] in _c)
                                or (len(_jt_quote_norm) >= 10 and _jt_quote_norm[:10] in _c_norm)):
                            _resolved_title = _t
                            break

                if _resolved_title is None:
                    for _t, _c in sections_draft.items():
                        if (_t == _jt_sec or _norm(_t) == _norm(_jt_sec)
                                or _norm(_jt_sec) in _norm(_t) or _norm(_t) in _norm(_jt_sec)):
                            _resolved_title = _t
                            break

                if _resolved_title:
                    jump_target["section"] = _resolved_title

                if just_jumped and _resolved_title:
                    _esc = _resolved_title.replace("\\", "\\\\").replace("'", "\\'")
                    _nonce = _json.dumps(str(st.session_state.get("_jump_seq", 0)))
                    components.html(
                        f"""
                        <!-- nonce: {_nonce} -->
                        <script>
                        (function() {{
                            var doc = window.parent.document;
                            function activate() {{
                                var tabs = doc.querySelectorAll('[role="tab"]');
                                for (var i = 0; i < tabs.length; i++) {{
                                    if (tabs[i].textContent.indexOf('{_esc}') >= 0) {{
                                        tabs[i].click();
                                        return;
                                    }}
                                }}
                            }}
                            function scrollTo() {{
                                // RGB로 스타일된 하이라이트 블록 찾기: background: rgb(255, 245, 157)
                                var els = doc.querySelectorAll('div[style*="background"]');
                                for (var i = 0; i < els.length; i++) {{
                                    var st = els[i].getAttribute('style') || '';
                                    if (st.indexOf('rgb(255, 245, 157)') >= 0 || st.indexOf('255, 245, 157') >= 0) {{
                                        els[i].scrollIntoView({{behavior:'smooth',block:'center'}});
                                        return true;
                                    }}
                                }}
                                return false;
                            }}
                            function run() {{
                                activate();
                                setTimeout(function() {{ if (!scrollTo()) setTimeout(scrollTo, 500); }}, 300);
                            }}
                            setTimeout(run, 200);
                            setTimeout(run, 1000);
                        }})();
                        </script>
                        """,
                        height=0,
                    )

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
                        if "_record_id" in st.session_state:
                            update_record(st.session_state["_record_id"], matrix=matrix)
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

                    missing = [r for r in rows if r.get("coverage") == "미충족"]
                    partial = [r for r in rows if r.get("coverage") == "부분충족"]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("전체 요구사항", len(rows))
                    c2.metric("미충족 항목", len(missing), delta=f"-{len(missing)}" if missing else None, delta_color="inverse")
                    c3.metric("부분충족 항목", len(partial))

                    st.caption("💡 note가 끝까지 안 보일 때는 해당 칸을 더블클릭하세요.")
                    st.dataframe(
                        df.style.apply(highlight, axis=1),
                        use_container_width=True,
                        hide_index=True,
                    )


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
                if "_record_id" in st.session_state:
                    update_record(st.session_state["_record_id"], research=research_results)

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
                        if "_record_id" in st.session_state:
                            update_record(st.session_state["_record_id"], checklist=checklist_result)
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

                        open_checklist_group = st.session_state.get("_open_checklist_group")
                        restore_checklist_group = st.session_state.pop("_restore_checklist_group", False)

                        for status_filter, label in [("fail", "❌ 감점 항목"), ("warning", "⚠️ 주의 항목"), ("pass", "✅ 통과 항목")]:
                            filtered = [r for r in rows if r.get("status") == status_filter]
                            if not filtered:
                                continue
                            # 복귀 직후에는 이동 버튼을 눌렀던 그룹을 다시 연다.
                            # 일반 진입 시에는 기존 동작대로 감점 그룹을 기본으로 연다.
                            is_expanded = (
                                status_filter == open_checklist_group
                                if restore_checklist_group and open_checklist_group
                                else status_filter == "fail"
                            )
                            with st.expander(f"{label}  ({len(filtered)}건)", expanded=is_expanded):
                                for i, r in enumerate(filtered):
                                    cat = r.get("category", "")
                                    badge_color = CATEGORY_BADGE.get(cat, "888888")
                                    sec = r.get("section", "")
                                    para = r.get("paragraph", "")
                                    icon = STATUS_ICON.get(r.get("status"), "")
                                    border = "border-top:1px solid #f0f0f0;" if i > 0 else ""
                                    row_key = f"jump_{status_filter}_{i}"

                                    badge_html = (
                                        f'<span style="background:#{badge_color};color:white;padding:1px 8px;border-radius:10px;font-size:0.72em">{cat}</span>'
                                        if status_filter != "pass" else ""
                                    )
                                    st.markdown(f"""
<div style="padding:8px 2px 0 2px;{border}">
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:2px">
    <span>{icon}</span>
    <span style="font-weight:600;font-size:0.95em">{r.get('item','')}</span>
    {badge_html}
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
                                            args=(sec, para_num, quote_val, status_filter),
                                            help="3단계 초안에서 해당 위치로 이동",
                                        )

                                    st.markdown(
                                        f'<div style="color:#444;font-size:0.85em;line-height:1.5;padding:0 2px 6px 2px">{r.get("detail","")}</div>',
                                        unsafe_allow_html=True,
                                    )


            # ── Phase 5. 산출물 생성 ─────────────────────────────────────────
            st.divider()
            _stage_header("📦 7단계 — 산출물 생성")

            if uploaded_file is not None:
                _fname = uploaded_file.name
            else:
                _fname = st.session_state.get("_record_filename", "제안서")
            base_name = _fname.rsplit(".", 1)[0]
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
                st.caption("AI가 섹션별 핵심 불릿 요약 후 슬라이드 생성")
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

            # ── 메모 기능 ────────────────────────────────────────────────────
            _render_memo_widget()

            # ── 페이지 최하단: 6단계로 복귀 FAB ──────────────────────────
            # (스크롤은 미리보기 박스 바로 아래에서 이미 1회 수행됨)
            if st.session_state.pop("_remove_fab", False):
                components.html(
                    """<script>
                    var fab = window.parent.document.getElementById("return-fab");
                    if (fab) fab.remove();
                    </script>""",
                    height=1,
                )
            elif jump_target:
                _render_return_button()
