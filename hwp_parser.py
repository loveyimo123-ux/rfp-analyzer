import io
import zlib
import struct
import zipfile
import re
from xml.etree import ElementTree as ET


def extract_text(file_bytes: bytes, filename: str) -> tuple[str, list[str]]:
    """
    Returns (extracted_text, debug_log).
    실패 시 text는 'ERR:코드|설명' 형식.
    """
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "hwpx":
        text, log = _extract_hwpx(file_bytes)
    elif ext == "hwp":
        text, log = _extract_hwp(file_bytes)
    else:
        return "ERR:UNSUPPORTED|지원하지 않는 파일 형식입니다 (.hwp / .hwpx만 가능).", []

    # 성공
    if text.strip() and not text.startswith("ERR:"):
        return text, log

    # 실패 원인 분류
    error_msg = _classify_error(file_bytes, ext, text, log)
    return error_msg, log


def _classify_error(file_bytes: bytes, ext: str, raw_msg: str, log: list[str]) -> str:
    joined_log = " ".join(log).lower()

    # 1. 암호화 파일
    if ext == "hwp":
        try:
            import olefile, struct
            ole = olefile.OleFileIO(io.BytesIO(file_bytes))
            if ole.exists("FileHeader"):
                hdr = ole.openstream("FileHeader").read()
                if len(hdr) >= 40:
                    flags = struct.unpack_from("<I", hdr, 36)[0]
                    if flags & 0x02:  # bit 1 = 암호화
                        ole.close()
                        return "ERR:ENCRYPTED|암호화된 문서입니다. 암호를 해제한 후 다시 업로드해주세요."
            ole.close()
        except Exception:
            pass

    # 2. OLE 구조 자체가 손상
    if "ole 파일 열기 실패" in raw_msg.lower() or "not a compound document" in joined_log:
        return "ERR:CORRUPT|파일이 손상되었거나 올바른 HWP 형식이 아닙니다."

    # 3. 이미지 기반 (텍스트 레이어 없음) — 파일 크기는 크지만 텍스트 없음
    if len(file_bytes) > 50_000 and ("텍스트를 찾을 수 없습니다" in raw_msg):
        return "ERR:IMAGE_BASED|이미지 기반 문서로 텍스트를 읽을 수 없습니다. 스캔 파일이거나 그림으로만 구성된 경우 OCR이 필요합니다."

    # 4. 빈 문서
    if len(file_bytes) < 5_000 or "텍스트를 찾을 수 없습니다" in raw_msg:
        return "ERR:EMPTY|문서에 텍스트 내용이 없습니다. 빈 문서이거나 내용이 도형·표 안에만 있을 수 있습니다."

    # 5. 압축 해제 실패 (구버전 HWP 3.x 등)
    if "압축 해제 실패" in joined_log and "section0" not in joined_log:
        return "ERR:OLD_FORMAT|지원하지 않는 구버전 HWP 형식일 수 있습니다. HWP 2002 이상 버전으로 다시 저장 후 업로드해주세요."

    # 6. 기타
    return f"ERR:UNKNOWN|텍스트 추출에 실패했습니다. ({raw_msg})"


# ── HWPX (ZIP + XML) ─────────────────────────────────────────────────────────

def _extract_hwpx(file_bytes: bytes) -> tuple[str, list[str]]:
    log = []
    paragraphs = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            all_names = zf.namelist()
            log.append(f"ZIP 내 파일 목록: {all_names}")

            # Contents/section*.xml 찾기
            section_files = sorted(
                n for n in all_names
                if re.match(r".*[Ss]ection\d*\.xml$", n)
                and "Content" in n
            )
            log.append(f"섹션 파일: {section_files}")

            if not section_files:
                # fallback: 모든 xml에서 텍스트 태그 탐색
                section_files = [n for n in all_names if n.endswith(".xml")]
                log.append(f"fallback 섹션 파일: {section_files}")

            for name in section_files:
                with zf.open(name) as f:
                    content = f.read()
                tree = ET.fromstring(content)
                # 네임스페이스 무관하게 로컬 태그명 't' 탐색
                found = []
                for elem in tree.iter():
                    local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if local == "t" and elem.text:
                        found.append(elem.text)
                log.append(f"{name}: {len(found)}개 텍스트 조각 발견")
                paragraphs.extend(found)

    except Exception as e:
        log.append(f"오류: {e}")
        return f"HWPX 파싱 오류: {e}", log

    text = "\n".join(paragraphs)
    return (text if text.strip() else "텍스트를 찾을 수 없습니다."), log


# ── HWP binary (OLE + zlib) ──────────────────────────────────────────────────

_HWPTAG_PARA_TEXT = 67  # 0x43


def _extract_hwp(file_bytes: bytes) -> tuple[str, list[str]]:
    log = []
    try:
        import olefile
    except ImportError:
        msg = "olefile 패키지가 필요합니다: pip install olefile"
        return msg, [msg]

    try:
        ole = olefile.OleFileIO(io.BytesIO(file_bytes))
    except Exception as e:
        return f"OLE 파일 열기 실패: {e}", [str(e)]

    streams = ole.listdir()
    log.append(f"OLE 스트림 목록: {['/'.join(s) for s in streams[:20]]}")

    is_compressed, compress_log = _hwp_check_compression(ole)
    log.extend(compress_log)
    log.append(f"압축 여부: {is_compressed}")

    paragraphs = []
    i = 0
    while ole.exists(f"BodyText/Section{i}"):
        raw = ole.openstream(f"BodyText/Section{i}").read()
        log.append(f"Section{i}: raw {len(raw)} bytes")

        if is_compressed:
            data, decomp_log = _decompress(raw, i)
            log.extend(decomp_log)
        else:
            data = raw
            log.append(f"Section{i}: 비압축 사용")

        if data:
            found = _parse_section(data)
            log.append(f"Section{i}: {len(found)}개 문단 파싱")
            paragraphs.extend(found)
        else:
            log.append(f"Section{i}: 압축 해제 실패")
        i += 1

    if i == 0:
        log.append("BodyText/Section0 스트림 없음 — 스트림명 확인 필요")

    ole.close()
    text = "\n".join(paragraphs)
    return (text if text.strip() else "텍스트를 찾을 수 없습니다."), log


def _hwp_check_compression(ole) -> tuple[bool, list[str]]:
    log = []
    if ole.exists("FileHeader"):
        header = ole.openstream("FileHeader").read()
        log.append(f"FileHeader 크기: {len(header)} bytes")
        if len(header) >= 40:
            flags = struct.unpack_from("<I", header, 36)[0]
            log.append(f"FileHeader flags: 0x{flags:08X}")
            # bit 0 = 압축, bit 1 = 암호화
            compressed = bool(flags & 0x01)
            log.append(f"압축 bit(0x01): {compressed}")
            return compressed, log
    log.append("FileHeader 없음 → 기본값 True(압축)")
    return True, log


def _decompress(data: bytes, section_idx: int) -> tuple[bytes | None, list[str]]:
    log = []
    # wbits 47 = zlib + gzip auto, 15 = zlib, -15 = raw deflate
    for wbits in (15, -15, 47):
        try:
            result = zlib.decompress(data, wbits)
            log.append(f"Section{section_idx}: wbits={wbits}로 압축 해제 성공 → {len(result)} bytes")
            return result, log
        except zlib.error as e:
            log.append(f"Section{section_idx}: wbits={wbits} 실패 ({e})")
    return None, log


def _parse_section(stream: bytes) -> list[str]:
    texts = []
    pos = 0
    length = len(stream)

    while pos + 4 <= length:
        header = struct.unpack_from("<I", stream, pos)[0]
        rec_type = header & 0x3FF
        rec_size = (header >> 20) & 0xFFF
        pos += 4

        if rec_size == 0xFFF:
            if pos + 4 > length:
                break
            rec_size = struct.unpack_from("<I", stream, pos)[0]
            pos += 4

        if pos + rec_size > length:
            break

        payload = stream[pos: pos + rec_size]
        pos += rec_size

        if rec_type == _HWPTAG_PARA_TEXT and payload:
            text = _decode_para_text(payload)
            if text:
                texts.append(text)

    return texts


def _decode_para_text(data: bytes) -> str:
    chars = []
    for i in range(0, len(data) - 1, 2):
        code = struct.unpack_from("<H", data, i)[0]
        if code == 0x0D:
            chars.append("\n")
        elif code == 0x09:
            chars.append("\t")
        elif 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD:
            chars.append(chr(code))
    return "".join(chars).strip()
