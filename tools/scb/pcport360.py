# -*- coding: utf-8 -*-
r"""
pcport360.py — PC 포트(360 리컴파일)용 한글 SCB: **360 원본 dec에 한글 MSG 테이블만 이식**

배경 (2026-10-23, PS3_VS_360.md §2.3-b, 워크로그 §34):
  기존 PC 배포(deploy_pcport.py ← excel2scb output_pcport)는 PS3 순정 dec에 한글을 넣은
  평문을 그대로 360 트리에 넣었다. 그 결과 360 엔진에서 PS3 스크립트 로직(CMD 등이 다른
  파일 다수)과 PS3식 커뮤 음성(BNSF flag 0, 360 원본은 2)이 돌고 있었다.
  이 도구는 360 원본 dec를 바탕으로 MSG 섹션만 excel2scb와 같은 규칙으로 리빌드한다:
    - 번역 매칭·rewrap·116B 캡: excel2scb.resolve_translations (PS3 인덱스 기준 그대로)
    - MSG 테이블 리빌드: excel2scb.build_msg_block (CLAUDE.md 규칙 3)
    - 섹션 디렉터리 + pac 헤더 4필드 갱신: excel2scb.replace_msg_section (규칙 4)
  PS3 MSG 인덱스 → 360 인덱스는 원문 텍스트 정렬로 대응시킨다(대부분 1:1 동일).

입력(전부 읽기 전용):
  PS3 순정 SCB  : USRDIR\gscript - 복사본          (번역 엑셀 abs_offset의 기준)
  360 원본 SCB  : Desktop\unpack\imas2\resource\gscript  (table360.bin, 풋터 32B)
  번역 엑셀      : excel2scb.choose_excel_path() (게임 tools의 translation_2.xlsx)
출력(게임 tools 폴더):
  output_pcport360\<rel>.scb        360 기반 평문 pac (360 엔진은 평문 pac 수용)
  pcport360_classify.json / .md     PS3 vs 360 섹션 비교 분류
  pcport360_build_report.json / .md 대응표·미대응 행 보고

사용 (게임 tools 폴더에서):
  python pcport360.py classify
  python pcport360.py build [rel ...] [--excel <웹앱 회수본.xlsx>]
  python pcport360.py validate        # 종료코드 0 = 통과, 1 = 구조 오류
  python pcport360.py stage [dest]    # 인게임 확인용: game_kor 사본(기본 imas2pc\game_kor360_test)에만 배치
배포: python deploy_pcport.py --src360   (validate 통과 시에만, game_kor 전용 — 인게임 확인 뒤)
"""
import os
import sys
import json
import struct
import difflib
import argparse
import collections

from Crypto.Cipher import AES

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scb_common as common          # noqa: E402
import excel2scb as e2s              # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
PS3_ORIG = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\gscript - 복사본"
X360_ORIG = r"C:\Users\jackfilm\Desktop\unpack\imas2\resource\gscript"
TABLE360 = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\imas2dec\imas2dec\table360.bin"
OUT = os.path.join(GAME_TOOLS, "output_pcport360")
LOGIC_TAGS = ("CMD", "LBL", "LBN", "RSC", "RSN", "VCN")

_T3 = None


def dec360(raw: bytes) -> bytes:
    """360 SCB 복호화: 키 테이블 table360.bin, 풋터 32B(PS3는 64B)."""
    global _T3
    if _T3 is None:
        _T3 = open(TABLE360, "rb").read()
    n = len(raw)
    key = common.derive_key(_T3, raw[n - 31], raw[n - 30], raw[n - 29])
    body = raw[:n - 32]
    body = body[:len(body) - len(body) % 16]
    out = AES.new(key, AES.MODE_CBC, b"\x00" * 16).decrypt(body)[16:]
    if out[:4] != b"pac\x00":
        raise ValueError("360 복호화 결과가 pac이 아님")
    return out


def load_ps3(rel):
    return common.decrypt_scb(open(os.path.join(PS3_ORIG, rel), "rb").read())


def load_360(rel):
    return dec360(open(os.path.join(X360_ORIG, rel), "rb").read())


def scb_rels(root):
    out = {}
    for dp, _dn, fns in os.walk(root):
        for f in fns:
            if f.lower().endswith(".scb"):
                rel = os.path.relpath(os.path.join(dp, f), root)
                if not rel.lower().startswith("tools"):
                    out[rel.lower()] = rel
    return out


# ---------------------------------------------------------------- 구조 비교

def pac_subs(d):
    n = struct.unpack_from(">I", d, 0x0C)[0]
    out = []
    for i in range(n):
        sz, of = struct.unpack_from(">II", d, 0x40 + i * 0x20 + 8)
        out.append(d[0x80 + of:0x80 + of + sz])
    return out


def bnsf_flags(blob):
    """서브파일(컷씬 pac) 안 BNSF 음성의 sfmt 플래그(BNSF+0x14 u16) 목록."""
    out, i = [], blob.find(b"BNSF")
    while i >= 0:
        if blob[i + 8:i + 12] == b"IS14":
            out.append(struct.unpack_from(">H", blob, i + 0x14)[0])
        i = blob.find(b"BNSF", i + 4)
    return out


def msg_texts(d):
    s = common.parse_section_dir(d)
    if "MSG" not in s:
        return None
    return [x["text"] for x in e2s.parse_msg_table(d, s["MSG"][0])["strings"]]


def compare(p, x):
    sp, sx = common.parse_section_dir(p), common.parse_section_dir(x)
    diff = []
    for t in sorted(set(sp) | set(sx)):
        if t not in sp or t not in sx:
            diff.append(t + "?")
        elif p[sp[t][0]:sp[t][0] + sp[t][1]] != x[sx[t][0]:sx[t][0] + sx[t][1]]:
            diff.append(t)
    subs_p, subs_x = pac_subs(p), pac_subs(x)
    sub_same = subs_p[1:] == subs_x[1:]
    fp = [f for s in subs_p[1:] for f in bnsf_flags(s)]
    fx = [f for s in subs_x[1:] for f in bnsf_flags(s)]
    logic = [t for t in diff if t.rstrip("?") in LOGIC_TAGS]
    if p == x:
        kind = "동일"
    elif logic:
        kind = "로직 다름"
    elif "MSG" in diff:
        kind = "MSG만 다름"
    elif not diff:
        kind = "음성/서브파일만 다름" if not sub_same else "헤더만 다름"
    else:
        kind = "기타"
    tp, tx = msg_texts(p), msg_texts(x)
    return {
        "kind": kind, "sections": diff, "sub_same": sub_same,
        "voice_ps3": dict(collections.Counter(fp)), "voice_360": dict(collections.Counter(fx)),
        "voice_diff": fp != fx or not sub_same,
        "msg_ps3": len(tp or []), "msg_360": len(tx or []), "msg_text_same": tp == tx,
    }


def cmd_classify(_a):
    ps3, x = scb_rels(PS3_ORIG), scb_rels(X360_ORIG)
    deploy = set(scb_rels(os.path.join(GAME_TOOLS, "output_pcport")))
    res, bad = {}, []
    for k in sorted(set(ps3) & set(x)):
        try:
            r = compare(load_ps3(ps3[k]), load_360(x[k]))
        except Exception as ex:
            bad.append((ps3[k], repr(ex)))
            continue
        r["deployed"] = k in deploy
        res[ps3[k]] = r
    cnt = collections.Counter(r["kind"] for r in res.values())
    cnt_dep = collections.Counter(r["kind"] for r in res.values() if r["deployed"])
    voice = collections.Counter((tuple(sorted(r["voice_ps3"])), tuple(sorted(r["voice_360"])))
                                for r in res.values() if r["deployed"])
    json.dump({"files": res, "decrypt_errors": bad}, open(os.path.join(GAME_TOOLS, "pcport360_classify.json"),
              "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    L = ["# PS3 순정 vs 360 원본 SCB 비교 (pcport360.py classify)", "",
         f"공통 {len(res)}개 (PS3 전용 {len(set(ps3) - set(x))}, 360 전용 {len(set(x) - set(ps3))}, "
         f"복호화 오류 {len(bad)}), 그중 현 PC 배포 대상 {sum(r['deployed'] for r in res.values())}개", "",
         "| 분류 | 전체 | 배포 대상 |", "|---|---|---|"]
    for k, v in cnt.most_common():
        L.append(f"| {k} | {v} | {cnt_dep.get(k, 0)} |")
    L += ["", "음성(BNSF sfmt 플래그, 배포 대상): PS3 → 360"]
    for (fp, fx), v in voice.most_common():
        L.append(f"- PS3 {list(fp) or '음성 없음'} → 360 {list(fx) or '음성 없음'}: {v}개")
    L += ["", "## 로직 다름 / MSG만 다름 목록", "", "| 파일 | 분류 | 다른 섹션 | MSG 수 PS3→360 | 원문 동일 | 배포 대상 |",
          "|---|---|---|---|---|---|"]
    for rel, r in res.items():
        if r["kind"] in ("로직 다름", "MSG만 다름", "기타"):
            L.append(f"| {rel} | {r['kind']} | {','.join(r['sections'])} | {r['msg_ps3']}→{r['msg_360']} | "
                     f"{'예' if r['msg_text_same'] else '아니오'} | {'예' if r['deployed'] else ''} |")
    open(os.path.join(GAME_TOOLS, "pcport360_classify.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:20]))
    print(f"→ {os.path.join(GAME_TOOLS, 'pcport360_classify.md')}")


# ---------------------------------------------------------------- 인덱스 대응

def align(tp, tx):
    """PS3 MSG 문자열 목록 tp → 360 목록 tx 인덱스 대응.
    Returns (mapping{ps3_i: x_i}, approx{ps3_i: ratio}) — approx는 원문이 달라진 짝."""
    if tp == tx:
        return {i: i for i in range(len(tp))}, {}
    mapping, approx = {}, {}
    sm = difflib.SequenceMatcher(None, tp, tx, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
        elif op == "replace":
            # 블록 안에서 순서를 지키며 유사도 0.5 이상만 짝짓기(같은 길이면 위치 짝 우선)
            if i2 - i1 == j2 - j1:
                for k in range(i2 - i1):
                    r = difflib.SequenceMatcher(None, tp[i1 + k], tx[j1 + k]).ratio()
                    if r >= 0.5:
                        mapping[i1 + k] = j1 + k
                        approx[i1 + k] = round(r, 2)
            else:
                j = j1
                for i in range(i1, i2):
                    best = None
                    for jj in range(j, j2):
                        r = difflib.SequenceMatcher(None, tp[i], tx[jj]).ratio()
                        if r >= 0.6 and (best is None or r > best[1]):
                            best = (jj, r)
                    if best:
                        mapping[i] = best[0]
                        approx[i] = round(best[1], 2)
                        j = best[0] + 1
    return mapping, approx


# ---------------------------------------------------------------- 빌드

def excel_path():
    p = e2s.choose_excel_path()
    return p if os.path.exists(p) else os.path.join(GAME_TOOLS, "translation_2.xlsx")


def load_x360_translations():
    """웹앱 회수(webapp_pull.py script)가 만든 최신 translation_x360_*.json:
    {rel: {x인덱스(str): {"jp": 360 원문, "kr": 번역}}} — 360에만 있는 대사."""
    import glob
    fs = sorted(glob.glob(os.path.join(GAME_TOOLS, "translation_x360_*.json")))
    if not fs:
        return None, {}
    d = json.load(open(fs[-1], encoding="utf-8"))
    return fs[-1], {k.replace("/", "\\").lower(): v for k, v in d.items()}


def build_one(rel, abs_map, font_map, x360_tr=None):
    p, x = load_ps3(rel), load_360(rel)
    sp, sx = common.parse_section_dir(p), common.parse_section_dir(x)
    if "MSG" not in sp or "MSG" not in sx:
        return None, {"skip": "MSG 없음"}
    pp = e2s.parse_msg_table(p, sp["MSG"][0])
    new_ps3, recovered, misses, garbage = e2s.resolve_translations(pp, abs_map, e2s.choice_indices(p))
    msg_abs, msg_size = sx["MSG"]
    px = e2s.parse_msg_table(x, msg_abs)
    tp = [s["text"] for s in pp["strings"]]
    tx = [s["text"] for s in px["strings"]]
    mapping, approx = align(tp, tx)
    new_x = {mapping[i]: t for i, t in new_ps3.items() if i in mapping}
    lost = sorted(i for i in new_ps3 if i not in mapping)
    mapped_x = set(mapping.values())
    untranslated = [j for j in range(len(tx)) if j not in mapped_x and tx[j].strip()]
    x_applied, x_stale = 0, []
    choices_x = e2s.choice_indices(x)
    approx_x = {mapping[i] for i in approx}   # 원문이 달라진 짝(버튼명 ○→A 등): 웹앱 360 행 번역이 있으면 우선
    for js, ent in (x360_tr or {}).items():
        j = int(js)
        if (j in untranslated or j in approx_x) and tx[j] == ent.get("jp") and ent.get("kr", "").strip():
            new_x[j] = e2s.rewrap(ent["kr"], j in choices_x)
            x_applied += 1
        else:
            x_stale.append(j)          # 원문/위치가 달라진 회수본 — 적용 안 함
    # 360 전용 대사의 번역 참고: 같은 파일 PS3 대사 중 가장 비슷한 것의 기존 번역
    idx_tr = {}
    for s_ in pp["strings"]:
        hit = abs_map.get(s_["abs_offset"])
        if hit and hit[1].strip() and not e2s.is_garbage_translation(hit[1]):
            idx_tr[s_["index"]] = hit[1]
    def suggest(jt):
        best = None
        for i, kr in idx_tr.items():
            r = difflib.SequenceMatcher(None, jt, tp[i]).ratio()
            if r >= 0.5 and (best is None or r > best["ratio"]):
                best = {"ps3": i, "jp": tp[i], "kr": kr, "ratio": round(r, 2)}
        return best
    new_msg = e2s.build_msg_block(px, new_x, font_map, msg_size)
    new_dec, _delta = e2s.replace_msg_section(x, msg_abs, msg_size, new_msg)
    rep = {
        "identity": tp == tx, "msg_ps3": len(tp), "msg_360": len(tx),
        "translated": len(new_x), "recovered": recovered, "misses": misses, "garbage": garbage,
        "approx": [{"ps3": i, "x": mapping[i], "ratio": r, "jp_ps3": tp[i], "jp_360": tx[mapping[i]],
                    "kr_ps3": idx_tr.get(i, "")}
                   for i, r in approx.items()],     # PS3 쪽이 미번역인 짝도 웹앱 360 행이 필요(전수 조사)
        "untranslated_360": [{"x": j, "jp_360": tx[j], "suggest": suggest(tx[j]),
                              "translated": j in new_x} for j in untranslated],
        "lost": [{"ps3": i, "jp_ps3": tp[i], "kr": idx_tr.get(i, "")} for i in lost],
        "x360_applied": x_applied, "x360_stale": x_stale,
    }
    return new_dec, rep


def cmd_build(a):
    xr = scb_rels(X360_ORIG)
    font_map = e2s.load_font_mapping()
    xl = a.excel or excel_path()
    print(f"번역 엑셀: {xl}")
    tr = e2s.load_translations(xl)
    xp, x360 = load_x360_translations()
    if xp:
        print(f"360 전용 대사 번역: {xp}")
    targets = {r.replace("/", "\\").lower() for r in a.rels} if a.rels else None
    import build_state                      # 배포 게이트용 표식(빌드 중·이전 빌드 배포 방지)
    if targets is None:
        build_state.mark_running("x360", xl)
    report, ok, skipped, fail = {}, 0, [], []
    for rel, abs_map in sorted(tr.items()):
        relw = rel.replace("/", "\\")
        if targets is not None and relw.lower() not in targets:
            continue
        if relw.lower() not in xr:
            skipped.append(relw)          # PS3 전용(ryu 등) — 360 트리에 없음
            continue
        try:
            new_dec, rep = build_one(relw, abs_map, font_map, x360.get(relw.lower()))
        except Exception as ex:
            fail.append((relw, repr(ex)))
            continue
        report[relw] = rep
        if new_dec is None:
            continue
        dst = os.path.join(OUT, relw)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(new_dec)
        ok += 1
    json.dump({"excel": xl, "x360": xp, "files": report, "skipped_ps3_only": skipped, "failed": fail},
              open(os.path.join(GAME_TOOLS, "pcport360_build_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    reps = [r for r in report.values() if "skip" not in r]
    n_id = sum(r["identity"] for r in reps)
    L = ["# 360 원본 기반 한글 MSG 이식 빌드 (pcport360.py build)", "",
         f"번역 엑셀: {os.path.basename(xl)}", "",
         f"- 생성 {ok}개 → output_pcport360\\ (PS3 전용이라 제외 {len(skipped)}개, 실패 {len(fail)}개)",
         f"- MSG 인덱스 1:1 동일(원문 목록 일치) {n_id}개, 텍스트 정렬로 대응 {len(reps) - n_id}개",
         f"- 이식된 번역 {sum(r['translated'] for r in reps):,}줄",
         f"- 원문이 달라진 짝(PS3 문구 수정분, 번역은 이식) {sum(len(r['approx']) for r in reps)}줄",
         f"- **대응 안 된 PS3 번역(360에 해당 대사 없음, 버림)** {sum(len(r['lost']) for r in reps)}줄",
         f"- **360에만 있는 대사** {sum(len(r['untranslated_360']) for r in reps)}줄 — 웹앱 번역 반영 "
         f"{sum(r['x360_applied'] for r in reps)}줄, 나머지는 일본어로 남음"
         + (f" (회수본과 원문 불일치로 미적용 {sum(len(r['x360_stale']) for r in reps)}줄)"
            if any(r['x360_stale'] for r in reps) else ""), ""]
    if fail:
        L += ["## 실패", ""] + [f"- {r}: {e}" for r, e in fail] + [""]
    L += ["## 파일별 (1:1이 아닌 것)", "", "| 파일 | MSG PS3→360 | 이식 | 원문 다른 짝 | 버린 번역 | 360 전용 대사 |",
          "|---|---|---|---|---|---|"]
    for rel, r in report.items():
        if "skip" in r or r["identity"]:
            continue
        L.append(f"| {rel} | {r['msg_ps3']}→{r['msg_360']} | {r['translated']} | {len(r['approx'])} | "
                 f"{len(r['lost'])} | {len(r['untranslated_360'])} |")
    L += ["", "## 360에만 있는 대사 (번역 필요 — 일본어 그대로 출력됨)", ""]
    for rel, r in report.items():
        for u in r.get("untranslated_360", []):
            L.append(f"- {rel} #{u['x']}: {u['jp_360'][:60]!r}")
    L += ["", "## 버린 PS3 번역 (360에 대응 대사 없음)", ""]
    for rel, r in report.items():
        for u in r.get("lost", []):
            L.append(f"- {rel} PS3#{u['ps3']}: {u['jp_ps3'][:60]!r}")
    open(os.path.join(GAME_TOOLS, "pcport360_build_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:12]))
    print(f"→ {os.path.join(GAME_TOOLS, 'pcport360_build_report.md')}")
    if targets is None:
        build_state.mark_done("x360", ok=not fail)
    if fail:
        sys.exit(1)


# ---------------------------------------------------------------- 검증 게이트

def validate_all(log=print):
    """output_pcport360 전수: validate_output.validate_dec(구조) + 360 원본 대비
    MSG 외 섹션·서브파일(음성/컷씬) 바이트 불변, MSG 개수 불변."""
    import validate_output as V
    outs = scb_rels(OUT)
    bad = []
    for rel in sorted(outs.values()):
        try:
            d = open(os.path.join(OUT, rel), "rb").read()
            o = load_360(rel)
            issues, _hangul = V.validate_dec(d, o)
            sd, so = common.parse_section_dir(d), common.parse_section_dir(o)
            if set(sd) != set(so):
                issues.append("섹션 목록 다름")
            for t in so:
                if t != "MSG" and d[sd[t][0]:sd[t][0] + sd[t][1]] != o[so[t][0]:so[t][0] + so[t][1]]:
                    issues.append(f"{t} 섹션이 360 원본과 다름")
            if pac_subs(d)[1:] != pac_subs(o)[1:]:
                issues.append("서브파일(컷씬/음성)이 360 원본과 다름")
            if msg_texts(d) is None or len(msg_texts(d)) != len(msg_texts(o)):
                issues.append("MSG 개수가 360 원본과 다름")
            # SCB 헤더: 0x88(SCB 크기-32)과 섹션 디렉터리의 len/ofs 필드만 바뀔 수 있음
            hdr_end = min(a for a, _n in so.values())
            allowed = set(range(0x88, 0x8C))
            for i in range(struct.unpack_from(">I", o, 0x8C)[0]):
                allowed |= set(range(0xF0 + i * 0x20 + 8, 0xF0 + i * 0x20 + 16))
            if any(d[k] != o[k] and k not in allowed for k in range(0x80, hdr_end)):
                issues.append("SCB 헤더가 크기 필드 외에 바뀜")
        except Exception as ex:
            issues = [f"예외: {ex!r}"]
        if issues:
            bad.append((rel, issues[:4]))
    log(f"검증 대상: {len(outs)}개 (360 원본 기준)")
    log(f"구조 오류: {len(bad)}개 파일")
    for rel, iss in bad[:30]:
        log(f"   {rel} {iss}")
    return len(outs) > 0 and not bad


def cmd_validate(_a):
    if validate_all():
        print("\n✅ 360 기준 구조 검증 통과 — deploy_pcport.py --src360 가능")
        sys.exit(0)
    print("\n❌ 구조 오류 — 배포 금지")
    sys.exit(1)


# ---------------------------------------------------------------- PS3 로직 오버레이 (ps3-360-pc 요청, KOR 승인 2026-10-23)

def _clips(blob, base=0):
    """blob 안 BNSF(IS14) 클립 목록 [(절대 위치, 크기)]."""
    out, i = [], blob.find(b"BNSF")
    while i >= 0:
        size = struct.unpack_from(">I", blob, i + 4)[0] + 8
        if blob[i + 8:i + 12] == b"IS14":
            out.append((base + i, size))
        i = blob.find(b"BNSF", i + max(size, 4))
    return out


def voice_to_360(dec_p, dec_x):
    """PS3 dec의 컷씬 서브파일 음성 클립을 같은 대사의 360 클립으로 제자리 교체.
    360 클립은 헤더·크기가 같고 sfmt 플래그(BNSF+0x14)만 0→2이며 페이로드 일부가 다르다(인코딩 변형) —
    플래그만 바꾸면 안 되고 360 클립 바이트를 통째로 써야 한다. 짝 = 같은 크기·같은 헤더(플래그 제외) 중
    바이트 일치가 가장 많은 것. 크기 불변이라 pac 재조립 없음."""
    out = bytearray(dec_p)
    xs = []
    for blob in pac_subs(dec_x)[1:]:
        xs += [blob[a:a + s] for a, s in _clips(blob)]
    n = struct.unpack_from(">I", dec_p, 0x0C)[0]
    done, miss = 0, 0
    for k in range(1, n):
        sz, of = struct.unpack_from(">II", dec_p, 0x40 + k * 0x20 + 8)
        base = 0x80 + of
        for a, s in _clips(dec_p[base:base + sz], base):
            c = dec_p[a:a + s]
            hdr = c[:0x14] + c[0x16:0x30]
            cands = [x for x in xs if len(x) == s and x[:0x14] + x[0x16:0x30] == hdr]
            if not cands:
                miss += 1
                continue
            best = max(cands, key=lambda x: sum(1 for u, v in zip(x[0x30::7], c[0x30::7]) if u == v))
            out[a:a + s] = best
            done += 1
    return bytes(out), {"voice_replaced": done, "voice_unmatched": miss}


def build_ps3_logic(rel, out_dir, abs_map, font_map):
    """PS3 로직(CMD/LBL/LBN/VCN = PS3 순정 백업) + 웹앱 PS3 행 한글 MSG + 360 음성 클립 → 평문 pac(360 엔진은 평문 pac 수용).
    out_dir은 game_kor·공유 game·테스터 패키지 밖이어야 한다. → (out_path, report)"""
    low = os.path.abspath(out_dir).lower()
    if any(k in low for k in ("game_kor", "build_imas2_o2\\game", "tester", "dev_hdd0")):
        raise ValueError(f"출력 폴더 거부(game_kor/공유 game/테스터/PS3 게임 폴더 금지): {out_dir}")
    import validate_output as vo
    p, x = load_ps3(rel), load_360(rel)
    sp = common.parse_section_dir(p)
    msg_abs, msg_size = sp["MSG"]
    pp = e2s.parse_msg_table(p, msg_abs)
    new_by_idx, recovered, misses, garbage = e2s.resolve_translations(pp, abs_map, e2s.choice_indices(p))
    new_msg = e2s.build_msg_block(pp, new_by_idx, font_map, msg_size)
    new_dec, _delta = e2s.replace_msg_section(p, msg_abs, msg_size, new_msg)
    new_dec, vrep = voice_to_360(new_dec, x)
    issues, _h = vo.validate_dec(new_dec, p)
    if issues:
        raise ValueError(f"{rel}: 구조 검증 실패 {issues[:3]}")
    untr = [{"i": s_["index"], "jp": s_["text"]} for s_ in pp["strings"]
            if s_["text"].strip() and s_["index"] not in new_by_idx]
    dst = os.path.join(out_dir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "wb").write(new_dec)
    return dst, {"msg": len(pp["strings"]), "translated": len(new_by_idx), "untranslated": untr,
                 "recovered": recovered, "misses": misses, "garbage": garbage, **vrep, "size": len(new_dec)}


def cmd_ps3logic(a):
    import glob
    newest = max(glob.glob(os.path.join(GAME_TOOLS, "translation_webapp_*.xlsx")), key=os.path.getmtime, default=None)
    xl = a.excel or newest or excel_path()      # 기본 = 최신 웹앱 회수본(translation_2는 미번역이 많다 — ps3-360-pc 지적)
    print(f"번역 엑셀: {xl}")
    tr = e2s.load_translations(xl)
    font_map = e2s.load_font_mapping()
    by_low = {k.replace("/", "\\").lower(): v for k, v in tr.items()}
    rep = {}
    for rel in a.rels:
        relw = rel.replace("/", "\\")
        dst, r = build_ps3_logic(relw, a.out, by_low.get(relw.lower(), {}), font_map)
        rep[relw] = r
        print(f"  {relw}: MSG {r['translated']}/{r['msg']} 한글, 미번역 {len(r['untranslated'])}, "
              f"음성 360 클립 {r['voice_replaced']} (짝 없음 {r['voice_unmatched']}) → {dst}")
    json.dump({"excel": xl, "files": rep}, open(os.path.join(a.out, "ps3logic_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"→ {os.path.join(a.out, 'ps3logic_report.json')}")


GAME_KOR = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor"
TEST_ROOT = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor360_test"


def cmd_stage(a):
    """인게임 확인용 별도 디스크 루트: game_kor 전체 사본에 360 기반 SCB만 넣는다.
    game_kor·공유 game은 건드리지 않는다. 실행은 IMAS2PC_DISC_ROOT=<dest>."""
    import shutil
    import hashlib
    import subprocess
    dest = os.path.abspath(a.dest)
    if os.path.normcase(dest) in (os.path.normcase(GAME_KOR),
                                  os.path.normcase(r"C:\Users\jackfilm\Desktop\imas2pc\build_imas2_o2\game")):
        sys.exit("❌ stage 대상은 별도 테스트 루트여야 함 (game_kor·공유 game 금지)")
    if not validate_all():
        sys.exit("❌ 360 기준 구조 검증 실패 — stage 중단")
    if not os.path.isdir(dest):
        print(f"game_kor 사본 생성: {dest}")
        r = subprocess.run(["robocopy", GAME_KOR, dest, "/E", "/NFL", "/NDL", "/NJH", "/NP"])
        if r.returncode >= 8:
            sys.exit(f"❌ robocopy 실패 {r.returncode}")
    gs = os.path.join(dest, "resource", "gscript")
    man = {}
    for rel in sorted(scb_rels(OUT).values()):
        dst = os.path.join(gs, rel)
        if not os.path.exists(dst):
            continue
        shutil.copyfile(os.path.join(OUT, rel), dst)
        man[rel.replace("\\", "/")] = hashlib.sha256(open(dst, "rb").read()).hexdigest()
    json.dump(man, open(os.path.join(dest, "pcport360_stage_manifest.json"), "w"), indent=1)
    print(f"✅ {len(man)}개 SCB를 {gs}에 배치 (game_kor 불변). 실행: IMAS2PC_DISC_ROOT={dest}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("classify")
    b = sub.add_parser("build")
    b.add_argument("rels", nargs="*")
    b.add_argument("--excel", help="번역 엑셀(기본 translation_2.xlsx, 웹앱 회수본 translation_webapp_*.xlsx 지정 가능)")
    sub.add_parser("validate")
    s = sub.add_parser("stage")
    s.add_argument("dest", nargs="?", default=TEST_ROOT)
    q = sub.add_parser("ps3logic", help="PS3 로직 + 한글 MSG + 360 음성 평문 pac (PS3 오버레이용, game_kor 밖 출력)")
    q.add_argument("rels", nargs="+")
    q.add_argument("--out", required=True)
    q.add_argument("--excel", help="번역 엑셀(기본: 최신 회수본/translation_2)")
    a = ap.parse_args()
    {"classify": cmd_classify, "build": cmd_build, "validate": cmd_validate, "stage": cmd_stage,
     "ps3logic": cmd_ps3logic}[a.cmd](a)


if __name__ == "__main__":
    main()
