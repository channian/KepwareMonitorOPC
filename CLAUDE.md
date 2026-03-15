# KepwareMonitorOPC

## Debugging

1. 修 UI bug 時，先排除環境問題（瀏覽器快取、script 載入順序），確認問題可重現後再改程式碼
2. 修完前端 bug 後，提醒使用者 hard-refresh（Ctrl+Shift+R）或清除快取來驗證修復
3. Theme/dark mode toggle 邏輯必須 inline 在 HTML 中，不要放外部 JS 檔案，避免載入/依賴問題
4. 除錯時優先檢查 Console 錯誤和 Network tab 載入狀態，再決定是否需要改程式碼

## Architecture

- 本專案使用 HTML、CSS、JavaScript（無框架）
- 前端互動邏輯應 inline 在 HTML 中，避免外部 JS 載入依賴問題
