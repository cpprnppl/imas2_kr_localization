#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
RPCS3(PS3판) 인게임 확인용 간단 드라이버 (2026-10-23)

  python rpcs3_drive.py start [--owner ui]     # gpu_run.lock(원자적 생성) 잡고 rpcs3 --no-gui EBOOT.BIN 실행
  python rpcs3_drive.py keys "RET, wait 3, C, wait 2, DOWN, C"   # 키 입력(창 앞으로 가져온 뒤 SendInput)
  python rpcs3_drive.py shot out.png [--scale 0.5]               # RPCS3 게임 창 캡처
  python rpcs3_drive.py stop                    # rpcs3 종료 + 잠금 해제(내 잠금일 때만)

패드 매핑(config/input_configs/global/Default.yml, 키보드): Start=RET(Enter) Select=SPACE ○=C ×=X △=V □=Z
L1=Q R1=E 방향=UP/DOWN/LEFT/RIGHT. 일본판은 ○ 결정·× 취소.
GPU 잠금 규칙은 imas2pc run_ctrl.ps1과 같다(Desktop\imas2pc\gpu_run.lock, 한 번에 게임 하나).
"""
import os
import sys
import time
import ctypes
import subprocess
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RPCS3 = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc"
EBOOT = os.path.join(RPCS3, r"dev_hdd0\game\NPJB00337\USRDIR\EBOOT.BIN")
LOCK = r"C:\Users\jackfilm\Desktop\imas2pc\gpu_run.lock"
U = ctypes.windll.user32
VK = {"RET": 0x0D, "SPACE": 0x20, "BS": 0x08, "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27}
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK[ch] = ord(ch)


def game_window():
    """RPCS3 게임 창(제목에 FPS 또는 게임명) 핸들."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        if U.IsWindowVisible(h):
            n = U.GetWindowTextLengthW(h)
            b = ctypes.create_unicode_buffer(n + 1)
            U.GetWindowTextW(h, b, n + 1)
            t = b.value
            if "FPS" in t or "iDOLM@STER" in t or "アイドルマスター" in t:
                found.append((h, t))
        return True
    U.EnumWindows(cb, 0)
    return found[0] if found else (None, "")


def focus(h):
    U.ShowWindow(h, 9)
    U.SetForegroundWindow(h)
    time.sleep(0.15)


def press(name, ms=120):
    vk = VK[name.upper()]
    sc = U.MapVirtualKeyW(vk, 0)
    ext = 1 if name.upper() in ("UP", "DOWN", "LEFT", "RIGHT") else 0
    U.keybd_event(vk, sc, ext, 0)
    time.sleep(ms / 1000)
    U.keybd_event(vk, sc, ext | 2, 0)
    time.sleep(0.12)


def cmd_keys(seq):
    h, _t = game_window()
    if not h:
        sys.exit("RPCS3 게임 창 없음")
    focus(h)
    for tok in [t.strip() for t in seq.split(",") if t.strip()]:
        if tok.lower().startswith("wait"):
            time.sleep(float(tok.split()[1]))
        else:
            n = 1
            if "*" in tok:
                tok, n = tok.split("*")
                n = int(n)
            for _ in range(n):
                press(tok)


def cmd_shot(path, scale=1.0):
    from PIL import ImageGrab
    h, t = game_window()
    if not h:
        sys.exit("RPCS3 게임 창 없음")
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    focus(h)                      # 다른 창·오버레이가 덮지 않게 앞으로
    time.sleep(0.3)
    r = wintypes.RECT()
    U.GetClientRect(h, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    U.ClientToScreen(h, ctypes.byref(pt))
    img = ImageGrab.grab(bbox=(pt.x, pt.y, pt.x + r.right, pt.y + r.bottom), all_screens=True)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    img.save(path)
    print("ok", img.size, t)


def cmd_start(owner):
    if os.path.exists(LOCK):
        sys.exit("GPU_BUSY: " + open(LOCK, encoding="utf-8", errors="replace").read())
    if os.system('tasklist /FI "IMAGENAME eq imas2pc.exe" | find /I "imas2pc.exe" >nul') == 0 or \
            os.system('tasklist /FI "IMAGENAME eq rpcs3.exe" | find /I "rpcs3.exe" >nul') == 0:
        sys.exit("GPU_BUSY: 게임 프로세스 실행 중")
    fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    p = subprocess.Popen([os.path.join(RPCS3, "rpcs3.exe"), "--no-gui", EBOOT], cwd=RPCS3)
    os.write(fd, f"runner_pid={p.pid} log=rpcs3_{owner} owner={owner} started={time.strftime('%Y-%m-%dT%H:%M:%S')}\n".encode())
    os.close(fd)
    print("STARTED", p.pid)


def cmd_stop():
    os.system("taskkill /IM rpcs3.exe /F >nul 2>&1")
    time.sleep(3)
    if os.path.exists(LOCK) and "rpcs3_" in open(LOCK, encoding="utf-8", errors="replace").read():
        os.remove(LOCK)
    print("stopped; lock", "남음" if os.path.exists(LOCK) else "해제")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "start":
        cmd_start(a[a.index("--owner") + 1] if "--owner" in a else "ui")
    elif a[0] == "keys":
        cmd_keys(a[1])
    elif a[0] == "shot":
        cmd_shot(a[1], float(a[a.index("--scale") + 1]) if "--scale" in a else 1.0)
    elif a[0] == "stop":
        cmd_stop()
