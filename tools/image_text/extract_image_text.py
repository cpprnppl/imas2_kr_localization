#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IM@S2 UI/메뉴 이미지 텍스트 추출기

게임 리소스(mpc/s2d/nut/tsk/xmb) 안의 NTP3 NUT 텍스처를 PNG로 추출해
이미지 작업자(포토샵)에게 넘길 패키지를 만든다.

- 대상 인벤토리: 중국팀 패치 폴더에서 gscript/·initialFix.mpc·initialTemp.mpc를
  제외한 전 파일 = "이미지 텍스트가 있는(중국팀이 수정한) 파일" 목록.
- JP 원본(NPJB00337)과 CN 번역본(BLJS10083)을 같은 인덱스로 나란히 추출:
    out/jp/<상대경로>/<파일명>_<nnn>.png      ← 수정 대상
    out/cn_ref/<상대경로>/<파일명>_<nnn>.png  ← 번역 참고
    out/_review/<상대경로플랫>.png            ← JP/CN 나란히 검수 시트
    out/index.json, out/index.md
- 게임 폴더 원본은 절대 수정하지 않는다. out/_cache/ 에 사본을 뜨고,
  암호화 파일(.s2d/.nut/.tsk/.xmb 등)은 사본만 imas2dec로 복호화한다.
  (imas2dec는 'Finished' 후 프로세스가 안 죽으므로 타임아웃 kill,
   .dec 출력 위치 문제 때문에 CWD를 대상 폴더로 지정 — 워크로그 §8)

NUT 레이아웃(이 게임에서 실측 확인):
- 'NTP3' + ver(u16) + count(u16) + 8B, 이후 텍스처마다
  [80B 헤더][데이터 totalSize-80B] 가 연속(인터리브). ver=256(다중)·512(단독) 공통.
  ※ 폰트 NUT(im2_font_l)만 "헤더 연속 후 데이터 연속" 특수 배치지만, 그것도
    count=1 기준이 아니라서 이 도구 대상엔 없음. 마커(eXt/GIDX) 검증 실패 시 스킵.
- 80B 헤더: +0 totalSize, +4 palSize, +8 dataSize, +12 hdrSize(=80),
  +0x11 mipCount, +0x13 fmt, +0x14 w, +0x16 h, +0x30 'eXt\\0', +0x40 'GIDX'
- fmt: 0=DXT1, 1=DXT3, 2=DXT5, 14=ARGB8888(BE). DXT 블록 자체는 표준 LE.
"""
import os
import sys
import json
import time
import shutil
import struct
import hashlib
import argparse
import subprocess

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JP_ROOT = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource"
CN_ROOT = r"C:\Users\jackfilm\Desktop\偶像大师2汉化补丁\games\THE iDOLM@STER 2 [BLJS10083]\PS3_GAME\USRDIR\resource"
IMAS2DEC = r"C:\Users\jackfilm\Documents\GitHub\Imas2ToolS\misc\imas2dec\imas2dec.exe"
OUT_DEFAULT = r"C:\Users\jackfilm\Desktop\imas2_image_text"
PS3_ORIG = os.path.join(OUT_DEFAULT, "ps3_res_orig")   # ps3_res_apply.py 순정 사본 (2026-10-23)


def ps3_src(rel):
    """PS3 resource를 '원본'으로 읽을 때의 경로. ps3_res_apply가 순정 사본을 떠 둔 파일은 그 사본 —
    게임 폴더 파일은 한글 배포본일 수 있다(재패치 오염 방지, CLAUDE.md 규칙 1과 같은 이유)."""
    p = os.path.join(PS3_ORIG, rel)
    return p if os.path.exists(p) else os.path.join(JP_ROOT, rel)

EXCLUDE_DIRS = {"gscript"}
EXCLUDE_FILES = {"initialfix.mpc", "initialtemp.mpc"}
PLAIN_MAGICS = (b"pac\x00", b"NTP3", b"TSK ", b"XMB ")

# fmt 6 = ARGB1555 BE(360 fmt10과 같은 비트). 예전엔 RGB565로 잘못 풀어 포스터화·마젠타 번짐 —
# 2026-10-23 pc-360-dlc가 DLC 카탈로그로 확인, 본편 16장도 1555 쪽이 매끈함(총변화량)으로 재확인.
FMT_NAMES = {0: "DXT1", 1: "DXT3", 2: "DXT5", 6: "ARGB1555", 7: "ARGB4444",
             14: "ARGB32", 17: "ARGB32L"}


# ---------------------------------------------------------------- DXT decode

def _rgb565(c):
    r = ((c >> 11) & 31).astype(np.float32) * (255.0 / 31)
    g = ((c >> 5) & 63).astype(np.float32) * (255.0 / 63)
    b = (c & 31).astype(np.float32) * (255.0 / 31)
    return np.stack([r, g, b], axis=-1)


def _dxt_color(cblk: np.ndarray, dxt1: bool) -> np.ndarray:
    """cblk: (N,8) uint8 컬러 블록 → (N,4,4,4) RGBA float32."""
    n = len(cblk)
    c0 = cblk[:, 0].astype(np.uint16) | (cblk[:, 1].astype(np.uint16) << 8)
    c1 = cblk[:, 2].astype(np.uint16) | (cblk[:, 3].astype(np.uint16) << 8)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    pal = np.zeros((n, 4, 4), np.float32)
    pal[:, 0, :3], pal[:, 1, :3] = p0, p1
    pal[:, :, 3] = 255.0
    four2 = (2 * p0 + p1) / 3
    four3 = (p0 + 2 * p1) / 3
    if dxt1:
        three = c0 <= c1
        pal[:, 2, :3] = np.where(three[:, None], (p0 + p1) / 2, four2)
        pal[:, 3, :3] = np.where(three[:, None], 0.0, four3)
        pal[:, 3, 3] = np.where(three, 0.0, 255.0)
    else:
        pal[:, 2, :3], pal[:, 3, :3] = four2, four3
    bits = cblk[:, 4:8]  # (N,4) 행당 1바이트, 2bit×4픽셀 LSB부터
    k = np.arange(4)
    idx = ((bits[:, :, None] >> (2 * k)[None, None, :]) & 3).astype(np.intp)
    return pal[np.arange(n)[:, None, None], idx]  # (N,4행,4열,4rgba)


def _dxt3_alpha(ablk: np.ndarray) -> np.ndarray:
    """(N,8) → (N,4,4) alpha."""
    v = ablk.reshape(-1, 4, 2).astype(np.uint16)
    v = v[:, :, 0] | (v[:, :, 1] << 8)  # 행당 u16, 4bit×4픽셀
    k = np.arange(4)
    nib = (v[:, :, None] >> (4 * k)[None, None, :]) & 0xF
    return (nib * 17).astype(np.float32)


def _dxt5_alpha(ablk: np.ndarray) -> np.ndarray:
    """(N,8) → (N,4,4) alpha."""
    n = len(ablk)
    a0 = ablk[:, 0].astype(np.float32)
    a1 = ablk[:, 1].astype(np.float32)
    pal = np.zeros((n, 8), np.float32)
    pal[:, 0], pal[:, 1] = a0, a1
    big = a0 > a1
    for k in range(2, 8):
        big_v = ((8 - k) * a0 + (k - 1) * a1) / 7
        if k <= 5:
            small_v = ((6 - k) * a0 + (k - 1) * a1) / 5
        else:
            small_v = np.full(n, 0.0 if k == 6 else 255.0, np.float32)
        pal[:, k] = np.where(big, big_v, small_v)
    v = np.zeros(n, np.uint64)
    for i in range(6):
        v |= ablk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    p = np.arange(16, dtype=np.uint64)
    idx = ((v[:, None] >> (3 * p)[None, :]) & np.uint64(7)).astype(np.intp)
    return np.take_along_axis(pal, idx, axis=1).reshape(n, 4, 4)


def _blocks_to_image(rgba_blocks: np.ndarray, w: int, h: int) -> np.ndarray:
    bw, bh = w // 4, h // 4
    return (rgba_blocks.reshape(bh, bw, 4, 4, 4)
            .transpose(0, 2, 1, 3, 4).reshape(h, w, 4)
            .round().clip(0, 255).astype(np.uint8))


def decode_texture(fmt: int, raw: bytes, w: int, h: int) -> np.ndarray:
    """상위 밉 1장만 디코드 → (h,w,4) uint8 RGBA."""
    if fmt in (14, 17):  # 32bpp ARGB 빅엔디언 (17은 boot 등에서 쓰는 변형, 동일 배열)
        need = w * h * 4
        px = np.frombuffer(raw[:need], np.uint8).reshape(h, w, 4)
        return px[..., [1, 2, 3, 0]].copy()  # ARGB(BE) → RGBA
    if fmt in (6, 7):  # 16bpp 빅엔디언
        need = w * h * 2
        v = np.frombuffer(raw[:need], ">u2").reshape(h, w).astype(np.uint32)
        out = np.zeros((h, w, 4), np.uint8)
        if fmt == 6:  # ARGB1555 (최상위 비트 = 알파; 전부 0이면 불투명 취급)
            out[..., 0] = ((v >> 10) & 31) * 255 // 31
            out[..., 1] = ((v >> 5) & 31) * 255 // 31
            out[..., 2] = (v & 31) * 255 // 31
            a = np.where(v >> 15, 255, 0)
            out[..., 3] = a if a.any() else 255
        else:  # ARGB4444
            out[..., 0] = ((v >> 8) & 15) * 17
            out[..., 1] = ((v >> 4) & 15) * 17
            out[..., 2] = (v & 15) * 17
            out[..., 3] = ((v >> 12) & 15) * 17
        return out
    if w % 4 or h % 4:
        raise ValueError(f"DXT인데 4배수 아님: {w}x{h}")
    nb = (w // 4) * (h // 4)
    if fmt == 0:
        blk = np.frombuffer(raw[:nb * 8], np.uint8).reshape(nb, 8)
        return _blocks_to_image(_dxt_color(blk, dxt1=True), w, h)
    if fmt in (1, 2):
        blk = np.frombuffer(raw[:nb * 16], np.uint8).reshape(nb, 16)
        rgba = _dxt_color(blk[:, 8:], dxt1=False)
        alpha = _dxt3_alpha(blk[:, :8]) if fmt == 1 else _dxt5_alpha(blk[:, :8])
        rgba[:, :, :, 3] = alpha
        return _blocks_to_image(rgba, w, h)
    raise ValueError(f"미지원 fmt={fmt}")


# ---------------------------------------------------------------- NUT walker

def walk_nuts(data: bytes, log):
    """버퍼 전체에서 NTP3 NUT를 카빙해 텍스처 리스트를 돌려준다."""
    out = []
    pos = 0
    while True:
        i = data.find(b"NTP3", pos)
        if i < 0:
            break
        ver, cnt = struct.unpack_from(">HH", data, i + 4)
        packed = ver >= 0x0200  # 0x0200: 헤더 연속 후 데이터 연속 (폰트 NUT와 동일)
        cur = i + 16            # 0x0100: [헤더][데이터] 인터리브
        texs = []
        ok = cnt > 0
        for t in range(cnt):
            if cur + 80 > len(data):
                ok = False
                break
            total, _pal, dsz, hsz = struct.unpack_from(">IIIH", data, cur)
            mip = data[cur + 0x11]
            fmt = data[cur + 0x13]
            w, h = struct.unpack_from(">HH", data, cur + 0x14)
            if (data[cur + 0x30:cur + 0x34] != b"eXt\x00"
                    or data[cur + 0x40:cur + 0x44] != b"GIDX"
                    or hsz != 80 or total < 80 + dsz):
                ok = False
                break
            texs.append({"nut_off": i, "tex_off": cur, "data_off": cur + 80,
                         "fmt": fmt, "mip": mip, "w": w, "h": h,
                         "data_size": dsz, "total": total})
            cur += 80 if packed else total
        if ok and packed:  # 데이터 영역 오프셋 재계산
            base = cur
            for t in texs:
                t["data_off"] = base
                base += t["total"] - 80
            cur = base
        if ok and cur <= len(data):
            out.extend(texs)
            pos = cur
        else:
            log(f"    [주의] NTP3 @0x{i:X}: 헤더 검증 실패(tex{len(texs)}) → 시그니처 스킵")
            pos = i + 4
    return out


# ---------------------------------------------------------------- staging

def stage_file(src: str, cache_path: str, log) -> str:
    """원본을 캐시에 복사하고, 암호화돼 있으면 사본만 복호화한다."""
    if os.path.exists(cache_path):
        return cache_path
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    shutil.copy2(src, cache_path)
    with open(cache_path, "rb") as f:
        magic = f.read(4)
    if magic in PLAIN_MAGICS:
        return cache_path
    # 암호화 → imas2dec (CWD=파일 폴더, Finished 후 안 죽으니 kill)
    log(f"    복호화: {os.path.basename(cache_path)}")
    p = subprocess.Popen([IMAS2DEC, cache_path],
                         cwd=os.path.dirname(cache_path),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dec = cache_path + ".dec"
    for _ in range(600):  # 최대 60초
        if os.path.exists(dec) and os.path.getsize(dec) > 0:
            time.sleep(0.5)  # 쓰기 완료 여유
            break
        time.sleep(0.1)
    try:
        p.kill()
    except OSError:
        pass
    time.sleep(0.2)
    if not os.path.exists(dec):
        raise RuntimeError(f"복호화 실패: {src}")
    os.replace(dec, cache_path)
    return cache_path


# ---------------------------------------------------------------- per file

def inventory():
    """CN 패치 폴더 기준 대상 파일 상대경로 목록."""
    rels = []
    for dirpath, dirnames, filenames in os.walk(CN_ROOT):
        dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDE_DIRS]
        for fn in sorted(filenames):
            if fn.lower() in EXCLUDE_FILES:
                continue
            rels.append(os.path.relpath(os.path.join(dirpath, fn), CN_ROOT))
    return sorted(rels)


def extract_side(rel: str, src_root: str, cache_root: str, png_root: str, log):
    src = ps3_src(rel) if src_root == JP_ROOT else os.path.join(src_root, rel)
    if not os.path.exists(src):
        return {"error": "원본 없음", "textures": []}
    cache = stage_file(src, os.path.join(cache_root, rel), log)
    data = open(cache, "rb").read()
    texs = walk_nuts(data, log)
    stem = os.path.splitext(os.path.basename(rel))[0]
    outdir = os.path.join(png_root, os.path.dirname(rel))
    entries = []
    for n, t in enumerate(texs):
        name = f"{stem}_{n:03d}.png"
        raw = data[t["data_off"]:t["data_off"] + t["data_size"]]
        entry = {"n": n, "png": name, "fmt": FMT_NAMES.get(t["fmt"], f"fmt{t['fmt']}"),
                 "w": t["w"], "h": t["h"], "mip": t["mip"],
                 "nut_off": t["nut_off"], "tex_off": t["tex_off"],
                 "data_off": t["data_off"], "data_size": t["data_size"],
                 "md5": hashlib.md5(raw).hexdigest()}
        try:
            img = decode_texture(t["fmt"], raw, t["w"], t["h"])
            os.makedirs(outdir, exist_ok=True)
            Image.fromarray(img, "RGBA").save(os.path.join(outdir, name))
        except Exception as e:  # noqa: BLE001 — 한 장 실패해도 계속
            entry["error"] = str(e)
            log(f"    [오류] {rel} tex{n}: {e}")
        entries.append(entry)
    return {"magic": data[:4].decode("ascii", "replace"), "size": len(data),
            "textures": entries}


# ---------------------------------------------------------------- review sheet

def review_sheet(rel: str, out_root: str, modified=frozenset()):
    """JP/CN 텍스처를 짝지어 한 장의 검수 시트로 합친다 (체커보드 배경)."""
    stem = os.path.splitext(os.path.basename(rel))[0]
    reldir = os.path.dirname(rel)
    jp_dir = os.path.join(out_root, "jp", reldir)
    cn_dir = os.path.join(out_root, "cn_ref", reldir)
    pairs = []
    n = 0
    while True:
        jp = os.path.join(jp_dir, f"{stem}_{n:03d}.png")
        cn = os.path.join(cn_dir, f"{stem}_{n:03d}.png")
        je, ce = os.path.exists(jp), os.path.exists(cn)
        if not je and not ce:
            break
        pairs.append((n, jp if je else None, cn if ce else None))
        n += 1
    if not pairs:
        return None

    def checker(img: Image.Image) -> Image.Image:
        px = np.zeros((img.height, img.width, 3), np.uint8)
        yy, xx = np.mgrid[0:img.height, 0:img.width]
        px[((yy // 8 + xx // 8) % 2) == 0] = 90
        px[((yy // 8 + xx // 8) % 2) == 1] = 140
        bg = Image.fromarray(px)
        bg.paste(img, (0, 0), img)
        return bg

    from PIL import ImageDraw
    cols = []
    max_w = 0
    total_h = 0
    rows = []
    for n, jp, cn in pairs:
        ims = []
        for p in (jp, cn):
            if p:
                im = checker(Image.open(p).convert("RGBA"))
            else:
                im = Image.new("RGB", (64, 64), (200, 0, 0))
            if im.width > 640:
                im = im.resize((640, max(1, im.height * 640 // im.width)))
            ims.append(im)
        h = max(i.height for i in ims) + 18
        w = sum(i.width for i in ims) + 24
        row = Image.new("RGB", (w, h), (30, 30, 30))
        d = ImageDraw.Draw(row)
        tag = " [CN수정]" if n in modified else ""
        d.text((2, 2), f"#{n:03d} JP | CN{tag}",
               fill=(255, 80, 80) if n in modified else (255, 255, 0))
        x = 0
        for im in ims:
            row.paste(im, (x, 18))
            x += im.width + 24
        rows.append(row)
        max_w = max(max_w, row.width)
        total_h += row.height + 4
    sheet = Image.new("RGB", (max_w, total_h), (30, 30, 30))
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height + 4
    os.makedirs(os.path.join(out_root, "_review"), exist_ok=True)
    out = os.path.join(out_root, "_review", rel.replace("\\", "__").replace("/", "__") + ".png")
    sheet.save(out)
    return out


# ---------------------------------------------------------------- index.md

def write_index(out_root: str, results: dict):
    # --only 재실행 시 기존 index와 병합
    prev_path = os.path.join(out_root, "index.json")
    if os.path.exists(prev_path):
        prev = json.load(open(prev_path, encoding="utf-8"))
        prev.update(results)
        results = prev
    notes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "review_notes.json")
    notes = {}
    if os.path.exists(notes_path):
        notes = json.load(open(notes_path, encoding="utf-8"))

    with open(os.path.join(out_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)

    n_mod = sum(len(r.get("cn_modified", [])) for r in results.values())
    uniq = len({
        r["jp"]["textures"][n]["md5"]
        for r in results.values() for n in r.get("cn_modified", [])
        if n < len(r["jp"]["textures"])})
    n_tex = sum(len(r.get("jp", {}).get("textures", [])) for r in results.values())
    lines = [
        "# IM@S2 UI 이미지 텍스트 추출 인덱스",
        "",
        f"- 전체 {len(results)}파일 / JP 텍스처 {n_tex}장 중 **CN 수정 {n_mod}장** "
        f"(내용 중복 제거 시 **유니크 {uniq}장**) — 같은 라벨 세트가 여러 pac에 중복 수록됨"
        "(도도부현 라벨: produce_etc·morning·night·scheduling·exep_commu / "
        "お守りINFO류: les_com·alf_common·produce_common·produce_etc 등). "
        "**한 번 작업한 PNG를 같은 md5의 다른 위치에 재사용**하면 된다 (index.json의 md5 참조).",
        f"- 생성: {time.strftime('%Y-%m-%d %H:%M')}  /  도구: `tools/image_text/extract_image_text.py` (레포 imas2_kr_localization)",
        "- `jp/` = 일본어 원본 텍스처(**작업 대상**), `cn_ref/` = 중국팀 번역본(같은 번호 = 같은 위치, 참고용)",
        "- `_review/` = JP|CN 나란히 검수 시트, `_cache/` = 복호화 사본(수정 금지·재생성 가능)",
        "- 좌표(`nut_off`/`tex_off`/`data_off`)는 **복호화된** 파일 기준 오프셋 (index.json 참조)",
        "",
        "## 재주입(한글 PNG → 게임) 시 주의점 — 다음 단계",
        "",
        "1. PNG를 원본과 **같은 포맷**(DXT1/DXT3/DXT5/ARGB32)으로 재인코딩하고 "
        "**데이터 크기를 원본과 동일하게** 유지해야 pac 오프셋이 안 깨진다 (크기 변경 금지).",
        "2. DXT 블록은 표준 리틀엔디언, ARGB32는 **빅엔디언 ARGB** 바이트 순서.",
        "3. 텍스처 치수를 바꾸지 말 것 — NFH/배치 좌표가 외부(별도 레이아웃 데이터)에 있다.",
        "4. 암호화 파일(.s2d/.nut/.tsk/.xmb)은 **복호화 상태로 재패킹**해 두면 게임이 그대로 읽는다 "
        "(중국팀 패치가 전부 복호화본 배포 — JP .mpc도 이미 복호화본으로 교체된 상태와 동일 원리). "
        "단, 평문 교체 가부는 인게임 1회 검증 후 전체 적용할 것.",
        "5. 원본 게임 폴더를 직접 덮지 말고 excel2scb→deploy 파이프라인처럼 검증 게이트를 거칠 것.",
        "",
        "`CN 수정` = JP와 CN의 텍스처 payload 바이트가 다른 장수 = 중국팀이 실제로 "
        "고친(=텍스트가 들어 있는) 텍스처. **작업 범위 산정은 이 열 기준**으로 하되, "
        "중국팀이 안 고친 일본어(예: 로마자 연출 등)가 있을 수 있어 눈검수 메모로 보완.",
        "",
        "## 파일별 추출 결과",
        "",
        "| 파일 | 텍스처 수 | CN 수정 | 수정 텍스처 번호 | 치수/포맷 요약 | 눈검수 메모 |",
        "|---|---|---|---|---|---|",
    ]
    for rel in sorted(results):
        r = results[rel]
        jp = r.get("jp", {})
        texs = jp.get("textures", [])
        n_err = sum(1 for t in texs if "error" in t)
        from collections import Counter
        c = Counter(f"{t['w']}x{t['h']} {t['fmt']}" for t in texs)
        summary = ", ".join(f"{k}×{v}" for k, v in c.most_common(4))
        if len(c) > 4:
            summary += f" 외 {len(c)-4}종"
        if n_err:
            summary += f" (디코드 실패 {n_err})"
        cn_n = len(r.get("cn", {}).get("textures", []))
        cnt = f"{len(texs)}"
        if cn_n != len(texs):
            cnt += f" (CN {cn_n} — 불일치!)"
        mod = r.get("cn_modified", [])
        mod_s = ",".join(str(m) for m in mod[:20])
        if len(mod) > 20:
            mod_s += f",… (+{len(mod)-20})"
        note = notes.get(rel.replace("\\", "/"), "")
        lines.append(f"| `{rel}` | {cnt} | {len(mod)} | {mod_s} | {summary} | {note} |")
    lines.append("")
    with open(os.path.join(out_root, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--only", help="상대경로 부분 일치 필터 (예: title)")
    ap.add_argument("--no-sheets", action="store_true", help="검수 시트 생략")
    ap.add_argument("--reindex", action="store_true",
                    help="추출 없이 기존 index.json + review_notes.json으로 index.md 재생성")
    args = ap.parse_args()
    log = print

    if args.reindex:
        write_index(args.out, {})
        log(f"index 재생성: {os.path.join(args.out, 'index.md')}")
        return

    rels = inventory()
    if args.only:
        rels = [r for r in rels if args.only.lower() in r.lower()]
    log(f"대상 {len(rels)}개 파일 (CN 인벤토리 기준)")

    results = {}
    for rel in rels:
        log(f"▶ {rel}")
        r = {}
        r["jp"] = extract_side(rel, JP_ROOT, os.path.join(args.out, "_cache", "jp"),
                               os.path.join(args.out, "jp"), log)
        r["cn"] = extract_side(rel, CN_ROOT, os.path.join(args.out, "_cache", "cn"),
                               os.path.join(args.out, "cn_ref"), log)
        nj, nc = len(r["jp"]["textures"]), len(r["cn"]["textures"])
        flag = "" if nj == nc else "  ← JP/CN 개수 불일치!"
        # payload 바이트가 다른 텍스처 = 중국팀이 수정한(=텍스트가 있는) 텍스처
        r["cn_modified"] = [
            tj["n"] for tj, tc in zip(r["jp"]["textures"], r["cn"]["textures"])
            if tj.get("md5") != tc.get("md5")]
        log(f"    JP {nj}장 / CN {nc}장, CN 수정 {len(r['cn_modified'])}장{flag}")
        if not args.no_sheets:
            review_sheet(rel, args.out, set(r["cn_modified"]))
        results[rel] = r

    write_index(args.out, results)
    total = sum(len(r["jp"]["textures"]) for r in results.values())
    log(f"\n완료: JP 텍스처 {total}장 → {args.out}")
    log(f"index: {os.path.join(args.out, 'index.md')}")


if __name__ == "__main__":
    main()
