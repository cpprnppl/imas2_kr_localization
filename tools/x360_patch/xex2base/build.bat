@echo off
rem Builds xex2base.exe from imas2pc's xex_basefile.cpp + XenonRecomp thirdparty
rem (tiny-AES-c, TinySHA1, libmspack lzxd - LGPL-2.1). Paths are this PC's checkouts.
setlocal
set IMAS2PC=C:\Users\jackfilm\Desktop\imas2pc
set XR=C:\Users\jackfilm\Desktop\XenonRecomp\thirdparty
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
clang-cl /nologo /O2 /EHsc /std:c++17 /D_CRT_SECURE_NO_WARNINGS ^
  /I"%IMAS2PC%\src\core" /I"%XR%\tiny-AES-c" /I"%XR%\TinySHA1" /I"%XR%\libmspack\libmspack\mspack" ^
  xex2base.cpp "%IMAS2PC%\src\core\xex_basefile.cpp" "%XR%\tiny-AES-c\aes.c" "%XR%\libmspack\libmspack\mspack\lzxd.c" ^
  /Fe:xex2base.exe || exit /b 1
del *.obj 2>nul
echo built %~dp0xex2base.exe
