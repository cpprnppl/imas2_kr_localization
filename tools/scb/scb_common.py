# -*- coding: utf-8 -*-
"""
아이돌마스터2 SCB 파일 공통 라이브러리
- AES-192-CBC 복호화/암호화
- MSG/VCN 섹션 파싱 및 패치
"""

import os, struct, re
from Crypto.Cipher import AES

# ── 경로 설정 ──────────────────────────────────────────────
TOOLS_DIR   = os.path.dirname(os.path.abspath(__file__))
GSCRIPT_DIR = os.path.dirname(TOOLS_DIR)
BMS_PATH    = os.path.join(GSCRIPT_DIR, 'imas2dec', 'imas2dec',
                            '..', '..', '..', 'unpack', 'wcgyao', 'imas2dec.bms')
# BMS가 없으면 Desktop 경로에서 찾기
_BMS_CANDIDATES = [
    BMS_PATH,
    r'C:\Users\jackfilm\Desktop\unpack\wcgyao\imas2dec.bms',
    os.path.join(os.path.expanduser('~'), 'Desktop', 'unpack', 'wcgyao', 'imas2dec.bms'),
]

# ── 캐릭터 이름 매핑 ────────────────────────────────────────
CHAR_MAP = {
    'ami': '双海亜美',
    'mam': '双海真美',
    'chi': '如月千早',
    'har': '天海春香',
    'hib': '我那覇響',
    'ior': '水瀬伊織',
    'mak': '菊地真',
    'mik': '星井美希',
    'rit': '秋月律子',
    'tak': '四条貴音',
    'yay': '高槻やよい',
    'yuk': '萩原雪歩',
    'azu': '三浦あずさ',
    'ryu': 'Jupiter',
    'all': '共通シーン',
    'pro': 'プロデューサー',
    'arr': '複数アイドル',
    'liv': '共通',
    'com': '共通',
}

# ── 키 테이블 로드 ──────────────────────────────────────────
def _load_key_table():
    for path in _BMS_CANDIDATES:
        path = os.path.normpath(path)
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='ascii', errors='replace') as f:
            content = f.read()
        m = re.search(r'set memory_file binary "(.*?)"', content, re.DOTALL)
        if not m:
            continue
        raw = m.group(1)
        table = bytearray()
        i = 0
        bs = chr(92)  # backslash
        while i < len(raw):
            c = raw[i]
            if c == bs and i + 1 < len(raw):
                nc = raw[i + 1]
                if nc == 'x' and i + 3 < len(raw):
                    table.append(int(raw[i + 2:i + 4], 16))
                    i += 4
                else:
                    i += 2
            else:
                v = ord(c)
                table.append(v if v < 256 else 63)
                i += 1
        return bytes(table)
    raise FileNotFoundError("imas2dec.bms를 찾을 수 없습니다. Desktop\\unpack\\wcgyao\\ 에 있는지 확인하세요.")

_KEY_TABLE = None

def get_key_table():
    global _KEY_TABLE
    if _KEY_TABLE is None:
        _KEY_TABLE = _load_key_table()
    return _KEY_TABLE


# ── AES 키 유도 ─────────────────────────────────────────────
def derive_key(table, num1, num2, num3):
    hi  = (num1 >> 4) & 0xF
    lo  = num1 & 0xF
    o0  = hi * 24
    o1  = lo * 24
    i0  = num2 % 24
    i1  = num3 % 24
    key = bytearray(24)
    for i in range(24):
        key[i] = table[o0 + i0] ^ table[o1 + i1]
        i0 = (i0 + 1) % 24
        i1 = (i1 + 1) % 24
    return bytes(key)


# ── SCB 복호화 ──────────────────────────────────────────────
def decrypt_scb(scb_data):
    """암호화된 .scb 바이트 → 복호화된 .dec 바이트"""
    table = get_key_table()
    n  = len(scb_data)
    fp = n - 32
    key = derive_key(table, scb_data[fp + 1], scb_data[fp + 2], scb_data[fp + 3])
    cipher = AES.new(key, AES.MODE_CBC, b'\x00' * 16)
    return cipher.decrypt(scb_data[:n - 64])[16:]


# ── SCB 재암호화 ────────────────────────────────────────────
def encrypt_to_scb(dec_data, orig_scb_data):
    """수정된 .dec 바이트 + 원본 .scb → 재암호화된 .scb 바이트

    dec_data 길이가 원본과 달라도 되지만, 16바이트 배수여야 합니다.
    """
    table  = get_key_table()
    n      = len(orig_scb_data)
    fp     = n - 32
    key    = derive_key(table, orig_scb_data[fp + 1],
                               orig_scb_data[fp + 2],
                               orig_scb_data[fp + 3])
    footer = orig_scb_data[n - 64:]   # 64바이트 풋터 유지

    # plaintext = 16바이트 prefix(복호화 시 제거됨) + 실제 내용
    plaintext = b'\x00' * 16 + dec_data
    pad = (16 - len(plaintext) % 16) % 16
    plaintext += b'\x00' * pad

    cipher     = AES.new(key, AES.MODE_CBC, b'\x00' * 16)
    ciphertext = cipher.encrypt(plaintext)
    return ciphertext + footer


# ── SCB 섹션 디렉토리 파싱 ──────────────────────────────────
def parse_section_dir(dec_data):
    """섹션 이름 → (절대 오프셋, 크기) 딕셔너리 반환"""
    scb_off      = 0x80
    num_sections = struct.unpack_from('>I', dec_data, scb_off + 12)[0]
    sections     = {}
    for i in range(num_sections):
        entry  = 0xF0 + i * 0x20
        tag    = dec_data[entry:entry + 4].rstrip(b'\x00').decode('ascii', errors='replace')
        size   = struct.unpack_from('>I', dec_data, entry + 8)[0]
        offset = struct.unpack_from('>I', dec_data, entry + 12)[0]
        sections[tag] = (scb_off + offset, size)
    return sections


# ── 텍스트 섹션 파싱 (VCN용 – 엔트리 단위) ─────────────────
def parse_text_section(dec_data, abs_off, encoding='utf-16-be'):
    """VCN 섹션 파싱(엔트리 단위).  MSG는 parse_msg_strings_stream 사용 권장.

    Returns list of dicts:
      abs_offset  : 파일 내 텍스트 데이터의 절대 오프셋
      size        : 텍스트 바이트 수(null 포함)
      text        : 디코딩된 문자열(null 제거)
      entry_index : 섹션 내 순서
    """
    sec         = dec_data[abs_off:]
    num_entries = struct.unpack_from('>H', sec, 0x20)[0]
    text_base   = abs_off + 0x60

    entries = []
    for i in range(num_entries):
        eoff   = 0x30 + i * 8
        size   = struct.unpack_from('>I', sec, eoff)[0]
        offset = struct.unpack_from('>I', sec, eoff + 4)[0]
        abs_t  = text_base + offset
        raw    = dec_data[abs_t:abs_t + size]
        if encoding == 'utf-16-be':
            text = raw.decode('utf-16-be', errors='replace').split('\x00')[0]
        else:
            text = raw.rstrip(b'\x00').decode('ascii', errors='replace').split('\x00')[0]
        entries.append({
            'abs_offset':  abs_t,
            'size':        size,
            'text':        text,
            'entry_index': i,
        })
    return entries


# ── MSG 스트림 파싱 (엔트리 경계 무관, 모든 대사 추출) ────────
def parse_msg_strings_stream(dec_data, msg_abs):
    """MSG 섹션의 텍스트 데이터를 스트림으로 읽어 NULL 단위로 분리.

    _liv_, _arr_ 등 하나의 엔트리에 여러 대사가 담기거나
    대사가 엔트리 경계를 넘는 파일도 정상 처리.

    Returns list of dicts:
      abs_offset : dec_data 내 이 문자열의 절대 바이트 오프셋
      size       : 바이트 수 (null 2바이트 포함)
      text       : 디코딩된 문자열 (null 제거)
    """
    sec         = dec_data[msg_abs:]
    num_entries = struct.unpack_from('>H', sec, 0x20)[0]
    text_base   = msg_abs + 0x60

    # 전체 텍스트 데이터 범위
    total_bytes = 0
    for i in range(num_entries):
        eoff   = 0x30 + i * 8
        size   = struct.unpack_from('>I', sec, eoff)[0]
        offset = struct.unpack_from('>I', sec, eoff + 4)[0]
        total_bytes = max(total_bytes, offset + size)

    stream    = dec_data[text_base:text_base + total_bytes]
    strings   = []
    pos       = 0
    str_start = 0

    while pos + 1 < len(stream):
        cp = (stream[pos] << 8) | stream[pos + 1]
        if cp == 0x0000:                       # NULL → 문자열 종료
            if pos > str_start:
                raw  = stream[str_start:pos]
                text = raw.decode('utf-16-be', errors='replace')
                strings.append({
                    'abs_offset': text_base + str_start,
                    'size':       pos - str_start + 2,   # null 포함
                    'text':       text,
                })
            str_start = pos + 2
            pos      += 2
        elif cp == 0xCDCD:                     # 패딩 → 건너뜀
            str_start = pos + 2
            pos      += 2
        else:
            pos += 2

    return strings


# ── 화자 추출 ───────────────────────────────────────────────
def speaker_from_vcn_id(vcn_id):
    """'ami_w01_03_ami_001' → 'ami' → '双海亜美'.
    CHAR_MAP에 없는 코드(숫자 트랙번호 등)면 None 반환 → 호출부에서 default_speaker 사용.
    """
    parts = vcn_id.split('_')
    # 뒤에서 두 번째 파트가 캐릭터 코드
    if len(parts) >= 2:
        code = parts[-2]
        if code in CHAR_MAP:
            return CHAR_MAP[code]
        return None   # 알 수 없는 코드 (숫자 트랙 ID 등)
    return None       # 단일 파트("01", "i" 등) → 판별 불가


# ── 텍스트 패치 ─────────────────────────────────────────────
def patch_text_entry(dec_data, abs_offset, orig_size, new_text, encoding='utf-16-be'):
    """dec_data 바이트 배열의 abs_offset 위치에 new_text를 씁니다.

    - new_text가 원본보다 짧으면 전각 공백(U+3000)으로 패딩
    - new_text가 원본보다 길면 잘라냄(경고 반환)
    Returns (patched_data, warning_message_or_None)
    """
    if encoding == 'utf-16-be':
        char_limit = orig_size // 2 - 1          # null 제외 최대 글자 수
        if len(new_text) > char_limit:
            new_text = new_text[:char_limit]
            warning = f"0x{abs_offset:X}: 번역문이 너무 길어 {char_limit}자로 잘렸습니다."
        else:
            warning = None
        padded = new_text.ljust(char_limit, '\u3000') + '\x00'
        raw = padded.encode('utf-16-be')
    else:
        char_limit = orig_size - 1
        if len(new_text) > char_limit:
            new_text = new_text[:char_limit]
            warning = f"0x{abs_offset:X}: 번역문이 너무 길어 {char_limit}자로 잘렸습니다."
        else:
            warning = None
        raw = (new_text.ljust(char_limit) + '\x00').encode('ascii', errors='replace')

    result = bytearray(dec_data)
    result[abs_offset:abs_offset + orig_size] = raw
    return bytes(result), warning


# ── 텍스트 엔트리 크기 확장 ──────────────────────────────────
def expand_text_entry(dec_data, abs_offset, old_size, new_size):
    """MSG 섹션에서 특정 abs_offset의 엔트리 크기를 확장.

    new_size는 반드시 old_size보다 크고 2의 배수여야 함.
    Returns 새 dec_data (bytes). abs_offset 이후 오프셋이 모두 자동 조정됨.
    """
    assert new_size > old_size and new_size % 2 == 0, "new_size는 old_size보다 크고 2의 배수여야 함"
    delta = new_size - old_size

    sections = parse_section_dir(dec_data)
    msg_abs, msg_sec_size = sections['MSG']
    sec      = dec_data[msg_abs:]
    num_entries = struct.unpack_from('>H', sec, 0x20)[0]
    text_base   = msg_abs + 0x60

    # abs_offset → 엔트리 인덱스 찾기 (엔트리 전체 범위로 탐색)
    # 범위 내 없으면 직전 엔트리로 fallback (엔트리 경계 밖 스트림 대사)
    target_idx = None
    entry_size = None
    for i in range(num_entries):
        eoff   = msg_abs + 0x30 + i * 8
        e_size = struct.unpack_from('>I', dec_data, eoff)[0]
        e_off  = struct.unpack_from('>I', dec_data, eoff + 4)[0]
        if text_base + e_off <= abs_offset < text_base + e_off + e_size:
            target_idx = i
            entry_size = e_size
            break

    if target_idx is None:
        # 엔트리 경계 밖: abs_offset보다 작은 마지막 엔트리를 확장
        best_i = None
        best_end = -1
        for i in range(num_entries):
            eoff  = msg_abs + 0x30 + i * 8
            e_size = struct.unpack_from('>I', dec_data, eoff)[0]
            e_off  = struct.unpack_from('>I', dec_data, eoff + 4)[0]
            end = text_base + e_off + e_size
            if end <= abs_offset and end > best_end:
                best_end = end
                best_i = i
        if best_i is None:
            raise ValueError(f"abs_offset {abs_offset:#x}에 해당하는 엔트리를 찾을 수 없습니다.")
        target_idx = best_i
        eoff_b = msg_abs + 0x30 + target_idx * 8
        entry_size = struct.unpack_from('>I', dec_data, eoff_b)[0]

    # 1. 문자열 끝 위치에 바이트 삽입, 엔트리 전체 size도 delta만큼 확장
    eoff_t     = msg_abs + 0x30 + target_idx * 8
    insert_pos = abs_offset + old_size  # 문자열 끝

    buf = bytearray(dec_data)
    pad = b'\xCD\xCD' * (delta // 2)
    buf = buf[:insert_pos] + pad + buf[insert_pos:]

    # 2. 해당 엔트리 size 수정 (엔트리 전체 size + delta)
    struct.pack_into('>I', buf, eoff_t, entry_size + delta)

    # 3. 이후 엔트리 offset += delta
    for i in range(target_idx + 1, num_entries):
        eoff_i   = msg_abs + 0x30 + i * 8 + 4
        old_off  = struct.unpack_from('>I', buf, eoff_i)[0]
        struct.pack_into('>I', buf, eoff_i, old_off + delta)

    # 4. MSG 섹션 size += delta (섹션 디렉토리)
    scb_off   = 0x80
    num_secs  = struct.unpack_from('>I', buf, scb_off + 12)[0]
    msg_sec_raw_offset = None
    for i in range(num_secs):
        entry = 0xF0 + i * 0x20
        tag   = buf[entry:entry+4].rstrip(b'\x00').decode('ascii', errors='replace')
        if tag == 'MSG':
            msg_sec_raw_offset = struct.unpack_from('>I', buf, entry + 12)[0]
            old_sec_size = struct.unpack_from('>I', buf, entry + 8)[0]
            struct.pack_into('>I', buf, entry + 8, old_sec_size + delta)
            # MSG 헤더 내부 크기 필드도 수정
            struct.pack_into('>I', buf, msg_abs + 0x08, struct.unpack_from('>I', buf, msg_abs + 0x08)[0] + delta)
            struct.pack_into('>I', buf, msg_abs + 0x24, struct.unpack_from('>I', buf, msg_abs + 0x24)[0] + delta)
            break

    # 5. MSG보다 raw_offset이 큰 섹션 offset += delta
    for i in range(num_secs):
        entry      = 0xF0 + i * 0x20
        tag        = buf[entry:entry+4].rstrip(b'\x00').decode('ascii', errors='replace')
        off_field  = entry + 12
        sec_offset = struct.unpack_from('>I', buf, off_field)[0]
        if tag != 'MSG' and sec_offset > msg_sec_raw_offset:
            struct.pack_into('>I', buf, off_field, sec_offset + delta)

    return bytes(buf)