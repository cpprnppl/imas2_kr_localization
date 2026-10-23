#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iM@S2 KOR 번역 플랫폼 — Supabase 시딩

rows 테이블에 3개 대분류의 전 행을 넣는다:
  xmb    : xmb_texts.json + xmb_translations.json (제안 kr은 st=1)
  script : translation_2.xlsx 전 시트 (번역문 있으면 st=1, 없으면 st=0)
  image  : index.json의 CN 수정 md5 그룹 (+ label_specs.json의 기존 문구)

기본은 **이미 있는 행을 건드리지 않는다**(ignore-duplicates) — 팀 수정 보호.
전체 덮어쓰기는 --force-merge (주의).

  python webapp_seed.py --code <팀암호> [--only xmb|script|image] [--force-merge]
  python webapp_seed.py --thumbs --service-key <SERVICE_ROLE_KEY>   # 썸네일 업로드

썸네일은 storage 버킷 tex(공개 읽기)에 jp/<md5>.png, cn/<md5>.png로 올린다.
service key는 버킷 생성/업로드에만 쓰며 어디에도 저장하지 않는다.
"""
import io
import os
import sys
import json
import argparse
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_image_text import OUT_DEFAULT, JP_ROOT  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "webapp_config.json"), encoding="utf-8"))
XLSX_PATH = os.path.join(JP_ROOT, "gscript", "tools", "translation_2.xlsx")

XMB_REL2GRP = {"text/install.xmb": "install",
               "ranker/ranker_npc.xmb": "ranker",
               "scene/exep_init.mpc": "exep_init"}


def xmb_grp_key(rel, tid):
    """가사(songinfo/<곡>/lyrics_*.xmb)는 단일 'lyrics' 그룹에 곡코드 접두 키로."""
    if rel.startswith("songinfo/"):
        return "lyrics", f"{rel.split('/')[1]}/{tid}"
    return XMB_REL2GRP[rel], tid


def req(method, path, body=None, headers=None, ctype="application/json"):
    h = {"apikey": CFG["anon_key"], "Authorization": f"Bearer {CFG['anon_key']}"}
    h.update(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else \
            json.dumps(body, ensure_ascii=False).encode("utf-8")
        h["Content-Type"] = ctype
    r = urllib.request.Request(CFG["url"] + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def rows_xmb():
    texts = json.load(open(os.path.join(HERE, "xmb_texts.json"), encoding="utf-8"))
    tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    out = []
    for rel, rows in texts.items():
        seen = {}
        for i, r in enumerate(rows):
            grp, tid = xmb_grp_key(rel, r["id"])
            k = seen.get(tid, 0)
            seen[tid] = k + 1
            key = tid if k == 0 else f"{tid}#{k}"
            kr = (tr.get(rel, {}).get(r["id"]) or {}).get("kr", "")
            out.append({"id": f"xmb:{grp}:{key}", "cat": "xmb", "grp": grp,
                        "seq": i, "key": key, "jp": r["jp"], "kr": kr,
                        "st": 1 if kr else 0, "ts": 0, "by": "", "meta": {}})
    return out


def rows_script():
    from openpyxl import load_workbook
    wb = load_workbook(XLSX_PATH, read_only=True)
    out = []
    for ws in wb.worksheets:
        t = ws.title
        if "(" not in t:
            continue
        grp = t.split("(", 1)[0]
        seen = {}
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
            sp, jp, kr, note, file, off, nbytes = (list(row) + [None] * 7)[:7]
            if jp is None and file is None:
                continue
            base = f"{file}:{off}"
            k = seen.get(base, 0)
            seen[base] = k + 1
            key = base if k == 0 else f"{base}#{k}"
            jp = str(jp) if jp is not None else ""
            kr = str(kr) if kr is not None else ""
            meta = {"sp": str(sp) if sp else "", "file": str(file) if file else "",
                    "off": off}
            if note:
                meta["note"] = str(note)
            out.append({"id": f"script:{grp}:{key}", "cat": "script", "grp": grp,
                        "seq": i, "key": key, "jp": jp, "kr": kr,
                        "st": 1 if kr else 0, "ts": 0, "by": "", "meta": meta})
    return out


def rows_script_x360():
    """PC 포트(360) 전용 대사: pcport360.py build 보고서의 untranslated_360 → script 행.
    id script:<폴더>:x360:<파일>#<360 MSG 인덱스>. 그룹 끝(seq 900000+)에 파일·인덱스 순.
    meta.suggest = 같은 파일 PS3 대사 중 가장 비슷한 것의 기존 번역(참고용, kr에는 안 넣음)."""
    p = os.path.join(JP_ROOT, "gscript", "tools", "pcport360_build_report.json")
    if not os.path.exists(p):
        print("  script360: pcport360_build_report.json 없음 — 먼저 python pcport360.py build")
        return []
    files = json.load(open(p, encoding="utf-8"))["files"]
    out = []
    for fi, (rel, r) in enumerate(sorted(files.items())):
        for u in r.get("untranslated_360", []):
            grp = rel.split("\\")[0]
            key = f"x360:{rel}#{u['x']}"
            meta = {"sp": "", "file": rel, "x360": True, "x_idx": u["x"],
                    "note": "360판(PC 포트)에만 있는 대사 — PS3판에는 없음"}
            if u.get("suggest"):
                meta["suggest"] = u["suggest"]
            out.append({"id": f"script:{grp}:{key}", "cat": "script", "grp": grp,
                        "seq": 900000 + fi * 1000 + u["x"], "key": key, "jp": u["jp_360"],
                        "kr": "", "st": 0, "ts": 0, "by": "", "meta": meta})
        # 원문이 PS3와 조금 다른 짝(○→A ボタン, Ｌ１→LB, 문구 수정): 지금은 PS3 번역이 그대로 들어간다.
        # 360 문구에 맞춘 번역을 받으려고 행을 따로 둔다 — kr이 비어 있으면 PS3 번역 유지(pcport360 build).
        for a in r.get("approx", []):
            grp = rel.split("\\")[0]
            key = f"x360:{rel}#{a['x']}"
            meta = {"sp": "", "file": rel, "x360": True, "x_idx": a["x"], "plat": "x360", "approx": True,
                    "note": "360판 원문이 PS3와 조금 다름(버튼명·문구 수정) — 지금은 PS3 번역이 임시로 들어감. "
                            "360 원문에 맞게 고쳐 넣으면 PC판에 반영",
                    "suggest": {"ps3": a["ps3"], "jp": a["jp_ps3"], "kr": a.get("kr_ps3", ""),
                                "ratio": a["ratio"]}}
            out.append({"id": f"script:{grp}:{key}", "cat": "script", "grp": grp,
                        "seq": 900000 + fi * 1000 + a["x"], "key": key, "jp": a["jp_360"],
                        "kr": "", "st": 0, "ts": 0, "by": "", "meta": meta})
    return out


def rows_npc_x360():
    """360판 NPC 명단(alf_common 등 4개 pac에 복제된 표)에서 같은 id에 PS3와 다른 이름이 든 43칸.
    id xmb:exep_init:x360:<id>. 번역은 pcport_apply.npc_kr_for가 원문 일치로만 적용한다.
    kr 초기값: 같은 원문의 PS3 번역이 있으면 그것(st=1, src_tr=seed)."""
    import pcport_apply as pa
    from platform_audit import dec_any
    from xmb_text import parse_xmb as _px, collect_texts as _ct
    tr = json.load(open(os.path.join(HERE, "xmb_translations.json"), encoding="utf-8"))
    ps3 = tr.get("scene/exep_init.mpc", {})
    byjp = {}
    for v in ps3.values():
        if v.get("kr"):
            byjp.setdefault(v["jp"], v["kr"])
    data = dec_any(open(os.path.join(pa.PORT, "game", "alf", "alf_common.mpc"), "rb").read(), "x360")
    ents, ds = pa.parse_pac(data)
    out = []
    for e in ents:
        seg = data[ds + e["ofs"]: ds + e["ofs"] + e["size"]]
        if seg[:4] != b"XMB ":
            continue
        texts = _ct(_px(seg, 0))
        if not any(t["id"].startswith(pa.NPC_PREFIX) for t in texts):
            continue
        for i, t in enumerate(texts):
            p = ps3.get(t["id"])
            if not p or p.get("jp") == t["text"]:
                continue
            kr = byjp.get(t["text"], "")
            meta = {"plat": "x360", "pair": f"xmb:exep_init:{t['id']}",
                    "plat_note": f"360판은 이 칸이 '{p['jp']}' 대신 '{t['text']}' (alf_common·NationwideRanking·"
                                 "ScheduleSelect·produce_etc 4곳 공통)",
                    "inject": "pcport_apply (원문 일치 확인 후 적용)"}
            if kr:
                meta["src_tr"] = "seed"
            out.append({"id": f"xmb:exep_init:x360:{t['id']}", "cat": "xmb", "grp": "exep_init",
                        "seq": 900000 + i, "key": f"x360:{t['id']}", "jp": t["text"], "kr": kr,
                        "st": 1 if kr else 0, "ts": 0, "by": "", "meta": meta})
        break
    return out


def image_index():
    idx = json.load(open(os.path.join(OUT_DEFAULT, "index.json"), encoding="utf-8"))
    groups = {}
    for rel, r in idx.items():
        texs = {t["n"]: t for t in r["jp"]["textures"]}
        for n in r.get("cn_modified", []):
            t = texs.get(n)
            if not t or "error" in t:
                continue
            g = groups.setdefault(t["md5"], {
                "md5": t["md5"], "w": t["w"], "h": t["h"], "fmt": t["fmt"],
                "locs": [], "png": t["png"], "rel0": rel})
            g["locs"].append(f"{rel}#{n:03d}")
    # CN 패치가 안 건드린 일본어 그림 (image_extra.json, 전수 점검 육안 확인분)
    ex = os.path.join(HERE, "image_extra.json")
    if os.path.exists(ex):
        for it in json.load(open(ex, encoding="utf-8"))["items"]:
            if it["md5"] in groups:
                continue
            # initialFix처럼 이미지 추출(index.json) 밖 파일은 항목에 치수·포맷·png를 직접 적어 둔다
            t = ({x["n"]: x for x in idx[it["rel"]]["jp"]["textures"]}[it["n"]] if it["rel"] in idx else it)
            groups[it["md5"]] = {"md5": it["md5"], "w": t["w"], "h": t["h"], "fmt": t["fmt"],
                                 "locs": it["locs"], "png": t["png"], "rel0": it["rel"], "jp": it["jp"]}
    return groups


def rows_image():
    groups = image_index()
    specs = {}
    sp_path = os.path.join(HERE, "label_specs.json")
    if os.path.exists(sp_path):
        specs = json.load(open(sp_path, encoding="utf-8")).get("items", {})
    out = []
    ordered = sorted(groups.values(), key=lambda g: (g["rel0"], g["locs"][0]))
    for i, g in enumerate(ordered):
        top = g["rel0"].split("\\")[0].split("/")[0]
        it = specs.get(g["md5"], {})
        kr = it.get("text", "")
        meta = {"w": g["w"], "h": g["h"], "fmt": g["fmt"], "locs": g["locs"], "mode": it.get("mode", "")}
        if g.get("jp"):
            meta["note"] = "중국어 패치가 안 건드린 일본어 그림 — 참고 그림(CN) 없음"
        out.append({"id": f"image:{top}:{g['md5']}", "cat": "image", "grp": top,
                    "seq": i, "key": g["md5"], "jp": g.get("jp", ""), "kr": kr,
                    "st": 1 if kr else 0, "ts": 0, "by": "", "meta": meta})
    # 레슨·커뮤 결과 배너(글자 타일 조립식 — tile_banner.py): 그림이 아니라 문구 행. 썸네일 = 칸 합성 PNG
    from tile_banner import BANNERS, SET_LABEL, PITCH, REL as BREL
    for j, (name, (jp, s)) in enumerate(BANNERS.items()):
        n = len(jp)
        it = specs.get(f"banner:{name}", {})
        kr = it.get("text", "")
        out.append({"id": f"image:game:banner_{name}", "cat": "image", "grp": "game",
                    "seq": len(ordered) + j, "key": f"banner_{name}", "jp": jp, "kr": kr,
                    "st": 1 if kr else 0, "ts": 0, "by": "",
                    "meta": {"kind": "글자 타일 배너", "w": PITCH * (n - 1) + 64, "h": 64, "fmt": "타일 조립",
                             "slots": n, "locs": [f"{BREL} ProResult/{name}_mc"],
                             "note": f"레슨·커뮤 결과 배너 — 글자 타일 {n}칸(56px 간격)에 한 글자씩. 공백도 한 칸, "
                                     f"짧으면 가운데 정렬. {SET_LABEL[s]} 색 세트는 레슨/커뮤 두 단어가 타일을 같이 쓰므로 "
                                     f"둘 다 번역돼야 적용되고, 두 단어의 서로 다른 글자 합이 타일 수를 넘으면 안 됨"}})
    return out


def seed_rows(code, only, force):
    batches = []
    if only in (None, "xmb"):
        batches.append(("xmb", rows_xmb()))
    if only in (None, "script"):
        batches.append(("script", rows_script()))
    if only in (None, "script", "script360"):
        batches.append(("script360", rows_script_x360()))
    if only in (None, "xmb", "npc360"):
        batches.append(("npc360", rows_npc_x360()))
    if only in (None, "image"):
        batches.append(("image", rows_image()))
    if only in (None, "dlc"):
        batches.append(("dlc", rows_dlc()))
    if only in (None, "dlcimg"):
        batches.append(("dlcimg", rows_dlc_images()))
    if only in (None, "gamedata"):
        batches.append(("gamedata", rows_gamedata()))
    prefer = "resolution=merge-duplicates,return=minimal" if force else \
        "resolution=ignore-duplicates,return=minimal"
    for name, rows in batches:
        n = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            st, body = req("POST", "/rest/v1/rows?on_conflict=id", chunk,
                           {"x-team-code": code, "Prefer": prefer})
            if st not in (200, 201):
                print(f"[실패] {name} batch {i}: HTTP {st} {body[:300]}")
                return False
            n += len(chunk)
            print(f"  {name}: {n}/{len(rows)}", end="\r")
        print(f"  {name}: {len(rows)}행 완료           ")
    return True


def upload_thumbs(service_key):
    from PIL import Image
    groups = image_index()
    auth = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    # 버킷 생성 (이미 있으면 409 무시)
    st, body = req("POST", "/storage/v1/bucket",
                   {"id": "tex", "name": "tex", "public": True}, auth)
    print(f"버킷 tex: HTTP {st}")
    n = 0
    for g in groups.values():
        for side, base in (("jp", "jp"), ("cn", "cn_ref")):
            src = os.path.join(OUT_DEFAULT, base,
                               os.path.dirname(g["rel0"]), g["png"])
            if not os.path.exists(src):
                continue
            # 원본 해상도 그대로 업로드 (뷰어 확대용 — 축소본은 분간 불가 문제)
            im = Image.open(src)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            h = dict(auth)
            h["x-upsert"] = "true"
            st, body = req("POST", f"/storage/v1/object/tex/{side}/{g['md5']}.png",
                           buf.getvalue(), h, ctype="image/png")
            if st not in (200, 201):
                print(f"[실패] {side}/{g['md5']}: HTTP {st} {body[:200]}")
                return False
            n += 1
            print(f"  썸네일 {n}", end="\r")
    print(f"  썸네일 {n}장 업로드 완료")
    return True


def rows_dlc():
    """dlc_text.py extract 산출(dlc_texts.json) → rows. 그룹: mail/catalog/package/songinfo/ranker."""
    p = os.path.join(HERE, "dlc_texts.json")
    if not os.path.exists(p):
        print("  dlc: dlc_texts.json 없음 — 먼저 python dlc_text.py extract")
        return []
    d = json.load(open(p, encoding="utf-8"))
    out = []
    for rid, v in d.items():
        out.append({"id": rid, "cat": "dlc", "grp": v["grp"], "seq": v["seq"],
                    "key": v["key"], "jp": v["jp"], "kr": v.get("kr", ""),
                    "st": v.get("st", 0), "ts": 0, "by": "", "meta": v.get("meta", {})})
    return out


DLC_TEX = os.path.join(OUT_DEFAULT, "dlc_tex")


def rows_gamedata():
    """game_xmb.py extract 산출(gamedata_texts.json) → rows."""
    p = os.path.join(HERE, "gamedata_texts.json")
    if not os.path.exists(p):
        print("  gamedata: gamedata_texts.json 없음 — 먼저 python game_xmb.py extract")
        return []
    d = json.load(open(p, encoding="utf-8"))
    return [{"id": rid, "cat": "gamedata", "grp": v["grp"], "seq": v["seq"],
             "key": v["key"], "jp": v["jp"], "kr": v.get("kr", ""), "st": v.get("st", 0),
             "ts": 0, "by": "", "meta": v.get("meta", {})} for rid, v in d.items()]


def dlc_image_groups():
    p = os.path.join(DLC_TEX, "index.json")
    if not os.path.exists(p):
        return []
    g = json.load(open(p, encoding="utf-8"))["groups"]
    return sorted((v for v in g.values() if v.get("text")),
                  key=lambda v: (v["text"], v["png"]))


def rows_dlc_images():
    """360 DLC 텍스처 중 텍스트 있는 것(dlc_images.py extract) → image/dlc 행."""
    out = []
    for i, g in enumerate(dlc_image_groups()):
        locs = [f"360:{L['pkg'][:6]}/{L['rel']}#{L['n']:03d}" for L in g["locs"]]
        out.append({"id": f"image:dlc:{g['md5']}", "cat": "image", "grp": "dlc",
                    "seq": i, "key": g["md5"], "jp": "", "kr": "", "st": 0,
                    "ts": 0, "by": "",
                    "meta": {"w": g["w"], "h": g["h"], "fmt": g["fmt"],
                             "locs": locs, "kind": g["text"], "mode": ""}})
    return out


def upload_dlc_thumbs(service_key):
    auth = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    n = 0
    for g in dlc_image_groups():
        data = open(os.path.join(DLC_TEX, g["png"]), "rb").read()
        h = dict(auth)
        h["x-upsert"] = "true"
        st, body = req("POST", f"/storage/v1/object/tex/jp/{g['md5']}.png",
                       data, h, ctype="image/png")
        if st not in (200, 201):
            print(f"[실패] {g['md5']}: HTTP {st} {body[:200]}")
            return False
        n += 1
    print(f"  DLC 텍스처 {n}장 업로드 완료")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="팀 암호 (rows 시딩)")
    ap.add_argument("--only", choices=["xmb", "script", "script360", "npc360", "image", "dlc", "dlcimg",
                                       "gamedata"])
    ap.add_argument("--dlc-thumbs", action="store_true", help="DLC 텍스처 업로드")
    ap.add_argument("--force-merge", action="store_true",
                    help="기존 행 덮어쓰기 (팀 수정 소실 주의)")
    ap.add_argument("--thumbs", action="store_true", help="썸네일 업로드")
    ap.add_argument("--service-key", help="storage용 service role key (저장 안 함)")
    args = ap.parse_args()
    ok = True
    if args.thumbs:
        key = args.service_key or os.environ.get("IMAS2_SB_SERVICE")
        if not key:
            sys.exit("--service-key 또는 IMAS2_SB_SERVICE 필요")
        ok = upload_thumbs(key) and ok
    if args.dlc_thumbs:
        key = args.service_key or os.environ.get("IMAS2_SB_SERVICE")
        if not key:
            sys.exit("--service-key 또는 IMAS2_SB_SERVICE 필요")
        ok = upload_dlc_thumbs(key) and ok
    if args.code:
        ok = seed_rows(args.code, args.only, args.force_merge) and ok
    if not (args.thumbs or args.dlc_thumbs or args.code):
        print("아무 작업도 지정 안 됨 — --code 또는 --thumbs")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
