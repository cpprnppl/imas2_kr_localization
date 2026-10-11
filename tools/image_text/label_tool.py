#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IM@S2 UI 라벨 한글화 툴 (로컬 웹 UI)

CN 수정 텍스처(=텍스트가 있는 텍스처)를 md5 중복 제거한 그룹(333개) 단위로,
폰트·크기·스타일을 지정해 한글 라벨을 렌더하고 JP/CN과 나란히 미리본다.
미리보기와 내보내기가 같은 PIL 렌더러를 쓰므로 보이는 그대로 PNG가 나온다.

  python label_tool.py            # http://127.0.0.1:8765 에서 UI
  python label_tool.py --export   # UI 없이 스펙 전체를 kr/로 렌더

- 스펙 저장: tools/image_text/label_specs.json (레포 커밋 대상)
- 내보내기: <out>/kr/<상대경로>/<파일명>_<nnn>.png — 같은 md5의 모든 위치에 복제
  → 이후 `python inject_image_text.py` 로 주입(검증 게이트 포함)
- 스타일은 프리셋으로 공유: 프리셋 수정 시 그 프리셋을 쓰는 모든 텍스처에 반영.
  도도부현처럼 좁은 칸은 '자동 맞춤'이 글자 크기를 칸에 맞게 줄인다.
"""
import os
import io
import sys
import json
import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_image_text import OUT_DEFAULT  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "label_specs.json")
FONT_DIRS = [r"C:\Windows\Fonts", r"C:\Users\jackfilm\Desktop\xenia"]

DEFAULT_PRESET = {
    "font": "malgunbd.ttf", "size": 24, "fit": True, "margin": 2,
    "fill": "#ffffff", "stroke_w": 2, "stroke": "#1a1a1a",
    "glow_r": 0, "glow": "#000000", "glow_a": 160,
    "spacing": 0, "dy": 0, "line_h": 1.1, "align": "center",
}


# ---------------------------------------------------------------- state

def load_specs():
    if os.path.exists(SPEC_PATH):
        return json.load(open(SPEC_PATH, encoding="utf-8"))
    return {"presets": {"기본": dict(DEFAULT_PRESET)}, "items": {}}


def save_specs(s):
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def build_groups():
    """index.json → md5 그룹 (CN 수정 텍스처만)."""
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
                "locs": []})
            g["locs"].append({"rel": rel, "n": n, "png": t["png"]})
    for g in groups.values():
        g["locs"].sort(key=lambda L: (L["rel"], L["n"]))
    return dict(sorted(groups.items(),
                       key=lambda kv: (kv[1]["locs"][0]["rel"], kv[1]["locs"][0]["n"])))


GROUPS = build_groups()
SPECS = load_specs()
LOCK = threading.Lock()
FONT_CACHE = {}


def list_fonts():
    out = []
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".ttf", ".otf", ".ttc")):
                out.append(fn)
    return out


def font_path(name):
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


def get_font(name, size):
    key = (name, size)
    if key not in FONT_CACHE:
        FONT_CACHE[key] = ImageFont.truetype(font_path(name), size)
    return FONT_CACHE[key]


# ---------------------------------------------------------------- renderer

def style_of(item):
    st = dict(DEFAULT_PRESET)
    st.update(SPECS["presets"].get(item.get("preset", ""), {}))
    st.update(item.get("over", {}))
    return st


def _line_metrics(font, line, spacing):
    if not line:
        return 0
    w = sum(font.getlength(c) for c in line) + spacing * (len(line) - 1)
    return int(w)


def render_label(w, h, text, st):
    """투명 캔버스에 스타일 적용 텍스트 렌더. 미리보기=최종."""
    lines = text.split("\n")
    size = int(st["size"])
    margin = int(st.get("margin", 2))
    box_w, box_h = w - margin * 2, h - margin * 2
    while size > 7:
        font = get_font(st["font"], size)
        asc, desc = font.getmetrics()
        lh = int((asc + desc) * float(st.get("line_h", 1.1)))
        tw = max((_line_metrics(font, ln, st.get("spacing", 0)) for ln in lines),
                 default=0) + 2 * int(st.get("stroke_w", 0))
        th = lh * len(lines)
        if not st.get("fit", True) or (tw <= box_w and th <= box_h):
            break
        size -= 1
    font = get_font(st["font"], size)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * float(st.get("line_h", 1.1)))
    th = lh * len(lines)
    y0 = (h - th) // 2 + int(st.get("dy", 0))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    sw = int(st.get("stroke_w", 0))
    sp = int(st.get("spacing", 0))

    def draw_pass(target, fill, stroke_fill):
        d = ImageDraw.Draw(target)
        for i, ln in enumerate(lines):
            lw = _line_metrics(font, ln, sp)
            if st.get("align", "center") == "left":
                x = margin
            elif st["align"] == "right":
                x = w - margin - lw
            else:
                x = (w - lw) // 2
            y = y0 + i * lh
            if sp:
                cx = x
                for c in ln:
                    d.text((cx, y), c, font=font, fill=fill,
                           stroke_width=sw, stroke_fill=stroke_fill)
                    cx += font.getlength(c) + sp
            else:
                d.text((x, y), ln, font=font, fill=fill,
                       stroke_width=sw, stroke_fill=stroke_fill)

    if int(st.get("glow_r", 0)) > 0:
        mask = Image.new("L", (w, h), 0)
        draw_pass(mask, 255, 255)
        blur = mask.filter(ImageFilter.GaussianBlur(int(st["glow_r"])))
        ga = int(st.get("glow_a", 160))
        glow = Image.new("RGBA", (w, h), st.get("glow", "#000000"))
        glow.putalpha(blur.point(lambda v: v * ga // 255))
        img = Image.alpha_composite(img, glow)
    draw_pass(img, st.get("fill", "#ffffff"), st.get("stroke", "#1a1a1a"))
    return img


def render_group(md5):
    g = GROUPS[md5]
    item = SPECS["items"].get(md5, {})
    text = item.get("text", "")
    return render_label(g["w"], g["h"], text, style_of(item))


def export_all(log=print):
    n_png = n_grp = 0
    skipped = []
    for md5, g in GROUPS.items():
        item = SPECS["items"].get(md5)
        if not item or item.get("mode", "text") != "text" or not item.get("text"):
            if item and item.get("mode") == "manual":
                skipped.append(md5)
            continue
        img = render_group(md5)
        n_grp += 1
        for L in g["locs"]:
            dst = os.path.join(OUT_DEFAULT, "kr", os.path.dirname(L["rel"]), L["png"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            img.save(dst)
            n_png += 1
    log(f"내보내기: 그룹 {n_grp}개 → PNG {n_png}장 ({os.path.join(OUT_DEFAULT, 'kr')})")
    if skipped:
        log(f"수동(포토샵) 지정 {len(skipped)}그룹은 제외 — 직접 kr/에 넣을 것")
    log("다음: python inject_image_text.py  (검증 게이트 후 patched/ 생성)")
    return {"groups": n_grp, "pngs": n_png, "manual": len(skipped)}


# ---------------------------------------------------------------- HTTP

def group_state():
    out = []
    for md5, g in GROUPS.items():
        item = SPECS["items"].get(md5, {})
        out.append({"md5": md5, "w": g["w"], "h": g["h"], "fmt": g["fmt"],
                    "count": len(g["locs"]), "locs": g["locs"],
                    "item": item})
    return {"groups": out, "presets": SPECS["presets"], "fonts": list_fonts(),
            "default": DEFAULT_PRESET}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path == "/":
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                with LOCK:
                    self._json(group_state())
            elif u.path.startswith("/img/"):
                _, _, side, md5 = u.path.split("/")
                g = GROUPS[md5]
                L = g["locs"][0]
                base = "jp" if side == "jp" else "cn_ref"
                p = os.path.join(OUT_DEFAULT, base, os.path.dirname(L["rel"]), L["png"])
                self._send(200, open(p, "rb").read(), "image/png")
            elif u.path.startswith("/render/"):
                md5 = u.path.rsplit("/", 1)[1]
                with LOCK:
                    img = render_group(md5)
                b = io.BytesIO()
                img.save(b, "PNG")
                self._send(200, b.getvalue(), "image/png")
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        body = json.loads(self.rfile.read(
            int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        try:
            with LOCK:
                if u.path == "/api/item":
                    SPECS["items"][body["md5"]] = body["item"]
                    save_specs(SPECS)
                    self._json({"ok": True})
                elif u.path == "/api/preset":
                    if body.get("delete"):
                        SPECS["presets"].pop(body["name"], None)
                    else:
                        SPECS["presets"][body["name"]] = body["style"]
                    save_specs(SPECS)
                    self._json({"ok": True})
                elif u.path == "/api/export":
                    msgs = []
                    r = export_all(log=msgs.append)
                    r["log"] = msgs
                    self._json(r)
                else:
                    self._send(404, b"not found", "text/plain")
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)


PAGE = r"""<!doctype html><meta charset="utf-8">
<title>iM@S2 라벨 툴</title>
<style>
:root{--bg:#f4f4f2;--sf:#fff;--fg:#1c1d1f;--mut:#6e7075;--ln:#d8d8d4;--ac:#31557d}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:13px/1.5 "Malgun Gothic",system-ui,sans-serif;display:flex;height:100vh}
#list{width:300px;border-right:1px solid var(--ln);overflow-y:auto;background:var(--sf)}
#list .hd{position:sticky;top:0;background:var(--sf);border-bottom:1px solid var(--ln);
 padding:8px;display:flex;gap:6px;align-items:center}
#list .hd select{font:inherit}
.row{display:flex;gap:8px;padding:6px 8px;border-bottom:1px solid var(--ln);
 cursor:pointer;align-items:center}
.row:hover{background:#eef1f4}
.row.sel{background:var(--ac);color:#fff}
.row img{width:72px;height:36px;object-fit:contain;background:
 repeating-conic-gradient(#ccc 0 25%,#eee 0 50%) 0 0/12px 12px;flex:none}
.row .meta{min-width:0;font-size:11px}
.row .meta b{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.tag{font-size:10px;border:1px solid currentColor;padding:0 4px;margin-right:3px}
#mid{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.pv{display:flex;gap:6px;align-items:center}
.pv .lab{width:24px;color:var(--mut);font-size:11px}
.pv .box{background:repeating-conic-gradient(#b9b9b9 0 25%,#dcdcdc 0 50%) 0 0/16px 16px;
 border:1px solid var(--ln);line-height:0}
.pv img{image-rendering:pixelated}
#side{width:320px;border-left:1px solid var(--ln);background:var(--sf);
 overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px}
#side label{display:flex;justify-content:space-between;align-items:center;gap:8px;
 font-size:12px;color:var(--mut)}
#side input,#side select,#side textarea{font:inherit;color:var(--fg);
 border:1px solid var(--ln);background:var(--sf);padding:3px 6px;width:170px}
#side textarea{width:100%;min-height:60px;resize:vertical}
#side input[type=checkbox]{width:auto}
#side input[type=color]{padding:0;width:40px;height:24px}
.btn{font:inherit;border:1px solid var(--ln);background:var(--sf);padding:5px 10px;
 cursor:pointer}
.btn.pri{background:var(--ac);color:#fff;border-color:var(--ac)}
.grp{border-top:1px solid var(--ln);padding-top:8px;display:flex;flex-direction:column;gap:6px}
.grp h3{margin:0;font-size:12px;color:var(--mut);font-weight:500}
#locs{font-size:11px;color:var(--mut);white-space:pre-wrap}
#status{font-size:12px;color:var(--mut);white-space:pre-wrap}
.num{width:60px!important}
</style>
<div id="list"><div class="hd">
 <select id="flt"><option value="all">전체</option><option value="todo">미지정</option>
 <option value="done">지정됨</option><option value="manual">수동</option></select>
 <input id="q" type="search" placeholder="경로 검색" style="flex:1;font:inherit;padding:3px 6px;border:1px solid var(--ln)">
</div><div id="rows"></div></div>
<div id="mid">
 <div class="pv"><span class="lab">JP</span><span class="box"><img id="pjp"></span></div>
 <div class="pv"><span class="lab">CN</span><span class="box"><img id="pcn"></span></div>
 <div class="pv"><span class="lab">KR</span><span class="box"><img id="pkr"></span></div>
 <label style="font-size:12px;color:var(--mut)">확대
  <input id="zoom" type="range" min="1" max="6" value="2" style="vertical-align:middle">
 </label>
 <div id="locs"></div>
</div>
<div id="side">
 <textarea id="text" placeholder="한글 텍스트 (여러 줄 가능)"></textarea>
 <label>모드 <select id="mode"><option value="text">텍스트 렌더</option>
  <option value="manual">수동(포토샵)</option><option value="skip">제외</option></select></label>
 <label>프리셋 <select id="preset"></select></label>
 <div class="grp"><h3>스타일 (이 텍스처만 덮어씀 — 비우면 프리셋 값)</h3>
 <label>폰트 <select id="font"></select></label>
 <label>크기 <input id="size" type="number" class="num" min="8" max="96"></label>
 <label>자동 맞춤 <input id="fit" type="checkbox"></label>
 <label>여백 <input id="margin" type="number" class="num" min="0" max="40"></label>
 <label>채움색 <input id="fill" type="color"></label>
 <label>외곽선 폭 <input id="stroke_w" type="number" class="num" min="0" max="10"></label>
 <label>외곽선색 <input id="stroke" type="color"></label>
 <label>글로우 반경 <input id="glow_r" type="number" class="num" min="0" max="20"></label>
 <label>글로우색 <input id="glow" type="color"></label>
 <label>글로우 농도 <input id="glow_a" type="number" class="num" min="0" max="255"></label>
 <label>자간 <input id="spacing" type="number" class="num" min="-5" max="20"></label>
 <label>세로 오프셋 <input id="dy" type="number" class="num" min="-40" max="40"></label>
 <label>줄간격 <input id="line_h" type="number" class="num" min="0.8" max="2" step="0.05"></label>
 <label>정렬 <select id="align"><option>center</option><option>left</option><option>right</option></select></label>
 </div>
 <div class="grp">
  <button class="btn" id="savePreset">현재 스타일을 프리셋으로 저장…</button>
  <button class="btn pri" id="export">전체 내보내기 → kr/</button>
  <div id="status"></div>
 </div>
</div>
<script>
let S=null, cur=null, zoom=2;
const $=s=>document.querySelector(s);
const FIELDS=["font","size","fit","margin","fill","stroke_w","stroke","glow_r","glow","glow_a","spacing","dy","line_h","align"];
async function load(){S=await (await fetch("/api/state")).json();
 const fs=$("#font");fs.innerHTML=S.fonts.map(f=>`<option>${f}</option>`).join("");
 renderPresetSel();renderList();
 if(!cur&&S.groups.length)select(S.groups[0].md5);}
function renderPresetSel(){const p=$("#preset");
 p.innerHTML=Object.keys(S.presets).map(n=>`<option>${n}</option>`).join("");}
function itemOf(md5){const g=S.groups.find(g=>g.md5===md5);return g?g.item||{}:{}}
function stateOf(g){const it=g.item||{};
 if(!it.mode&&!it.text)return"todo";
 if(it.mode==="manual")return"manual";
 if(it.mode==="skip")return"skip";
 return it.text?"done":"todo"}
function renderList(){const f=$("#flt").value,q=$("#q").value.toLowerCase();
 const host=$("#rows");host.innerHTML="";
 for(const g of S.groups){const st=stateOf(g);
  if(f!=="all"&&st!==f)continue;
  if(q&&!g.locs.some(L=>L.rel.toLowerCase().includes(q)))continue;
  const d=document.createElement("div");d.className="row"+(g.md5===cur?" sel":"");
  const tags=st==="done"?'<span class="tag">텍스트</span>':st==="manual"?'<span class="tag">수동</span>':st==="skip"?'<span class="tag">제외</span>':"";
  d.innerHTML=`<img loading="lazy" src="/img/jp/${g.md5}">
   <div class="meta"><b>${g.locs[0].rel} #${String(g.locs[0].n).padStart(3,"0")}</b>
   ${tags}${g.w}×${g.h} ${g.fmt}${g.count>1?` ×${g.count}곳`:""}</div>`;
  d.onclick=()=>select(g.md5);
  host.appendChild(d);}}
function select(md5){cur=md5;renderList();
 const g=S.groups.find(g=>g.md5===md5),it=g.item||{};
 const sty=Object.assign({},S.default,S.presets[it.preset||"기본"]||{},it.over||{});
 $("#text").value=it.text||"";
 $("#mode").value=it.mode||"text";
 $("#preset").value=it.preset||Object.keys(S.presets)[0];
 for(const k of FIELDS){const el=$("#"+k);
  if(el.type==="checkbox")el.checked=!!sty[k];else el.value=sty[k];}
 $("#locs").textContent="사용 위치:\n"+g.locs.map(L=>`${L.rel} #${String(L.n).padStart(3,"0")}`).join("\n");
 refresh(g);}
function refresh(g){const z=zoom;
 for(const[id,src]of[["pjp","/img/jp/"],["pcn","/img/cn/"],["pkr","/render/"]]){
  const im=$("#"+id);im.src=src+g.md5+"?t="+Date.now();
  im.width=g.w*z;im.height=g.h*z;}}
let t;
function push(){clearTimeout(t);t=setTimeout(async()=>{
 const g=S.groups.find(g=>g.md5===cur);if(!g)return;
 const base=Object.assign({},S.default,S.presets[$("#preset").value]||{});
 const over={};
 for(const k of FIELDS){const el=$("#"+k);
  let v=el.type==="checkbox"?el.checked:(el.type==="number"?parseFloat(el.value):el.value);
  if(v!==base[k]&&!(typeof base[k]==="number"&&Math.abs(v-base[k])<1e-9))over[k]=v;}
 const item={text:$("#text").value.replace(/\r\n/g,"\n"),mode:$("#mode").value,
  preset:$("#preset").value,over};
 g.item=item;
 await fetch("/api/item",{method:"POST",body:JSON.stringify({md5:cur,item})});
 refresh(g);renderList();},350);}
for(const k of FIELDS)$("#"+k).addEventListener("input",push);
$("#text").addEventListener("input",push);
$("#mode").addEventListener("input",push);
$("#preset").addEventListener("input",()=>{select(cur);push();});
$("#flt").onchange=renderList;$("#q").oninput=renderList;
$("#zoom").oninput=e=>{zoom=+e.target.value;
 const g=S.groups.find(g=>g.md5===cur);if(g)refresh(g);};
$("#savePreset").onclick=()=>{
 if($("#pnBox"))return;
 const style={};for(const k of FIELDS){const el=$("#"+k);
  style[k]=el.type==="checkbox"?el.checked:(el.type==="number"?parseFloat(el.value):el.value);}
 const pn=document.createElement("div");pn.id="pnBox";
 pn.innerHTML='<input id="pnName" placeholder="프리셋 이름" style="width:150px;font:inherit;padding:3px 6px;border:1px solid var(--ln)"> <button class="btn" id="pnOk">저장</button>';
 $("#savePreset").after(pn);
 $("#pnName").value=$("#preset").value;
 $("#pnOk").onclick=async()=>{const n=$("#pnName").value.trim();if(!n)return;
  await fetch("/api/preset",{method:"POST",body:JSON.stringify({name:n,style})});
  S.presets[n]=style;renderPresetSel();$("#preset").value=n;pn.remove();push();};
};
$("#export").onclick=async()=>{
 $("#status").textContent="내보내는 중…";
 const r=await(await fetch("/api/export",{method:"POST",body:"{}"})).json();
 $("#status").textContent=(r.log||[]).join("\n");};
load();
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true", help="UI 없이 전체 렌더")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if args.export:
        export_all()
        return
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), H)
    print(f"라벨 툴: http://127.0.0.1:{args.port}  (그룹 {len(GROUPS)}개, Ctrl+C로 종료)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
