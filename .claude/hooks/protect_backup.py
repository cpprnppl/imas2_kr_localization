# -*- coding: utf-8 -*-
"""PreToolUse 훅: 순정 SCB 백업 폴더('gscript - 복사본') 쓰기 차단.

과거 사고: 패치본이 백업/원본 위치에 섞여 들어가 재패치 시 오염됐다.
백업 폴더는 어떤 도구로도 수정되면 안 된다. (CLAUDE.md 절대 규칙 1)
"""
import sys, json

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

p = (d.get("tool_input") or {}).get("file_path", "") or ""
# 폴더명에 한글이 있어 인코딩 함정을 피해 ASCII 부분으로 매칭 ("gscript - 복사본")
if "gscript - " in p:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Pristine SCB backup folder (gscript - *) is READ-ONLY. "
                "Patched files go to the live gscript folder via deploy.py. See CLAUDE.md."
            ),
        }
    }))
sys.exit(0)
