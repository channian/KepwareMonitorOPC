# -*- mode: python ; coding: utf-8 -*-
#
# KepwareMonitorOPC PyInstaller 打包設定
#
# 用法（於專案根目錄執行，Windows 開發機）：
#   pyinstaller KepwareMonitor.spec
#
# 產出：dist/KepwareMonitor.exe（單一執行檔，內含所有 Python 程式碼與
# web/templates、web/static 靜態資源），部署步驟見 docs/deployment-iis.md
# 方式 B。
#
# 為什麼用 .spec 檔而不是純 CLI 指令：
#   uvicorn / asyncua / jinja2 都有「依情境動態載入子模組」的機制
#   （uvicorn 依平台選擇 event loop 實作、asyncua 依安全策略選擇加密
#   後端、FastAPI 的 Form(...) 需要 python-multipart 但由 Starlette 在
#   請求時才惰性 import）。PyInstaller 的靜態分析常常追不到這類動態
#   載入，需要明確補上 hiddenimports，否則要等執行期才會噴
#   ModuleNotFoundError。集中寫在這份 .spec 檔裡才能被版控、code review，
#   不會像一長串 CLI --hidden-import flag 那樣容易漏打或漏抄。
#
# 首次在新的 PyInstaller/套件版本下打包時，若仍出現
# ModuleNotFoundError，請對照錯誤訊息把缺少的模組加進下方
# hidden_imports，並回頭更新這份檔案（不要只在當次手動加 CLI flag）。

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = (
    collect_submodules('uvicorn')
    + collect_submodules('asyncua')
    + collect_submodules('jinja2')
    + [
        # FastAPI 的 Form(...)（登入表單）依賴 python-multipart 解析
        # multipart/form-data，但 Starlette 是在請求進來時才惰性
        # import，靜態分析常抓不到。套件在不同版本下可 import 的模組
        # 名稱不一致（multipart / python_multipart），兩個都列上較保險。
        'multipart',
        'python_multipart',
        # Email 寄送用到，理論上已被 ase_email_service.py 的靜態
        # import 涵蓋，這裡明確列出作為保險。
        'email.mime.text',
        'email.mime.multipart',
    ]
)

a = Analysis(
    ['kepware_monitor.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='KepwareMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
