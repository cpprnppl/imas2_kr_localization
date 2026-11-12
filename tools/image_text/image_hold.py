"""그림 보류 목록(image_hold.json) — 작업본이 있어도 주입하지 않고 원본으로 두는 텍스처.
KOR 14판 기준(2026-11-12): 블록 보존 뒤에도 패치 diff 50%를 넘고 예외(넓이 16,384px 이하 글자 라벨)가 아닌 텍스처는
원본으로 둔다. 모든 그림 주입 경로(inject_image_text·ps3_res_apply.extra_images·dlc_inject·pcport_apply)가 이 목록을 본다.
키: plat('ps3'|'pc'), pkg(DLC만: PS3 'cpNN', 360 패키지 이름 앞 6자 이상), rel(resource 기준, '/' 구분), n(텍스처 번호)."""
import os
import json

_P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_hold.json")
_ITEMS = None


def _items():
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = json.load(open(_P, encoding="utf-8"))["hold"] if os.path.exists(_P) else []
    return _ITEMS


def held(plat, rel, n, pkg=None):
    rel = rel.replace("\\", "/")
    for it in _items():
        if it["plat"] != plat or it["rel"] != rel or it["n"] != n:
            continue
        if (it.get("pkg") or None) is None and pkg is None:
            return True
        if it.get("pkg") and pkg and (pkg.startswith(it["pkg"]) or it["pkg"].startswith(pkg)):
            return True
    return False
