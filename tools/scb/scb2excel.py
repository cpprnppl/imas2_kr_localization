# -*- coding: utf-8 -*-
"""
scb2excel.py  -  아이돌마스터2 SCB 스크립트 → Excel 변환기

사용법:
  python tools/scb2excel.py

출력:
  tools/translation.xlsx
    A열: 인물명(화자)
    B열: 원문(일본어)
    C열: 번역문(한국어) ← 번역자 입력
    D열: 비고            ← 번역자 메모
    E열: 파일경로(숨김)  ← 자동 패치용
    F열: 엔트리 인덱스   ← 자동 패치용
    G열: 원문 바이트수   ← 자동 패치용
"""

import os, sys, glob
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scb_common as common

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, PatternFill
from openpyxl.utils import get_column_letter

# ── 경로 ────────────────────────────────────────────────────
GSCRIPT_DIR  = common.GSCRIPT_DIR
OUTPUT_EXCEL = os.path.join(common.TOOLS_DIR, 'translation.xlsx')

# ── 헤더 색상 ────────────────────────────────────────────────
HDR_FILL   = PatternFill('solid', fgColor='4472C4')
HDR_FONT   = Font(bold=True, color='FFFFFF', name='맑은 고딕')
INFO_FILL  = PatternFill('solid', fgColor='D9E1F2')
TRANS_FILL = PatternFill('solid', fgColor='E2EFDA')
NOTE_FILL  = PatternFill('solid', fgColor='FFF2CC')

HEADERS = ['인물명', '원문', '번역문', '비고', '파일경로', '엔트리인덱스', '원문바이트수']

import re as _re
_ILLEGAL = _re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')

def _safe_cell(v):
    """Excel에 쓸 수 없는 제어문자를 제거"""
    if isinstance(v, str):
        return _ILLEGAL.sub('', v)
    return v
COL_WIDTHS = [14, 60, 60, 30, 50, 14, 14]


def _clean_text(text):
    """Excel에 쓸 수 없는 제어문자 제거 + 앞쪽 비일본어 쓰레기 제거.

    CJK Extension A(U+3400-U+4DBF)는 일본어 게임 텍스트에 정상적으로 등장하지 않으므로
    제외하여 바이너리 해석 오류로 생긴 쓰레기 문자('䵓䜀' 등)를 필터링합니다.
    """
    text = _ILLEGAL.sub('', text).strip()
    # 앞쪽의 비일본어 쓰레기 제거 (바이너리 혼입)
    for start_pos, ch in enumerate(text):
        if ('\u3000' <= ch <= '\u303F' or   # CJK 구두점 (、。「」 등)
                '\u3040' <= ch <= '\u30FF' or   # 히라가나·카타카나
                '\u4E00' <= ch <= '\u9FFF' or   # CJK 통합 한자 (일반 한자)
                '\uFF00' <= ch <= '\uFFEF' or   # 전각·반각 형식
                ch in '「」『』【】〜～！？…（）'):
            break
    else:
        return ''
    return text[start_pos:]


def _has_japanese(text):
    """실제 일본어 문자(히라가나·카타카나·일반 한자·구두점)를 포함하는지 확인.

    CJK Extension A(U+3400-U+4DBF)는 포함하지 않아 쓰레기 바이트 해석 문자를 걸러냅니다.
    """
    return any(
        '\u3000' <= c <= '\u303F' or   # CJK 구두점
        '\u3040' <= c <= '\u30FF' or   # 히라가나 + 카타카나
        '\u4E00' <= c <= '\u9FFF' or   # CJK 통합 한자
        '\uFF00' <= c <= '\uFFEF' or   # 전각·반각
        c in '「」『』【】〜～！？…（）'
        for c in text
    )


def _speaker_from_path(scb_path):
    """파일 경로에서 화자 추론: 폴더명 우선, 파일명 prefix 보조"""
    folder = os.path.basename(os.path.dirname(scb_path))
    if folder in common.CHAR_MAP:
        return common.CHAR_MAP[folder]
    # 파일명 prefix (e.g. "ami_w01_03" → "ami")
    fname = os.path.splitext(os.path.basename(scb_path))[0]
    prefix = fname.split('_')[0]
    return common.CHAR_MAP.get(prefix, folder)


def process_scb(scb_path):
    """SCB 하나를 복호화·파싱하여 row 리스트 반환 (스트림 방식)"""
    try:
        scb_data = open(scb_path, 'rb').read()
        dec_data = common.decrypt_scb(scb_data)
    except Exception as e:
        print(f"  [복호화 실패] {os.path.basename(scb_path)}: {e}")
        return []

    try:
        sections = common.parse_section_dir(dec_data)
    except Exception as e:
        print(f"  [파싱 실패] {os.path.basename(scb_path)}: {e}")
        return []

    if 'MSG' not in sections:
        return []

    msg_abs, _ = sections['MSG']
    try:
        strings = common.parse_msg_strings_stream(dec_data, msg_abs)
    except Exception:
        return []

    # VCN에서 화자 코드 수집 (의미 있는 캐릭터 코드만)
    vcn_speakers = []
    if 'VCN' in sections:
        vcn_abs, _ = sections['VCN']
        try:
            vcn_entries = common.parse_text_section(dec_data, vcn_abs, 'ascii')
            for ve in vcn_entries:
                spk = common.speaker_from_vcn_id(ve['text'])
                # CHAR_MAP에 없는 코드(숫자 트랙 ID 등)면 None → 후속 처리에서 default_speaker 사용
                vcn_speakers.append(spk)
        except Exception:
            pass

    # 파일 경로 기반 기본 화자
    default_speaker = _speaker_from_path(scb_path)

    rel_path = os.path.relpath(scb_path, GSCRIPT_DIR)
    rows = []
    for idx, entry in enumerate(strings):
        text = _clean_text(entry['text'])
        if not text or not _has_japanese(text):
            continue

        # 화자: VCN에서 같은 인덱스 참조, 없으면 파일 경로 기반
        if idx < len(vcn_speakers) and vcn_speakers[idx]:
            speaker = vcn_speakers[idx]
        else:
            speaker = default_speaker

        char_limit = entry['size'] // 2 - 1   # 글자 수 한도 (null 제외)

        rows.append([
            speaker,             # A: 인물명
            text,                # B: 원문
            '',                  # C: 번역문
            '',                  # D: 비고
            rel_path,            # E: 파일경로(숨김)
            entry['abs_offset'], # F: 절대오프셋(숨김) ← entry_index 대신
            entry['size'],       # G: 원문 바이트수(숨김)
        ])
    return rows


def apply_header(ws):
    ws.append(HEADERS)
    for col, (hdr, width) in enumerate(zip(HEADERS, COL_WIDTHS), 1):
        cell = ws.cell(1, col)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = 'A2'
    # E, F, G 열 숨기기
    for col in ['E', 'F', 'G']:
        ws.column_dimensions[col].hidden = True


def style_data_row(ws, row_num, speaker):
    ws.cell(row_num, 1).fill = INFO_FILL
    ws.cell(row_num, 2).alignment = Alignment(wrap_text=True)
    ws.cell(row_num, 3).fill = TRANS_FILL
    ws.cell(row_num, 3).alignment = Alignment(wrap_text=True)
    ws.cell(row_num, 4).fill = NOTE_FILL


def main():
    print("=" * 60)
    print("  아이돌마스터2 SCB → Excel 변환기")
    print("=" * 60)

    # SCB 파일 수집 (tools/, imas2dec/ 제외)
    all_scbs = glob.glob(os.path.join(GSCRIPT_DIR, '**', '*.scb'), recursive=True)
    all_scbs = [p for p in all_scbs
                if 'tools' not in p.replace('\\', '/').split('/')
                and 'imas2dec' not in p.replace('\\', '/').split('/')]
    all_scbs.sort()
    print(f"SCB 파일: {len(all_scbs)}개\n")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 기본 시트 제거

    # 폴더별로 시트 분리
    folder_rows: dict = {}
    for idx, scb_path in enumerate(all_scbs):
        folder = os.path.basename(os.path.dirname(scb_path))
        print(f"  [{idx+1:4}/{len(all_scbs)}] {os.path.relpath(scb_path, GSCRIPT_DIR)}")
        rows = process_scb(scb_path)
        if rows:
            folder_rows.setdefault(folder, []).extend(rows)

    # 폴더 순서: all 먼저, 나머지 알파벳
    folders = sorted(folder_rows.keys(), key=lambda x: ('0' if x == 'all' else '1') + x)

    total_rows = 0
    for folder in folders:
        rows = folder_rows[folder]
        char_name = common.CHAR_MAP.get(folder, folder)
        sheet_name = f"{folder}({char_name})"[:31]  # Excel 시트명 31자 제한
        ws = wb.create_sheet(title=sheet_name)
        apply_header(ws)

        for r, row in enumerate(rows, 2):
            ws.append([_safe_cell(v) for v in row])
            style_data_row(ws, r, row[0])
        total_rows += len(rows)

    # 목차 시트 (첫 번째)
    idx_ws = wb.create_sheet(title='📋목차', index=0)
    idx_ws.append(['시트명', '캐릭터', '대사 수'])
    idx_ws.column_dimensions['A'].width = 25
    idx_ws.column_dimensions['B'].width = 18
    idx_ws.column_dimensions['C'].width = 10
    for folder in folders:
        char_name = common.CHAR_MAP.get(folder, folder)
        sheet_name = f"{folder}({char_name})"[:31]
        idx_ws.append([sheet_name, char_name, len(folder_rows[folder])])

    wb.save(OUTPUT_EXCEL)
    print(f"\n✅ 완료! 총 {total_rows}개 대사 → {OUTPUT_EXCEL}")
    print(f"   C열(번역문)을 채운 후 excel2scb.py를 실행하세요.")


if __name__ == '__main__':
    main()
