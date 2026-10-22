# -*- coding: utf-8 -*-
"""
deploy_pcport.py — PC 포트(360 리컴파일)에 한글 SCB 배포

대상(기본): C:\\Users\\jackfilm\\Desktop\\imas2pc\\game_kor\\resource\\gscript
  2026-10-22 KOR 결정: 새 번역 배포의 기본 대상은 game_kor(한글판 사본, 실행은
  IMAS2PC_DISC_ROOT). 공유 build_imas2_o2\\game은 10-15 한글판 상태로 동결 —
  여기에 쓰려면 --allow-shared를 명시해야 한다.
원칙 (imas2pc 세션과 합의):
  - 원본 디스크 추출본(unpack\\imas2)은 건드리지 않는다. build 트리만 교체.
  - 360 엔진은 평문 pac을 수용 → output_pcport/(재암호화 전 dec)를 그대로 배포.
  - PC 트리에 존재하는 파일만 교체 (PS3 전용 파일 ~25개는 자동 제외).
  - 최초 교체 시 원본을 _backup_kr_orig/<상대경로>로 보존 (이미 있으면 재백업 안 함).
  - 배포 후 SHA-256 해시를 pcport_deploy_manifest.json에 기록.
  - ⚠ PS3 dec와 360 dec의 내용 동일성은 미검증 가정 — 인게임 검증은 imas2pc 세션 담당.

사용: python deploy_pcport.py                  (game_kor에 배포)
      python deploy_pcport.py --check          (대상/제외 목록만 출력)
      python deploy_pcport.py --allow-shared   (공유 build_imas2_o2\\game — 명시적으로만)
      python deploy_pcport.py --src360         (pcport360.py 산출물: 360 원본 dec + 한글 MSG.
                                                pcport360 검증 게이트 통과 시에만, game_kor 전용)
"""
import os, sys, glob, shutil, hashlib, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_TOOLS = r"C:\Users\jackfilm\Desktop\rpcs3-v0.0.39-18811-6bfb3327_win64_msvc\dev_hdd0\game\NPJB00337\USRDIR\resource\gscript\tools"
SRC360 = "--src360" in sys.argv
SRC = os.path.join(GAME_TOOLS, "output_pcport360" if SRC360 else "output_pcport")
PCPORT_KOR = r"C:\Users\jackfilm\Desktop\imas2pc\game_kor\resource\gscript"
PCPORT_SHARED = r"C:\Users\jackfilm\Desktop\imas2pc\build_imas2_o2\game\resource\gscript"
PCPORT = PCPORT_SHARED if "--allow-shared" in sys.argv else PCPORT_KOR
BACKUP = os.path.join(os.path.dirname(PCPORT), "_backup_kr_orig", "gscript")
BACKUP_PS3DEC = os.path.join(os.path.dirname(PCPORT), "_backup_ps3dec", "gscript")
MANIFEST = os.path.join(GAME_TOOLS, "pcport_deploy_manifest.json" if PCPORT == PCPORT_SHARED
                        else ("pcport_kor360_deploy_manifest.json" if SRC360
                              else "pcport_kor_deploy_manifest.json"))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    check = "--check" in sys.argv
    srcs = glob.glob(os.path.join(SRC, "**", "*.scb"), recursive=True)
    if not srcs:
        print(f"❌ 평문 산출물 없음: {SRC} — "
              + ("pcport360.py build" if SRC360 else "excel2scb.py(PCPORT_OUTPUT=True)") + " 먼저 실행")
        sys.exit(1)
    if not os.path.isdir(PCPORT):
        print(f"❌ PC 포트 gscript 없음: {PCPORT}")
        sys.exit(1)
    print(f"배포 대상: {PCPORT}" + ("  ⚠ 공유 기준선(--allow-shared)" if PCPORT == PCPORT_SHARED else ""))
    if SRC360:
        if PCPORT == PCPORT_SHARED:
            print("❌ --src360은 game_kor 전용 (공유 기준선 동결)")
            sys.exit(1)
        sys.path.insert(0, HERE)
        import pcport360
        print(f"소스: {SRC} (360 원본 기반) — 검증 게이트 실행")
        if not pcport360.validate_all():
            print("❌ 360 기준 구조 검증 실패 — 배포 중단")
            sys.exit(1)

    deployed, skipped = [], []
    manifest = {"deployed_at": datetime.datetime.now().isoformat(), "files": {}}
    for s in srcs:
        rel = os.path.relpath(s, SRC)
        dst = os.path.join(PCPORT, rel)
        if not os.path.exists(dst):
            skipped.append(rel)
            continue
        if check:
            deployed.append(rel)
            continue
        bak = os.path.join(BACKUP, rel)
        if not os.path.exists(bak):
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            shutil.copy2(dst, bak)
        if SRC360:
            # 지금 들어 있는 PS3 dec 배포본을 롤백용으로 보존 (최초 1회)
            bak2 = os.path.join(BACKUP_PS3DEC, rel)
            if not os.path.exists(bak2):
                os.makedirs(os.path.dirname(bak2), exist_ok=True)
                shutil.copy2(dst, bak2)
        shutil.copy2(s, dst)
        manifest["files"][rel.replace("\\", "/")] = sha256(dst)
        deployed.append(rel)

    print(f"{'대상' if check else '배포'}: {len(deployed)}개, PC 트리에 없어 제외: {len(skipped)}개")
    for r in skipped[:10]:
        print("   (제외)", r)
    if not check:
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        print(f"원본 백업: {BACKUP}")
        if SRC360:
            print(f"PS3 dec 배포본 백업(롤백용): {BACKUP_PS3DEC}")
        print(f"해시 기록: {MANIFEST}")
        print("✅ 완료 — 인게임 검증은 imas2pc 세션에 요청할 것")

if __name__ == "__main__":
    main()
