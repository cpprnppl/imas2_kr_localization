# -*- coding: utf-8 -*-
"""
validate_output.py — excel2scb 산출물(output/) 전수 구조 검증 게이트

배포(deploy) 전에 반드시 통과해야 하는 검증:
  1. 복호화 가능
  2. pac 컨테이너 불변식 (+0x08 총크기, 서브파일 레코드 연속성/합, 0x88 = SCB크기-32)
  3. MSG 테이블/본문 정합 (오프셋 연속, 널 종단, 내부 널 없음)
  4. MSG 크기 필드 (+36 u4 = 대사 총 바이트, +0x08 delta 일관성)
  5. 섹션 경계/겹침
  6. 한글 검출 — excel2scb.DIRECT_HANGUL 모드와 일치 검증:
     직접 등록 모드면 원시 한글이 정상(미검출 시 경고 없음),
     매핑 모드면 원시 한글 = 빈 글리프 경고

사용: 게임 tools 폴더에서  python validate_output.py
종료코드: 0 = 통과(경고 허용), 1 = 구조 오류 존재
"""
import os, sys, glob, struct

TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
sys.path.insert(0, TOOLS)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import scb_common as common

GS = common.GSCRIPT_DIR
BACKUP = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(GS)), "gscript - 복사본"))
OUT = os.path.join(TOOLS, "output")


def validate_one(path, rel):
    issues, hangul = [], []
    dec = common.decrypt_scb(open(path, "rb").read())
    secs = common.parse_section_dir(dec)
    if "MSG" not in secs:
        return ["MSG 섹션 없음"], hangul
    msg_abs, msg_size = secs["MSG"]
    count = struct.unpack_from(">H", dec, msg_abs + 0x20)[0]
    f08 = struct.unpack_from(">I", dec, msg_abs + 8)[0]
    f36 = struct.unpack_from(">I", dec, msg_abs + 36)[0]
    table_off = msg_abs + 0x30
    base = table_off + count * 8 + ((16 - (count * 8) % 16) % 16)
    total, prev_end = 0, 0
    for i in range(count):
        ln = struct.unpack_from(">I", dec, table_off + i * 8)[0]
        of = struct.unpack_from(">I", dec, table_off + i * 8 + 4)[0]
        if of != prev_end:
            issues.append(f"entry{i} ofs {of} != {prev_end}")
        raw = dec[base + of: base + of + ln]
        if ln > 116:
            issues.append(f"entry{i} {ln}B > 116B (게임 버퍼 초과 — 힙 손상 유발)")
        if ln < 2 or raw[-2:] != b"\x00\x00":
            issues.append(f"entry{i} 널 종단 없음")
        body = raw[:-2]
        for j in range(0, len(body) - 1, 2):
            if body[j] == 0 and body[j + 1] == 0:
                issues.append(f"entry{i} 내부 널")
                break
        txt = body.decode("utf-16-be", errors="replace")
        bad = {c for c in txt if "\uAC00" <= c <= "\uD7A3"}
        if bad:
            hangul.append((i, "".join(sorted(bad))))
        prev_end = of + ln
        total = max(total, of + ln)
    if f36 != total:
        issues.append(f"+36 {f36} != 대사총길이 {total}")
    pad2 = (16 - (total % 16)) % 16
    if base + total + pad2 != msg_abs + msg_size:
        issues.append("MSG 섹션 끝 불일치")
    # f08: 원본 대비 delta 일관성
    orig_p = os.path.join(BACKUP, rel)
    if os.path.exists(orig_p):
        o = common.decrypt_scb(open(orig_p, "rb").read())
        osecs = common.parse_section_dir(o)
        omsg_abs, omsg_size = osecs["MSG"]
        of08 = struct.unpack_from(">I", o, omsg_abs + 8)[0]
        if f08 - of08 != msg_size - omsg_size:
            issues.append(f"MSG +0x08 delta 불일치 ({f08} vs 원본 {of08})")
    # pac 컨테이너
    if dec[:4] != b"pac\x00":
        issues.append("pac magic 없음")
    else:
        pac_total = struct.unpack_from(">I", dec, 0x08)[0]
        if pac_total != len(dec) - 0x80:
            issues.append(f"pac 총크기 {pac_total} != {len(dec) - 0x80}")
        scb_total = max(off + sz for off, sz in secs.values()) - 0x80
        f88 = struct.unpack_from(">I", dec, 0x88)[0]
        if f88 != scb_total - 32:
            issues.append(f"0x88 {f88} != SCB크기-32 {scb_total - 32}")
        nsub = struct.unpack_from(">I", dec, 0x0C)[0]
        pos = 0
        for si in range(nsub):
            r = 0x40 + si * 0x20
            ssz = struct.unpack_from(">I", dec, r + 8)[0]
            sof = struct.unpack_from(">I", dec, r + 12)[0]
            if sof != pos:
                issues.append(f"pac rec{si} ofs {sof} != {pos}")
            if si == 0 and ssz != scb_total:
                issues.append(f"pac rec0 size {ssz} != {scb_total}")
            pos = sof + ssz
        if pos != pac_total:
            issues.append(f"pac rec 합 {pos} != {pac_total}")
    # 섹션 겹침
    ends = sorted((off, off + sz, t) for t, (off, sz) in secs.items())
    for a, b in zip(ends, ends[1:]):
        if a[1] > b[0]:
            issues.append(f"섹션 겹침 {a[2]}/{b[2]}")
    return issues, hangul


def main():
    outs = glob.glob(os.path.join(OUT, "**", "*.scb"), recursive=True)
    print(f"검증 대상: {len(outs)}개")
    struct_bad, hangul_warn = [], []
    for p in outs:
        rel = os.path.relpath(p, OUT)
        try:
            issues, hangul = validate_one(p, rel)
        except Exception as e:
            issues, hangul = [f"예외: {e}"], []
        if issues:
            struct_bad.append((rel, issues[:4]))
        if hangul:
            hangul_warn.append((rel, hangul[:3]))
    try:
        import excel2scb as _e2s
        direct = getattr(_e2s, "DIRECT_HANGUL", False)
    except Exception:
        direct = False
    print(f"구조 오류: {len(struct_bad)}개 파일")
    for rel, iss in struct_bad[:30]:
        print("  ", rel, iss)
    if direct:
        print(f"한글 포함: {len(hangul_warn)}개 파일 (직접 등록 모드 — 정상. 직접 등록 폰트와 함께 배포할 것)")
    else:
        print(f"미매핑 한글 경고: {len(hangul_warn)}개 파일 (빈 글리프로 표시됨)")
        for rel, hs in hangul_warn[:10]:
            print("  ", rel, hs)
    if struct_bad:
        print("\n❌ 구조 오류 — 배포 금지")
        sys.exit(1)
    print("\n✅ 구조 검증 통과 — 배포 가능")
    sys.exit(0)


if __name__ == "__main__":
    main()
