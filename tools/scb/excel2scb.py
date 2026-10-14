# -*- coding: utf-8 -*-
"""
excel2scb.py  -  Excel → SCB 패치 (MSG 테이블 기반 리빌드, spiral6 구조 준수)

근거:
- MSG 블록은 dialogue_strings_count 개의 (len_dialogue_string, ofs_dialogue_string) 테이블로 관리
- 문자열 body 위치는:
    msg_abs + 48 + (count*8) + table_padding + ofs_dialogue_string
  (spiral6 scb.ksy) :contentReference[oaicite:1]{index=1}
- MSG 재구성은:
    header(8) + meta(24) + count(u2) + pad4 + len_dialogue_strings(u2) + pad2
    + len_msgs_header(u2) + pad4 + table + table_pad + bodies + body_pad
  (spiral6 msg.py) :contentReference[oaicite:2]{index=2}

특징:
- CMD/VCN/LBL 등 다른 섹션의 내용은 그대로 두고,
  MSG 섹션만 새로 만들며 섹션 디렉토리의 MSG len, 뒤 섹션 ofs_section만 delta만큼 보정
- 번역문 길이 제한 없음(테이블 재계산으로 자연 확장)
- 폰트 매핑(JSON) 적용(한글 출력용)
- 드래그&드롭으로 특정 파일/폴더만 처리 가능

입력 엑셀:
- tools/translation_1_with_entry.xlsx 또는 tools/translation_1.xlsx 둘 다 지원(있으면 with_entry 우선)
- 엑셀의 F열 abs_offset(원본 문자열 body 시작 abs)을 이용해 string index 매칭
"""

import os, sys, glob, json, struct
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scb_common as common
import openpyxl

GSCRIPT_DIR = common.GSCRIPT_DIR
TOOLS_DIR   = common.TOOLS_DIR

# 원본 SCB는 항상 순정 백업 폴더에서 읽는다.
# (게임 폴더의 gscript는 패치본으로 덮일 수 있으므로, 거기서 읽으면
#  패치본을 재패치하는 사고가 난다 — mam_w01_01 오염 사건의 원인)
_ORIG_CANDIDATE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(GSCRIPT_DIR)), "gscript - 복사본"))
ORIG_DIR = _ORIG_CANDIDATE if os.path.isdir(_ORIG_CANDIDATE) else GSCRIPT_DIR

EXCEL_PATH_V2         = os.path.join(TOOLS_DIR, "translation_2.xlsx")  # 재추출판(오프셋 교정, 최우선)
EXCEL_PATH_WITH_ENTRY = os.path.join(TOOLS_DIR, "translation_1_with_entry.xlsx")
EXCEL_PATH_FALLBACK   = os.path.join(TOOLS_DIR, "translation_1.xlsx")
FONT_MAPPING_JSON     = os.path.join(TOOLS_DIR, "font_mapping.json")
OUTPUT_DIR            = os.path.join(TOOLS_DIR, "output")


# -------------------------
# Drag & Drop filter
# -------------------------
def _norm_rel(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")

def build_target_set(argv_paths):
    if not argv_paths:
        return None
    targets = set()
    for p in argv_paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for scb in glob.glob(os.path.join(p, "**", "*.scb"), recursive=True):
                rel = os.path.relpath(scb, GSCRIPT_DIR)
                targets.add(_norm_rel(rel))
        else:
            if p.lower().endswith(".scb"):
                rel = os.path.relpath(p, GSCRIPT_DIR)
                targets.add(_norm_rel(rel))
    return targets


# -------------------------
# Font mapping
# -------------------------
# 한글 직접 등록 모드 (2026-10-14 전환, 워크로그 §24~25):
#   NFH에 한글 코드포인트가 직접 등록된 폰트(deploy_fonts.py --direct)와 짝.
#   True면 SCB에 원시 한글(UTF-16BE)을 그대로 쓰고 한자 슬롯 치환을 하지 않는다.
#   ※ 구 매핑 폰트와 직접 등록 SCB는 서로 비호환 — 폰트와 SCB를 같이 배포할 것.
#   롤백: False로 되돌리고 재생성 + 구 폰트 배포.
DIRECT_HANGUL = True

def load_font_mapping():
    if DIRECT_HANGUL:
        print("한글 직접 등록 모드: 폰트 매핑 미적용 (원시 한글로 기록)")
        return {}
    if not os.path.exists(FONT_MAPPING_JSON):
        print(f"⚠ 폰트 매핑 JSON 없음: {FONT_MAPPING_JSON}")
        return {}
    with open(FONT_MAPPING_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)
    mapping = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and len(k) == 1 and len(v) == 1:
            mapping[k] = v
    print(f"폰트 매핑 로드: {len(mapping)}개 문자")
    return mapping

def apply_font_mapping(text: str, mapping: dict) -> str:
    if not mapping:
        return text
    return "".join(mapping.get(ch, ch) for ch in text)


# -------------------------
# 재줄바꿈 (게임 대사창 폭 맞춤)
# -------------------------
# 원본 일본어 전수 측정 결과: 대사는 전부 1~2줄, 줄당 최대 25~26전각.
# 번역문의 \n이 이 폭을 넘기면 게임이 중간에 강제개행을 추가해
# "아이/돌들은" 같은 어절 쪼개짐·뒷글자 잘림이 생긴다.
WRAP_WIDTH = 26.0   # 전각 기준 폭
WRAP_WARN_LINES = 3  # 이 줄 수 초과 시 경고(수동 축약 대상)

def _char_width(ch: str) -> float:
    o = ord(ch)
    if o < 0x2E80:               # ASCII/반각
        return 0.5
    if 0xE000 <= o <= 0xF8FF:    # PUA 플레이스홀더(유닛명 등, 런타임 확장) — 여유폭
        return 6.0
    return 1.0                   # 한글/한자/가나/전각

def _text_width(s: str) -> float:
    return sum(_char_width(c) for c in s)

def _is_hangul(c: str) -> bool:
    return '가' <= c <= '힣'

# 뒷줄 첫 어절이 이 중 하나(단독)면 앞말의 조사/어미 연속으로 보고 붙여 쓴다
_PARTICLE_FRAGS = {"다", "로", "야", "요", "라", "은", "는", "을", "를", "가"}

def _join_sep(prev: str, nxt: str) -> str:
    """\n으로 나뉘었던 두 조각을 합칠 때 사이에 넣을 구분자.
    번역기가 일본어 개행 위치를 흉내 내 어절 중간에서 끊은 경우가 많아
    (전수 샘플링 기반 휴리스틱) 그 경우엔 공백 없이 붙인다."""
    if not prev or not nxt:
        return ""
    b, a = prev[-1], nxt[0]
    if b == " " or a == " ":
        return ""
    if not (_is_hangul(b) and _is_hangul(a)):
        # 문장부호 경계: 여는 괄호 뒤·닫는 부호 앞엔 공백 없이
        if b in "「『（([" or a in ",.!?…、。」』！？）)]":
            return ""
        return " "
    # 한글⏎한글: 앞말이 '이'로 끝나면 서술격 조사 분리(활동이⏎다, 아이⏎돌들은)
    if b == "이":
        return ""
    # 뒷줄 첫 한글 어절이 단음절 조사/어미면 붙임 (속도⏎로)
    frag = ""
    for c in nxt:
        if _is_hangul(c):
            frag += c
        else:
            break
    if frag in _PARTICLE_FRAGS:
        return ""
    return " "

import re as _re
_GARBAGE_RE = _re.compile(
    r"THOUGHT:|The user|I need|I will|-> |translat|Here is|japanese text", _re.I)

def is_garbage_translation(t: str) -> bool:
    """LLM 사고과정 유출/미번역 영문 행 감지 (전수 스캔에서 15행 확인).
    이런 행은 패치하지 않고 일본어 원문을 유지한다."""
    if _GARBAGE_RE.search(t):
        return True
    has_hangul = any('가' <= c <= '힣' for c in t)
    ascii_letters = sum(c.isascii() and c.isalpha() for c in t)
    return (not has_hangul) and ascii_letters >= 5


# Kiwi(한국어 형태소 분석기) 띄어쓰기 교정 — 어절 중간 \n 복원 후 누락 공백 복구
# ("확신이들었다" → "확신이 들었다"; 설치 안 돼 있으면 휴리스틱만 사용)
_KIWI = None
_KIWI_TRIED = False

def _kiwi_space(s: str, junctions=None) -> str:
    """Kiwi로 띄어쓰기를 교정하되, '공백 추가'만, 그것도 junctions
    (공백 없이 이어붙인 \n 접합 지점, 공백 제외 문자 인덱스)에서만 수용한다.
    Kiwi의 스타일성 교정('담당해줬으면'→'담당해 줬으면')이나 공백 삭제는 거부."""
    global _KIWI, _KIWI_TRIED
    if not _KIWI_TRIED:
        _KIWI_TRIED = True
        try:
            from kiwipiepy import Kiwi
            _KIWI = Kiwi()
            print("Kiwi 띄어쓰기 교정: 사용")
        except Exception:
            print("⚠ kiwipiepy 없음 — 띄어쓰기 교정 생략 (pip install kiwipiepy 권장)")
    if _KIWI is None or not junctions:
        return s
    try:
        spaced = _KIWI.space(s, reset_whitespace=False)
    except Exception:
        return s
    if [c for c in s if c != " "] != [c for c in spaced if c != " "]:
        return s  # 공백 외 변형이 생기면 원문 유지(안전)
    junctions = set(junctions)
    out = []
    i = j = 0
    emitted = 0  # 지금까지 출력한 비공백 문자 수 = 현재 gap 인덱스
    while i < len(s) or j < len(spaced):
        ci = s[i] if i < len(s) else None
        cj = spaced[j] if j < len(spaced) else None
        if ci == " ":
            out.append(" ")
            i += 1
            if cj == " ":
                j += 1
        elif cj == " ":
            # Kiwi가 추가한 공백: 접합 지점에서만 수용
            if emitted in junctions:
                out.append(" ")
            j += 1
        else:
            out.append(ci)
            i += 1
            j += 1
            emitted += 1
    return "".join(out)

# 개행 지점으로 선호하는 문장부호 (이 뒤에서 끊으면 자연스러움)
_BREAK_PUNCT = "、。，．,.!?！？…」』～♪"

def _wrap_balanced(flat: str) -> list:
    """공백 단위로 WRAP_WIDTH 이하 줄로 감싼다.
    2줄로 들어가면 문장부호 뒤 > 중앙 근접 순으로 자연스러운 지점을 고른다."""
    if _text_width(flat) <= WRAP_WIDTH:
        return [flat]
    words = flat.split(" ")
    # 단어 하나가 폭을 넘는 극단 케이스는 글자 단위로 사전 분할
    fixed = []
    for w in words:
        while _text_width(w) > WRAP_WIDTH:
            seg = ""
            while w and _text_width(seg + w[0]) <= WRAP_WIDTH:
                seg += w[0]
                w = w[1:]
            fixed.append(seg)
        if w:
            fixed.append(w)
    words = fixed

    # 2줄 균형 분할 시도
    n = len(words)
    best = None  # (우선순위, 불균형, k)
    for k in range(1, n):
        l1 = " ".join(words[:k])
        l2 = " ".join(words[k:])
        w1, w2 = _text_width(l1), _text_width(l2)
        if w1 > WRAP_WIDTH or w2 > WRAP_WIDTH:
            continue
        punct = 0 if (l1 and l1[-1] in _BREAK_PUNCT) else 1
        score = (punct, abs(w1 - w2))
        if best is None or score < best[0]:
            best = (score, k)
    if best is not None:
        k = best[1]
        return [" ".join(words[:k]), " ".join(words[k:])]

    # 2줄 불가 → 탐욕적 다줄
    lines, cur = [], ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if _text_width(cand) <= WRAP_WIDTH:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def rewrap(text: str) -> str:
    """기존 \n을 풀고(어절 중간 분리 복원) 띄어쓰기를 교정한 뒤
    대사창 폭에 맞게 자연스러운 지점에서 다시 감싼다.
    한글이 없는(미번역/일본어) 문자열은 건드리지 않는다."""
    if not any('가' <= c <= '힣' for c in text):
        return text
    parts = [p.strip() for p in text.split("\n")]
    flat = parts[0]
    junctions = []  # 공백 없이 이어붙인 지점(공백 제외 문자 인덱스)
    for p in parts[1:]:
        sep = _join_sep(flat, p)
        if sep == "" and flat and p and _is_hangul(flat[-1]) and _is_hangul(p[0]):
            junctions.append(sum(1 for c in flat if c != " "))
        flat = flat + sep + p
    flat = " ".join(flat.split())  # 다중 공백 정리
    flat = _kiwi_space(flat, junctions)
    return "\n".join(_wrap_balanced(flat))


# -------------------------
# Excel load (abs_offset-based)
# -------------------------
def choose_excel_path():
    if os.path.exists(EXCEL_PATH_V2):
        return EXCEL_PATH_V2
    if os.path.exists(EXCEL_PATH_WITH_ENTRY):
        return EXCEL_PATH_WITH_ENTRY
    return EXCEL_PATH_FALLBACK

def load_translations(excel_path: str):
    """
    Returns:
      dict[rel_path] = dict[abs_offset] = translation_text
    (orig_size 등은 필요 없음. MSG 테이블 기반으로 재계산하므로)
    """
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    data = {}
    for ws in wb.worksheets:
        if ws.title.startswith("📋"):
            continue
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 7:
                continue

            tr = row[2]  # C
            if tr is None or not str(tr).strip():
                continue

            rel_path = row[4]  # E
            abs_off  = row[5]  # F (원본 문자열 body abs_offset)
            if rel_path is None or abs_off is None:
                continue

            orig = str(row[1]) if row[1] is not None else ""  # B (원문: fallback 매칭용)
            rel_path = _norm_rel(str(rel_path))
            abs_off = int(abs_off)
            data.setdefault(rel_path, {})[abs_off] = (orig, str(tr))
    wb.close()
    return data


# -------------------------
# MSG parse/build (table-based)
# -------------------------
def parse_section_dir(dec: bytes):
    # scb_common.parse_section_dir를 그대로 씀
    return common.parse_section_dir(dec)

def find_section_dir_entry_offset(dec: bytes, tag_ascii: str):
    """
    섹션 디렉토리 엔트리(0xF0 + i*0x20)에서 특정 tag의 entry offset을 찾아 반환.
    Returns: entry_offset_in_file (absolute index into dec) or None
    """
    scb_off = 0x80
    num_secs = struct.unpack_from(">I", dec, scb_off + 12)[0]
    for i in range(num_secs):
        ent = 0xF0 + i * 0x20
        tag = dec[ent:ent+4].rstrip(b"\x00").decode("ascii", errors="replace")
        if tag == tag_ascii:
            return ent
    return None

def parse_msg_table(dec: bytes, msg_abs: int):
    """
    scb.ksy 기반 MSG 파싱 :contentReference[oaicite:3]{index=3}

    Returns dict:
      count, len_dialogue_strings(u2), len_msgs_header(u2),
      table_off_abs, body_base_abs, entries(list of (ln, ofs)),
      strings(list of dict index, abs_offset, len, ofs, text),
      prefix_48 (원본 msg_abs ~ msg_abs+48)
    """
    prefix_48 = dec[msg_abs:msg_abs+48]
    # layout: header(8) meta(24) count(u2) pad4 len_dialogue_strings(u2) pad2 len_msgs_header(u2) pad4  => 48 bytes
    count = struct.unpack_from(">H", dec, msg_abs + 32)[0]
    len_dialogue_strings = struct.unpack_from(">H", dec, msg_abs + 38)[0]
    len_msgs_header = struct.unpack_from(">H", dec, msg_abs + 42)[0]

    table_off = msg_abs + 48
    entries = []
    for i in range(count):
        ln  = struct.unpack_from(">I", dec, table_off + i*8 + 0)[0]
        ofs = struct.unpack_from(">I", dec, table_off + i*8 + 4)[0]
        entries.append((ln, ofs))

    table_bytes = count * 8
    table_pad = (16 - (table_bytes % 16)) % 16
    body_base = table_off + table_bytes + table_pad

    strings = []
    for i, (ln, ofs) in enumerate(entries):
        abs_body = body_base + ofs
        raw = dec[abs_body:abs_body+ln]
        # body is utf-16be string (likely includes terminator)
        txt = raw.decode("utf-16-be", errors="replace").split("\x00")[0]
        strings.append({
            "index": i,
            "abs_offset": abs_body,
            "len": ln,
            "ofs": ofs,
            "text": txt,
        })

    return {
        "count": count,
        "len_dialogue_strings": len_dialogue_strings,
        "len_msgs_header": len_msgs_header,
        "table_off_abs": table_off,
        "body_base_abs": body_base,
        "entries": entries,
        "strings": strings,
        "prefix_48": prefix_48,
    }

def build_msg_block(parsed, new_texts_by_index: dict, font_map: dict, old_msg_size: int):
    """
    spiral6 msg.py 방식에 맞춰 MSG 섹션 bytes를 새로 생성 :contentReference[oaicite:4]{index=4}
    - prefix_48의 구조를 유지하되 크기 필드들을 새 값으로 갱신:
      * +0x08 (u4): 내부 섹션 크기 필드 (전 파일에서 msg_size-32, 예외 1개는 delta 보존)
      * +36   (u4): 대사 총 바이트 수 (원본 전 파일에서 상위 2바이트 0 → u4로 기록)
    - count는 원본과 동일 유지 (CMD/VCN 인덱스 안정성)
    """
    count = parsed["count"]

    # 문자열 bodies 생성 + (len, ofs) 재계산
    bodies = []
    offsets = []
    ofs = 0
    total_dialogue_len = 0  # bytes, includes terminators (u2에 저장될 값)
    for i in range(count):
        txt = new_texts_by_index.get(i, parsed["strings"][i]["text"])
        txt = apply_font_mapping(txt, font_map)

        raw = txt.encode("utf-16-be", errors="replace") + b"\x00\x00"
        ln = len(raw)
        bodies.append(raw)
        offsets.append((ln, ofs))
        ofs += ln
        total_dialogue_len += ln

    # table
    table = bytearray()
    for ln, ofs0 in offsets:
        table += struct.pack(">I", ln)
        table += struct.pack(">I", ofs0)

    table_pad = (16 - ((count * 8) % 16)) % 16
    table += b"\x00" * table_pad  # pad 값은 의미 없음. (spiral6는 pre_MSG_padding 사용) :contentReference[oaicite:5]{index=5}

    # body + body pad to 16
    body_blob = bytearray().join(bodies)
    body_pad = (16 - (total_dialogue_len % 16)) % 16
    body_blob += b"\x00" * body_pad

    # prefix_48 복사 후 크기 필드 갱신
    prefix = bytearray(parsed["prefix_48"])

    # +36(u4): 대사 총 바이트 수. 원본 전 파일에서 +36~+38이 0이므로 u4로 기록.
    if total_dialogue_len > 0xFFFF:
        print(f"    ⚠ 대사 총 길이가 u2 범위 초과: {total_dialogue_len} (u4로 기록)")
    prefix[36:40] = struct.pack(">I", total_dialogue_len)

    new_msg_size = 48 + len(table) + len(body_blob)

    # +0x08(u4): 내부 섹션 크기 필드. 원본 값에 delta를 더해 보존
    # (1182/1183 파일에서 msg_size-32, mam_w01_01만 msg_size+16 → delta 방식이 둘 다 커버)
    old_f08 = struct.unpack_from(">I", prefix, 8)[0]
    struct.pack_into(">I", prefix, 8, old_f08 + (new_msg_size - old_msg_size))

    # 완성 MSG 블록
    return bytes(prefix) + bytes(table) + bytes(body_blob)


# -------------------------
# Replace MSG section in dec and update section dir offsets
# -------------------------
def replace_msg_section(dec: bytes, msg_abs: int, old_msg_size: int, new_msg_bytes: bytes):
    """
    dec_data에서 MSG 섹션만 교체하고, 섹션 디렉토리의:
      - MSG len_section 갱신
      - MSG 이후 섹션 ofs_section += delta
      - (필요 시) MSG 섹션 내부 길이 필드는 build_msg_block에서 처리
    """
    delta = len(new_msg_bytes) - old_msg_size
    if delta == 0:
        buf = bytearray(dec)
        buf[msg_abs:msg_abs+old_msg_size] = new_msg_bytes
        return bytes(buf), 0

    # 1) MSG 바이트 교체(삽입/삭제)
    buf = bytearray()
    buf += dec[:msg_abs]
    buf += new_msg_bytes
    buf += dec[msg_abs + old_msg_size:]

    # 2) 섹션 디렉토리 업데이트
    scb_off = 0x80
    num_secs = struct.unpack_from(">I", buf, scb_off + 12)[0]

    msg_entry_off = find_section_dir_entry_offset(buf, "MSG")
    if msg_entry_off is None:
        raise ValueError("섹션 디렉토리에서 MSG 엔트리를 찾지 못했습니다.")

    msg_raw_ofs = struct.unpack_from(">I", buf, msg_entry_off + 12)[0]
    # MSG len_section 갱신
    struct.pack_into(">I", buf, msg_entry_off + 8, len(new_msg_bytes))

    # MSG 뒤 섹션 ofs_section 보정
    for i in range(num_secs):
        ent = 0xF0 + i * 0x20
        tag = buf[ent:ent+4].rstrip(b"\x00").decode("ascii", errors="replace")
        if tag == "MSG":
            continue
        sec_ofs = struct.unpack_from(">I", buf, ent + 12)[0]
        if sec_ofs > msg_raw_ofs:
            struct.pack_into(">I", buf, ent + 12, sec_ofs + delta)

    # 3) pac 컨테이너 헤더 갱신 (전 1183파일 검증된 불변 구조)
    #    dec 파일은 'pac' 컨테이너: 서브파일0 = SCB(스크립트), 서브파일1 = 컷씬/모션 pac.
    #    SCB가 커지면 아래 4곳을 갱신해야 서브파일1 참조가 깨지지 않는다.
    #    (미갱신 시: 대사는 나오지만 음성/컷씬 로드 순간 access violation 크래시)
    if buf[:4] != b"pac\x00":
        raise ValueError("pac magic이 아닙니다 - 구조 재확인 필요")
    # 3a) +0x08: 전체 콘텐츠 크기 (dec_len - 0x80)
    struct.pack_into(">I", buf, 0x08, struct.unpack_from(">I", buf, 0x08)[0] + delta)
    # 3b) +0x88: SCB 블록 내부 크기 필드 (scb_total - 32)
    struct.pack_into(">I", buf, 0x88, struct.unpack_from(">I", buf, 0x88)[0] + delta)
    # 3c) 서브파일 레코드(0x40 + i*0x20, +8=size, +12=offset):
    #     offset 0(=SCB)인 레코드는 size += delta, 그 뒤 레코드는 offset += delta
    nsub = struct.unpack_from(">I", buf, 0x0C)[0]
    for i in range(nsub):
        rec = 0x40 + i * 0x20
        sz = struct.unpack_from(">I", buf, rec + 8)[0]
        of = struct.unpack_from(">I", buf, rec + 12)[0]
        if of == 0:
            struct.pack_into(">I", buf, rec + 8, sz + delta)
        else:
            struct.pack_into(">I", buf, rec + 12, of + delta)

    return bytes(buf), delta


# -------------------------
# Patch one SCB
# -------------------------
def patch_one_scb(rel_path: str, abs_to_tr: dict, font_map: dict):
    scb_path = os.path.join(ORIG_DIR, rel_path)
    if not os.path.exists(scb_path):
        return False, [f"원본 파일 없음: {rel_path}"]

    # decrypt
    scb_data = open(scb_path, "rb").read()
    dec = common.decrypt_scb(scb_data)

    # parse sections
    secs = parse_section_dir(dec)
    if "MSG" not in secs:
        return True, [f"MSG 없음(스킵): {rel_path}"]

    msg_abs, msg_size = secs["MSG"]

    parsed = parse_msg_table(dec, msg_abs)

    # build abs_offset -> string_index map (from original)
    abs_to_index = { s["abs_offset"]: s["index"] for s in parsed["strings"] }

    # fallback: 원문 텍스트 -> index (유일한 경우만). 구버전 추출기의 abs_offset 오류 구제용
    text_to_indices = {}
    for s in parsed["strings"]:
        text_to_indices.setdefault(s["text"].strip(), []).append(s["index"])

    # build new_texts_by_index
    new_by_idx = {}
    misses = 0
    text_recovered = 0
    garbage_skipped = 0
    for abs_off, (orig, tr) in abs_to_tr.items():
        if is_garbage_translation(tr):
            garbage_skipped += 1
            continue
        idx = abs_to_index.get(abs_off)
        if idx is None:
            # 원문 텍스트로 유일 매칭 시도
            cand = text_to_indices.get(orig.strip(), [])
            cand = [c for c in cand if c not in new_by_idx]
            if len(cand) == 1:
                idx = cand[0]
                text_recovered += 1
            else:
                misses += 1
                continue
        new_by_idx[idx] = rewrap(tr)

    # rebuild MSG block
    new_msg = build_msg_block(parsed, new_by_idx, font_map, msg_size)

    # replace MSG section + fix section dir offsets
    new_dec, _delta = replace_msg_section(dec, msg_abs, msg_size, new_msg)

    # encrypt to scb
    new_scb = common.encrypt_to_scb(new_dec, scb_data)

    out_path = os.path.join(OUTPUT_DIR, rel_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(new_scb)

    warns = []
    if text_recovered:
        warns.append(f"원문 텍스트 매칭으로 구제 {text_recovered}개")
    if misses:
        warns.append(f"abs_offset 매칭 실패 {misses}개(해당 줄은 미패치)")
    if garbage_skipped:
        warns.append(f"⚠ LLM 쓰레기 번역 {garbage_skipped}개 스킵(원문 유지, 재번역 필요)")
    too_long = [(i, t) for i, t in new_by_idx.items() if t.count("\n") + 1 > WRAP_WARN_LINES]
    for i, t in too_long[:5]:
        warns.append(f"⚠ {WRAP_WARN_LINES}줄 초과(축약 필요) entry[{i}]: {t.splitlines()[0][:20]}…")
    if len(too_long) > 5:
        warns.append(f"⚠ 그 외 {len(too_long)-5}개 더 {WRAP_WARN_LINES}줄 초과")
    return True, warns


# -------------------------
# main
# -------------------------
def main():
    print("=" * 60)
    print("  Excel → SCB 패치 (MSG 테이블 리빌드: spiral6 방식)")
    print("=" * 60)
    if ORIG_DIR == GSCRIPT_DIR:
        print("⚠ 순정 백업 폴더(gscript - 복사본)를 찾지 못해 게임 폴더에서 원본을 읽습니다.")
        print("  게임 폴더가 패치본으로 덮여 있으면 결과가 오염됩니다!")
    else:
        print(f"원본 소스: {ORIG_DIR}")

    excel_path = choose_excel_path()
    if not os.path.exists(excel_path):
        print(f"❌ 엑셀 파일 없음: {excel_path}")
        sys.exit(1)
    print(f"번역 엑셀: {os.path.basename(excel_path)}")

    font_map = load_font_mapping()
    translations = load_translations(excel_path)

    targets = build_target_set(sys.argv[1:])
    if targets is not None:
        translations = {k: v for k, v in translations.items() if _norm_rel(k) in targets}
        print(f"대상 필터: {len(translations)}개 파일")

    if not translations:
        print("번역문이 없습니다.")
        sys.exit(0)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total_files = len(translations)
    total_lines = sum(len(v) for v in translations.values())
    print(f"패치 대상: {total_files}개 파일, {total_lines}개 대사\n")

    ok = 0
    fail = 0
    all_warns = []

    for i, (rel_path, abs_map) in enumerate(sorted(translations.items()), 1):
        print(f"  [{i:4}/{total_files}] {rel_path} ({len(abs_map)}줄) ... ", end="")
        try:
            success, warns = patch_one_scb(rel_path, abs_map, font_map)
            if success:
                print("✅ OK")
                ok += 1
            else:
                print("❌ FAIL")
                fail += 1
            for w in warns:
                all_warns.append(f"  [{rel_path}] {w}")
        except Exception as e:
            print(f"❌ FAIL: {e}")
            fail += 1

    print(f"\n{'='*60}")
    print(f"완료: 성공 {ok} / 실패 {fail}")
    print(f"출력 위치: {OUTPUT_DIR}")

    if all_warns:
        print(f"\n경고/정보({len(all_warns)}):")
        for w in all_warns[:80]:
            print(w)
        if len(all_warns) > 80:
            print(f"... 외 {len(all_warns)-80}")

if __name__ == "__main__":
    main()