#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IM@S2 XMB 텍스트 테이블 도구 (dump / build)

대상 3종 (이미지 텍스트 추출에서 "텍스처 아님"으로 분류된 텍스트 데이터):
  text/install.xmb            설치/트로피 시스템 메시지 (단독 XMB, 암호화)
  ranker/ranker_npc.xmb       라이벌 NPC 유닛/아이돌명 (단독 XMB, 암호화)
  scene/exep_init.mpc         pac 안에 XMB 1개 내장 (ジュピター 소개 등)

XMB 구조 (ranker_npc/install 역분석으로 확정, big-endian):
  +0x00 'XMB '  +0x04 nodeCount  +0x08 attrCount  +0x0C nameCount  +0x10 idCount
  +0x14 u32 ofs[6]: 이름색인(secA) / 노드(16B×n) / 속성(8B×n) / id색인 / 이름문자열 / 값
  노드 16B: u32 nameOfs, u16 attrCount, u16 childCount, u16 firstAttr, u16 firstChild,
            u16 parent, u16 0xFFFF
  속성 8B: u32 nameOfs(이름문자열 섹션 내), u32 valueOfs(값 섹션 내)
  값 섹션: 'id' 속성 값은 ASCII+\0, '_text' 속성 값은 UTF-16BE+\0\0
  id색인: (id valueOfs, node index) 8B 쌍, id 문자열 기준 정렬(바이너리 서치용)

build는 **파일 크기를 원본과 동일하게 유지**한다(뒤쪽 0 패딩). 값 섹션이 원본보다
커지면 오류 — 한국어가 일본어보다 길어질 때는 문구를 줄일 것. _text만 교체하고
id/구조/이름은 불변이므로 id색인은 재계산이 필요 없다(id 오프셋 불변 배치).

사용:
  python xmb_text.py dump         # 3종 JP+CN을 파싱해 xmb_texts.json 생성
  python xmb_text.py export-xlsx  # 번역팀용 엑셀 생성 (기본: 게임 tools/xmb_translation_1.xlsx)
  python xmb_text.py import-xlsx  # 엑셀의 '한국어' 열 → xmb_translations.json 반영
  python xmb_text.py build        # xmb_translations.json의 kr로 patched/ 산출 (검증 포함)
    --no-font-mapping             # 한글→한자 슬롯 매핑 인코딩 생략 (기본: 적용)
"""
import os
import sys
import json
import struct
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(
    JP_ROOT, "gscript", "tools", "font_mapping.json")

TARGETS = ["text\\install.xmb", "ranker\\ranker_npc.xmb", "scene\\exep_init.mpc"]


# ---------------------------------------------------------------- parse

def find_xmb(data: bytes) -> int:
    if data[:4] == b"XMB ":
        return 0
    i = data.find(b"XMB ")
    if i < 0:
        raise ValueError("XMB 시그니처 없음")
    return i


def parse_xmb(data: bytes, base: int):
    h = struct.unpack_from(">4I", data, base + 4)
    n_node, n_attr, n_name, n_id = h
    ofs = struct.unpack_from(">6I", data, base + 0x14)
    o_sec_a, o_node, o_attr, o_idmap, o_name, o_val = (base + o for o in ofs)

    def name_at(off):
        end = data.index(b"\x00", o_name + off)
        return data[o_name + off:end].decode("ascii")

    nodes = []
    for i in range(n_node):
        f = struct.unpack_from(">IHHHHHH", data, o_node + i * 16)
        nodes.append({"name": name_at(f[0]), "n_attr": f[1], "n_child": f[2],
                      "first_attr": f[3], "first_child": f[4], "parent": f[5]})
    attrs = []
    for i in range(n_attr):
        nofs, vofs = struct.unpack_from(">II", data, o_attr + i * 8)
        attrs.append({"name": name_at(nofs), "off": i * 8 + (o_attr - base),
                      "vofs": vofs})

    def val_ascii(vofs):
        p = o_val + vofs
        end = data.index(b"\x00", p)
        return data[p:end].decode("ascii")

    def val_utf16(vofs):
        p = o_val + vofs
        end = p
        while data[end:end + 2] != b"\x00\x00":
            end += 2
        return data[p:end].decode("utf-16-be")

    # 노드별 id/_text 수집
    entries = []
    for ni, nd in enumerate(nodes):
        rec = {"node": ni, "name": nd["name"]}
        for ai in range(nd["first_attr"],
                        nd["first_attr"] + nd["n_attr"]) if nd["n_attr"] else []:
            a = attrs[ai]
            if a["name"] == "_text":
                rec["text"] = val_utf16(a["vofs"])
                rec["_text_attr"] = ai
            else:
                rec.setdefault("attrs", {})[a["name"]] = val_ascii(a["vofs"])
        # 부모의 id를 상속 표시 (text_node는 보통 id가 부모 쪽에 있음)
        entries.append(rec)
    return {"base": base, "counts": h, "ofs": ofs, "nodes": nodes,
            "attrs": attrs, "o_attr": o_attr, "o_val": o_val,
            "entries": entries}


def entry_key(x, nodes):
    """text_node의 식별자: 자신 또는 조상의 id 속성."""
    ni = x["node"]
    while ni != 0xFFFF:
        nd = nodes[ni]
        e = nd.get("_entry")
        if e and e.get("attrs", {}).get("id"):
            return e["attrs"]["id"]
        ni = nd["parent"]
    return f"node{x['node']}"


def collect_texts(parsed):
    for nd, e in zip(parsed["nodes"], parsed["entries"]):
        nd["_entry"] = e
    out = []
    for e in parsed["entries"]:
        if "text" in e:
            out.append({"id": entry_key(e, parsed["nodes"]),
                        "attr": e["_text_attr"], "text": e["text"]})
    return out


# ---------------------------------------------------------------- dump

def load_file(root, rel):
    """추출 캐시(복호화본)를 사용한다. extract_image_text.py 선실행 필요."""
    p = os.path.join(OUT_DEFAULT, "_cache", root, rel)
    if not os.path.exists(p):
        raise FileNotFoundError(f"{p} — 먼저 extract_image_text.py를 실행하세요")
    return open(p, "rb").read()


def cmd_dump(_args):
    table = {}
    for rel in TARGETS:
        jp = load_file("jp", rel)
        cn = load_file("cn", rel)
        pj = parse_xmb(jp, find_xmb(jp))
        pc = parse_xmb(cn, find_xmb(cn))
        tj, tc = collect_texts(pj), collect_texts(pc)
        rows = []
        cn_by_i = {i: t for i, t in enumerate(tc)}
        for i, t in enumerate(tj):
            rows.append({"id": t["id"], "jp": t["text"],
                         "cn": cn_by_i.get(i, {}).get("text", "")})
        table[rel.replace("\\", "/")] = rows
        print(f"{rel}: _text {len(rows)}개 (JP), CN {len(tc)}개")
    out = os.path.join(HERE, "xmb_texts.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=1)
    print(f"저장: {out}")
    # 번역 틀(없으면 생성 — 기존 파일은 보존)
    tr_path = os.path.join(HERE, "xmb_translations.json")
    if not os.path.exists(tr_path):
        tr = {rel: {r["id"]: {"jp": r["jp"], "cn": r["cn"], "kr": ""}
                    for r in rows_}
              for rel, rows_ in table.items()}
        with open(tr_path, "w", encoding="utf-8") as f:
            json.dump(tr, f, ensure_ascii=False, indent=1)
        print(f"번역 틀 생성: {tr_path} (kr 채운 뒤 build)")


# ---------------------------------------------------------------- build

def rebuild_xmb(data: bytes, base: int, repl: dict, log) -> bytes:
    """repl: {attr_index: 새 텍스트}. _text 값 섹션 재배치, 전체 크기 불변."""
    p = parse_xmb(data, base)
    o_attr, o_val = p["o_attr"], p["o_val"]
    end = len(data)  # 단독 XMB: 파일 끝까지가 값 섹션
    texts = collect_texts(p)
    tmap = {t["attr"]: t for t in texts}

    # 값 섹션 재구성: ASCII id들은 제자리 유지(최소 _text vofs 이전 영역 복사),
    # _text들은 그 뒤에 순서대로 재배치.
    first_txt = min(p["attrs"][t["attr"]]["vofs"] for t in texts)
    buf = bytearray(data[o_val:o_val + first_txt])
    new_vofs = {}
    for t in sorted(texts, key=lambda t: p["attrs"][t["attr"]]["vofs"]):
        s = repl.get(t["attr"], t["text"])
        if len(buf) % 2:
            buf.append(0)
        new_vofs[t["attr"]] = len(buf)
        buf += s.encode("utf-16-be") + b"\x00\x00"
    avail = end - o_val
    if len(buf) > avail:
        raise ValueError(f"값 섹션 초과: {len(buf)} > {avail}B — 문구를 줄이세요")
    buf += b"\x00" * (avail - len(buf))

    out = bytearray(data)
    out[o_val:end] = buf
    for ai, vofs in new_vofs.items():
        struct.pack_into(">I", out, o_attr + ai * 8 + 4, vofs)
    # 검증: 재파싱해 교체 텍스트 일치 + id/구조 불변
    p2 = parse_xmb(bytes(out), base)
    t2 = {t["attr"]: t for t in collect_texts(p2)}
    for ai, t in tmap.items():
        want = repl.get(ai, t["text"])
        assert t2[ai]["text"] == want, f"재파싱 불일치 attr{ai}"
        assert t2[ai]["id"] == t["id"], f"id 변동 attr{ai}"
    assert len(out) == len(data)
    used = max(new_vofs.values()) if new_vofs else 0
    log(f"    _text {len(repl)}/{len(texts)}개 교체, 값 섹션 사용 {used}B / 여유 {avail}B")
    return bytes(out)


def encode_with_mapping(s: str, mapping: dict, missing: set) -> str:
    out = []
    for ch in s:
        if "가" <= ch <= "힣":
            m = mapping.get(ch)
            if m is None:
                missing.add(ch)
                out.append(ch)
            else:
                out.append(m)
        else:
            out.append(ch)
    return "".join(out)


def cmd_build(args):
    tr_path = os.path.join(HERE, "xmb_translations.json")
    tr = json.load(open(tr_path, encoding="utf-8"))
    mapping = None
    if not args.no_font_mapping:
        mapping = json.load(open(MAPPING_PATH, encoding="utf-8"))
        print(f"폰트 매핑 {len(mapping)}자 적용 (한글→한자 슬롯)")
    missing = set()
    dst_dir = os.path.join(OUT_DEFAULT, "patched")
    for rel in TARGETS:
        key = rel.replace("\\", "/")
        kr = {i: v["kr"] for i, v in (tr.get(key) or {}).items() if v.get("kr")}
        if not kr:
            print(f"▶ {rel}: kr 번역 없음 — 스킵")
            continue
        print(f"▶ {rel} ({len(kr)}개)")
        data = load_file("jp", rel)
        base = find_xmb(data)
        p = parse_xmb(data, base)
        texts = collect_texts(p)
        by_id = {}
        for t in texts:
            by_id.setdefault(t["id"], []).append(t["attr"])
        repl = {}
        for tid, s in kr.items():
            if tid not in by_id:
                print(f"    [경고] id 없음: {tid}")
                continue
            if mapping:
                s = encode_with_mapping(s, mapping, missing)
            for ai in by_id[tid]:
                repl[ai] = s
        if base:  # pac 내장 → 그 구간만 교체
            # 내장 XMB 범위: base ~ 값 섹션 끝. 값 섹션 끝은 다음 pac 엔트리
            # 정렬 전까지인데, JP/CN diff가 값 섹션 안에서만 났으므로
            # "다음 0x10 정렬 + 원본 제로패딩 유지" 범위로 안전하게 자른다.
            o_val = p["o_val"]
            vend = max(p["attrs"][t["attr"]]["vofs"]
                       + 2 * len(t["text"]) + 2 for t in texts)
            end = o_val + vend
            while end < len(data) and end % 16 and data[end] == 0:
                end += 1
            # pac 내장은 단독 세그먼트로 떼어 재빌드 후 되붙인다
            rebuilt = rebuild_xmb(bytes(data[base:end]), 0, repl, print)
            out = data[:base] + rebuilt + data[end:]
            assert len(out) == len(data)
        else:
            out = rebuild_xmb(data, 0, repl, print)
        dst = os.path.join(dst_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(out)
        print(f"    → patched\\{rel}")
    if missing:
        print(f"[경고] 폰트 매핑에 없는 한글 {len(missing)}자: {''.join(sorted(missing))}")
        print("  → font-atlas 세션에 슬롯 추가 요청 필요 (repatch_fonts.py NEW_CHARS)")


# ---------------------------------------------------------------- xlsx

XLSX_DEFAULT = os.path.join(JP_ROOT, "gscript", "tools", "xmb_translation_1.xlsx")
XLSX_HEAD = ["파일", "id", "원문(JP)", "중국어역(CN)", "한국어(KR)", "메모"]


def cmd_export_xlsx(args):
    """번역팀용 엑셀: 파일별 시트, 기존 kr 제안은 미리 채움(검수 대상 표시)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    table = json.load(open(os.path.join(HERE, "xmb_texts.json"), encoding="utf-8"))
    tr_path = os.path.join(HERE, "xmb_translations.json")
    tr = json.load(open(tr_path, encoding="utf-8")) if os.path.exists(tr_path) else {}

    wb = Workbook()
    wb.remove(wb.active)
    wrap = Alignment(wrap_text=True, vertical="top")
    head_f = Font(bold=True)
    fill = PatternFill("solid", fgColor="FFF2CC")  # kr 제안 채워진 행 표시
    for rel, rows in table.items():
        ws = wb.create_sheet(rel.split("/")[-1][:28])
        ws.append(XLSX_HEAD)
        for c in ws[1]:
            c.font = head_f
        for r in rows:
            kr = (tr.get(rel, {}).get(r["id"]) or {}).get("kr", "")
            memo = "제안 — 검수 요망" if kr else ""
            ws.append([rel, r["id"], r["jp"], r["cn"], kr, memo])
            if kr:
                for c in ws[ws.max_row]:
                    c.fill = fill
        for col, w in zip("ABCDEF", (22, 14, 52, 52, 52, 16)):
            ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = wrap
        ws.freeze_panes = "A2"
    path = args.path or XLSX_DEFAULT
    if os.path.exists(path):
        raise SystemExit(f"[중단] 이미 존재: {path} — 기존 번역 엑셀을 덮지 않음. "
                         "--path로 새 파일명을 지정하세요")
    wb.save(path)
    n = sum(len(r) for r in table.values())
    print(f"엑셀 생성: {path} ({n}행, 시트 {len(table)}개)")
    print("한국어(KR) 열을 채워 import-xlsx 하면 됩니다. 줄바꿈은 셀 내 Alt+Enter.")


def cmd_import_xlsx(args):
    from openpyxl import load_workbook
    path = args.path or XLSX_DEFAULT
    wb = load_workbook(path, read_only=True)
    tr_path = os.path.join(HERE, "xmb_translations.json")
    tr = json.load(open(tr_path, encoding="utf-8"))
    n = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=2, values_only=True):
            rel, tid, _jp, _cn, kr = (row + (None,) * 5)[:5]
            if not rel or not tid or not kr:
                continue
            ent = tr.setdefault(str(rel), {}).setdefault(
                str(tid), {"jp": _jp or "", "cn": _cn or "", "kr": ""})
            if ent.get("kr") != str(kr):
                ent["kr"] = str(kr)
                n += 1
    with open(tr_path, "w", encoding="utf-8") as f:
        json.dump(tr, f, ensure_ascii=False, indent=1)
    print(f"반영 {n}건 → {tr_path}. 이제 `python xmb_text.py build` 실행.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "build", "export-xlsx", "import-xlsx"])
    ap.add_argument("--no-font-mapping", action="store_true")
    ap.add_argument("--path", help="export/import-xlsx 대상 경로")
    args = ap.parse_args()
    {"dump": cmd_dump, "build": cmd_build,
     "export-xlsx": cmd_export_xlsx, "import-xlsx": cmd_import_xlsx}[args.cmd](args)


if __name__ == "__main__":
    main()
