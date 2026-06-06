# ChatVault

本地優先（local-first）的聊天封存與 AI 記憶 App。原生 macOS（SwiftUI），
先支援 Telegram，核心架構保持平台無關，未來可擴充 WhatsApp / LINE / Signal /
iMessage / Discord / Slack / Teams / Email 等 connector。

> ⚠️ 這不是「Telegram 備份工具」。架構是：
> **ChatVault Core + Connector Framework + Telegram Connector（第一個 connector）**

---

## 這個資料夾是什麼

此 `chatvault/` 資料夾目前**只包含規劃文件與基礎設施腳本**，是在一個無法編譯
Swift/Xcode 的雲端 Linux 環境產出的。**實際的 macOS App 與 Swift packages 要在
Mac 本機用 Xcode 建立。**

| 路徑 | 說明 |
|---|---|
| `Docs/chatvault-macos-migration-plan.md` | Spike → 原生 macOS 專案的完整遷移／架構計畫（10 段） |
| `scripts/fetch-tdlib.sh` | 下載並校驗 333MB `TDLibFramework.xcframework` 的腳本 |
| `.gitignore` | 排除大型二進位與 build 產物 |

## Mac 端接手流程

```bash
# 1. 取得此分支
git clone <repo-url>
git checkout claude/chatvault-macos-architecture-6vhE9

# 2. 先讀計畫
open chatvault/Docs/chatvault-macos-migration-plan.md

# 3. 校正計畫：實際讀取 spike 的 5 個檔案（見計畫文件頂部清單）

# 4. 還原 TDLibFramework（不進 git 的 333MB 二進位）
bash chatvault/scripts/fetch-tdlib.sh

# 5. 確認 Xcode（目前可能只有 Command Line Tools）
xcode-select -p
# 必要時：sudo xcode-select -s /Applications/Xcode.app/Contents/Developer

# 6. 依計畫第 3、7 節，在 Mac 上建立 Xcode 專案與 Swift packages
```

## 第一個 Milestone

可啟動的 SwiftUI 殼：Welcome 畫面 → 建立/開啟 ChatVault Library 資料夾 →
初始化 Telegram connector service 抵達 `authorizationStateWaitPhoneNumber` →
顯示「waiting for phone number」。**尚不真正登入。** 驗收標準見計畫第 10 節。

## 資料安全紅線

- **絕不**碰、改、刪舊備份：`/Users/yadah/telegram backup`、
  `/Volumes/FlyDrive01/telegram backup`，以及舊 dashboard / 舊 SQLite / 舊媒體 /
  舊 Telegram session。
- 未來的「匯入既有備份」功能必須對舊資料**唯讀**，並以 copy-import 進新的
  ChatVault Library。
