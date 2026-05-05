# KepwareMonitorOPC

## Debugging

1. 修 UI bug 時，先排除環境問題（瀏覽器快取、script 載入順序），確認問題可重現後再改程式碼
2. 修完前端 bug 後，提醒使用者 hard-refresh（Ctrl+Shift+R）或清除快取來驗證修復
3. Theme/dark mode toggle 邏輯必須 inline 在 HTML 中，不要放外部 JS 檔案，避免載入/依賴問題
4. 除錯時優先檢查 Console 錯誤和 Network tab 載入狀態，再決定是否需要改程式碼

## Architecture

- 本專案使用 HTML、CSS、JavaScript（無框架）
- 前端互動邏輯應 inline 在 HTML 中，避免外部 JS 載入依賴問題

## Frontend Refactoring Checklist

- 重構 templates 或 design system 前，確認所有 JS 函數都存在於 app.js
- 任何 app.js 或 template 變更後，加入 cache-busting query params（如 ?v=timestamp）
- 測試所有受影響頁面：Tags, Settings, Users, 密碼變更
- 為 JS helper functions 加入 console 錯誤 logging，讓靜默失效可見

## Kepware Monitoring Conventions

- 所有新監控功能必須支援多台 Server
- 告警主旨依事件類型分開（不合併）
- Tag address 解析遵循現有模組的 regex 模式
- commit 前執行 python -m py_compile

## Git Workflow

- commit 前必須執行語法檢查
- push 失敗時以 exponential backoff 重試（2s, 4s, 8s, 16s）
- 相關檔案變更歸為同一 commit，附描述性訊息
