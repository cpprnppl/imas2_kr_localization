# -*- coding: utf-8 -*-
"""
report_issues.py — 번역 Excel의 문제 행을 산출물(docs/retranslate_needed.md)로 기록

패치 때 자동 스킵/경고되는 행은 로그에서 잘려 묻힐 수 있으므로,
전수 스캔 결과를 레포에 커밋되는 보고서로 남긴다. (수동 재번역 작업 목록)

감지 항목:
  1. LLM 쓰레기 번역 (사고과정 유출/미번역 영문) — 패치 시 자동 스킵됨(원문 유지)
  2. 재줄바꿈 후 3줄 초과 — 게임에서 잘릴 수 있어 축약 필요

사용: 게임 tools 폴더 또는 아무 데서나  python report_issues.py
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
REPORT = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "retranslate_needed.md"))

sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import importlib.util
spec = importlib.util.spec_from_file_location("e2s", os.path.join(HERE, "excel2scb.py"))
e2s = importlib.util.module_from_spec(spec)
# excel2scb는 import 시 경로 상수만 계산하므로 안전
sys.path.insert(0, GAME_TOOLS)
spec.loader.exec_module(e2s)

import openpyxl

excel = os.path.join(GAME_TOOLS, "translation_1_with_entry.xlsx")
wb = openpyxl.load_workbook(excel, read_only=True, data_only=True)

_CLOSERS = "」』）)"

garbage, toolong, truncated = [], [], []
for ws in wb.worksheets:
    if ws.title.startswith("📋"):
        continue
    for r, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not row or len(row) < 7:
            continue
        tr = row[2]
        if tr is None or not str(tr).strip():
            continue
        t = str(tr)
        orig = str(row[1]) if row[1] else ""
        loc = (ws.title, r, str(row[4]), orig[:50], t)
        if e2s.is_garbage_translation(t):
            garbage.append(loc)
            continue
        # 미완성 번역: 원문은 닫는 괄호로 끝나는데 번역은 안 닫힘 (Gemini 중단 행)
        if orig.rstrip() and orig.rstrip()[-1] in _CLOSERS and \
                (not t.rstrip() or t.rstrip()[-1] not in _CLOSERS):
            truncated.append(loc)
        w = e2s.rewrap(t)
        if w.count("\n") + 1 > e2s.WRAP_WARN_LINES:
            toolong.append(loc + (w.count("\n") + 1,))
wb.close()

os.makedirs(os.path.dirname(REPORT), exist_ok=True)
with open(REPORT, "w", encoding="utf-8") as f:
    f.write("# 재번역/축약 필요 행 목록\n\n")
    f.write(f"원본 Excel: `{os.path.basename(excel)}` (자동 생성: report_issues.py)\n\n")
    f.write(f"## 1. LLM 쓰레기 번역 — {len(garbage)}행 (패치 시 자동 스킵, 게임에선 일본어로 표시)\n\n")
    f.write("| 시트 | 행 | 파일 | 원문(앞 50자) | 현재 번역 |\n|---|---|---|---|---|\n")
    for s, r, fp, orig, t in garbage:
        f.write(f"| {s} | {r} | {fp} | {orig.replace(chr(10), '⏎')} | {t[:60].replace(chr(10), '⏎')} |\n")
    f.write(f"\n## 2. 미완성 번역 의심 — {len(truncated)}행 (원문은 닫는 괄호로 끝나는데 번역이 안 닫힘, 뒷부분 누락 가능)\n\n")
    f.write("| 시트 | 행 | 파일 | 원문(앞 50자) | 현재 번역 |\n|---|---|---|---|---|\n")
    for s, r, fp, orig, t in truncated:
        f.write(f"| {s} | {r} | {fp} | {orig.replace(chr(10), '⏎')} | {t[:60].replace(chr(10), '⏎')} |\n")
    f.write(f"\n## 3. 재줄바꿈 후 {e2s.WRAP_WARN_LINES}줄 초과 — {len(toolong)}행 (게임에서 잘릴 수 있음, 축약 필요)\n\n")
    f.write("| 시트 | 행 | 파일 | 줄수 | 번역(앞 60자) |\n|---|---|---|---|---|\n")
    for s, r, fp, orig, t, nl in toolong:
        f.write(f"| {s} | {r} | {fp} | {nl} | {t[:60].replace(chr(10), '⏎')} |\n")

print(f"쓰레기 번역: {len(garbage)}행, 미완성 의심: {len(truncated)}행, {e2s.WRAP_WARN_LINES}줄 초과: {len(toolong)}행")
print(f"보고서: {REPORT}")
