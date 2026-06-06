# ChatVault：Spike → 原生 macOS SwiftUI 專案 — Migration / Architecture Plan

> 產出環境註記：本文件由雲端 Linux 容器內的 Claude Code 工作階段產出。該環境
> **無法存取** Mac 本機的 spike（`/Users/yadah/ChatVaultSpike`），也**無法編譯
> Swift/Xcode**。因此凡涉及 spike 內部原始碼細節的判斷，皆為依使用者貼上的摘要
> 推論，標記為〔需在 Mac 上核對〕。回到 Mac 本機後，第一件事應是實際讀取下列
> 5 個 spike 檔案來校正本計畫：
>
> 1. `/Users/yadah/ChatVaultSpike/docs/spike-report.md`
> 2. `/Users/yadah/ChatVaultSpike/telegram-connector-spike/Package.swift`
> 3. `/Users/yadah/ChatVaultSpike/telegram-connector-spike/Sources/TelegramConnectorSpike/TelegramConnectorSpike.swift`
> 4. `/Users/yadah/ChatVaultSpike/local-packages/TDLibKitLocal/Package.swift`
> 5. `/Users/yadah/ChatVaultSpike/local-packages/TDLibFrameworkLocal/Package.swift`

---

## 1. 已驗證（What is already validated）

- TDLibKit + TDLibFramework 是目前最可行的原生 Swift/macOS Telegram 路線。
- TDLibFramework binary artifact 很大（約 **333MB**）。
- SwiftPM 遠端 binary artifact 下載會 hang／timeout。
- 改用手動 `curl` 下載 `TDLibFramework.zip` **成功**，checksum 相符：
  `0929dbd7d79ca301b60612431aa4e811c946110e4f8439e41ae1b7410436b830`
- 已用下載的 `TDLibFramework.xcframework` 建出**本機** TDLibFramework package。
- 已建出**本機** TDLibKit package，指向本機 TDLibFramework package。
- Swift Package 能編譯並啟動；TDLib 初始化成功，抵達
  `authorizationStateWaitPhoneNumber`。
- 全程**未碰**任何舊備份資料。

## 2. 尚未驗證（What is NOT yet validated）

- 真正的 Telegram 登入流程（手機號碼 → 驗證碼 → 可能的 2FA password）尚未跑過。
- `listConversations` / `fetchMessages` / `downloadAttachment` 等實際資料拉取
  **完全未驗證**。
- 在**完整 Xcode app target（.app bundle）**中連結 333MB xcframework 的行為
  （簽章、bundle 體積、啟動時間）尚未驗證 —— 目前只在 SwiftPM executable 驗證過。
- SQLite schema、ChatVault Library 目錄格式、Import、AI Connector 全部尚未落地。
- Swift 6 strict concurrency 下把 TDLibKit client 包進 actor 的實際可行性
  〔需在 Mac 上核對 TDLibKit API 形狀〕。
- 此機是否已安裝/選用完整 Xcode（目前是 Command Line Tools，可能需 `xcode-select`）。

## 3. 建議 Xcode 專案結構

維持 platform-agnostic 方向，但 **MVP 先收斂 package 數量**，避免一次爆 8 個空殼
（符合「No speculative abstractions」）：

```
ChatVault/                      # 新的乾淨專案根（不是 spike 那個）
├── ChatVault.xcodeproj  or  Package.swift（App 用 SPM 整合）
├── Apps/
│   └── ChatVaultMac/           # SwiftUI App target（@main、Views）
├── Packages/
│   ├── ChatVaultCore/          # 純 model + protocol（ChatConnector / Capabilities / 通用 entity）
│   ├── ChatVaultDatabase/      # SQLite schema + DAO（建議 GRDB 或自寫薄封裝）
│   ├── ChatVaultLibrary/       # Library 開/建、manifest.json、目錄結構、state
│   └── ChatVaultConnectors/    # ConnectorRegistry + TelegramConnector(actor 封裝 TDLibKit)
├── Tests/                      # 對 Core / Database / Library 的單元測試
├── Docs/
└── ThirdParty/                 # 本機 TDLibFramework / TDLibKit（見第 5 節）
```

> `ChatVaultBackup / ChatVaultImport / ChatVaultAIConnector / ChatVaultSearch`
> 先**不要**建空 package；等 Core+DB+Library+Telegram 跑通後再逐一拆出。先放在
> 對應 package 內的子目錄即可，protocol 邊界先用型別劃分。

## 4. 本機 TDLib packages vs 遠端 SwiftPM

**結論：MVP 全程保留「本機 packages」。**

- 遠端 binary artifact 已證實會 hang／timeout，CI/重建風險高、不可重現。
- 本機 xcframework + checksum 已驗證可重現。
- 作法：把 `TDLibFrameworkLocal` / `TDLibKitLocal` 以 **local path SPM dependency**
  放進新專案的 `ThirdParty/`（或用 git submodule / 由腳本還原），App 依賴本機 package。
- 之後若要改回遠端版本，當成獨立工作項，不擋 MVP。〔需在 Mac 上核對兩個本機
  `Package.swift` 的實際宣告方式再定搬移細節〕

## 5. 如何處理 333MB TDLibFramework artifact

- **不要**把 333MB 二進位直接 commit 進 git（會撐爆 repo、push 失敗）。
- 建議：repo 內只放 package 殼 + 一支 fetch 腳本（`scripts/fetch-tdlib.sh`），
  腳本做：`curl` 下載 → 比對 checksum（`0929…6830`）→ 解壓到
  `ThirdParty/TDLibFrameworkLocal/…/TDLibFramework.xcframework`。
- xcframework 路徑加進 `.gitignore`；checksum 寫死在腳本內當守門員。
- README 註明「首次 clone 後需先跑 `scripts/fetch-tdlib.sh`」。
- 對 .app bundle 體積/簽章的影響，列為 milestone 1 的**已知風險觀測點**（見第 2 節）。

## 6. 如何安全包裝 TDLibKit（Swift concurrency）

針對「TDLibKit client 非 Sendable」：

- 在 `ChatVaultConnectors` 內建 `actor TelegramConnectorService`，**TDLib client
  只存在於這個 actor 內**，外部永不直接持有/傳遞 client。
- 對外只暴露 `ChatConnector` protocol 的 async 方法；client 的 update 流
  （TDLib 是 callback/poll 模型）在 actor 內轉成 `AsyncStream`。
- auth 狀態用一個 `@MainActor` 的 observable（或 actor → AsyncStream → ViewModel）
  單向往 UI 推。
- 不把 TDLib 的型別洩漏到 Core / UI；在 connector 邊界轉成 `RemoteConversation`
  / `MessageBatch` 等通用型別。
- 〔需在 Mac 上核對 TDLibKit 實際 API（client 建立方式、update 回呼簽名）再定
  actor 介面〕

## 7. 第一個 Xcode Milestone

**Milestone 1 — 「可啟動的殼 + 觸達 auth 狀態（不真登入）」**：

1. App 能啟動。
2. 顯示 Welcome 畫面。
3. 能建立 / 開啟一個測試用 ChatVault Library 資料夾（寫出 `manifest.json` + 空
   `chatvault.db` + 標準子目錄）。
4. 初始化 Telegram connector service，足以抵達 auth 狀態。
5. 顯示「waiting for phone number」狀態。
6. **尚不**真正登入（除非另外核准）。

## 8. 提議建立的 files / folders

> 本雲端工作階段（Linux，無法編譯 Xcode）只寫入「文件 + 腳本」這類 A 級檔案。
> 下方 Swift 骨架屬於「給你帶回 Mac 建立」的建議，本工作階段不寫。

**本工作階段實際寫入（已核准）：**

- `chatvault/README.md`
- `chatvault/Docs/chatvault-macos-migration-plan.md`（本檔）
- `chatvault/.gitignore`
- `chatvault/scripts/fetch-tdlib.sh`

**建議你在 Mac 上建立（本工作階段不做）：**

- `Apps/ChatVaultMac/{ChatVaultApp.swift, WelcomeView.swift}`
- `Packages/ChatVaultCore/`（`Package.swift` + `ChatConnector` protocol + 通用 model）
- `Packages/ChatVaultDatabase/`（SQLite schema：sources/conversations/participants/
  messages/attachments/sync_runs/import_runs/ai_access_log）
- `Packages/ChatVaultLibrary/`（manifest.json、目錄建立、state）
- `Packages/ChatVaultConnectors/`（`actor TelegramConnectorService` 殼 + Registry）
- `Tests/`

## 9. 不會碰的東西（What I will NOT touch）

- `/Users/yadah/telegram backup`、`/Volumes/FlyDrive01/telegram backup`。
- 舊 dashboard、舊 SQLite、舊媒體、舊 Telegram session。
- spike 既有檔案。
- 寄居 repo（`toroyabe.github.io`）的既有 `CNAME` / `README.md` / `master`(main)
  分支 / GitHub Pages 內容 —— 只在功能分支**新增** `chatvault/` 子資料夾。
- 不開 PR、不建新 repo、不裝相依、不跑破壞性指令（除非明確同意）。

## 10. 第一個 Milestone 的驗收標準

- App 在 macOS 上 build 成功並啟動，顯示 Welcome 畫面，無 crash。
- 點「建立 Library」→ 在所選資料夾產生 `manifest.json` + `chatvault.db`（schema
  已建）+ 標準子目錄；「開啟 Library」可重新讀取同一資料夾。
- TelegramConnectorService 初始化後，UI 顯示 `waiting for phone number`。
- 全程未發出真正的登入請求；未觸碰任何舊備份路徑。
- 單元測試覆蓋「建立/開啟 Library」與「auth 狀態機到 waitPhoneNumber」的**意圖**
  （非 UI 像素）。
- 333MB xcframework 透過 fetch 腳本還原、未進 git。

---

## 附錄 A：ChatVault Library 目錄格式（目標）

```
ChatVault Library/
├── manifest.json
├── chatvault.db
├── attachments/
│   └── <platform>/<source_id>/<conversation_id>/{images,videos,audio,files}/
├── thumbnails/
├── imports/reports/
├── ai/access-log/
├── logs/
└── state/
```

## 附錄 B：核心資料表（平台無關）

`sources`、`conversations`、`participants`、`messages`、`attachments`、
`sync_runs`、`import_runs`、`ai_access_log`。

避免 Telegram 專屬命名（如 `telegram_chat_id`），改用通用：`source`、`account`、
`conversation`、`participant`、`message`、`attachment`、`sync_run`、`import_run`。

## 附錄 C：Connector 框架（目標形狀）

```swift
protocol ChatConnector {
    var platform: ChatPlatform { get }
    var capabilities: ConnectorCapabilities { get }

    func authStatus() async throws -> ConnectorAuthStatus
    func startAuthFlow() async throws -> AuthFlow
    func submitAuthInput(_ input: AuthInput) async throws -> AuthFlowResult

    func listConversations() async throws -> [RemoteConversation]
    func fetchMessages(conversationId: String, cursor: SyncCursor?) async throws -> MessageBatch
    func downloadAttachment(_ attachment: RemoteAttachment, to destination: URL,
                            progress: @escaping (DownloadProgress) -> Void) async throws -> AttachmentDownloadResult
    func logout() async throws
}
```

`ConnectorCapabilities`：`supportsLiveSync`、`supportsImport`、
`supportsMediaDownload`、`supportsIncrementalSync`、`supportsThreads`、
`supportsReactions`、`supportsEdits`、`supportsDeletes`。

MVP registry **只註冊 Telegram**。

## 附錄 D：AI Connector（後期功能）的硬性限制

local only、read-only、預設關閉、優先 stdio/local MCP、無 raw SQL、無任意檔案系統
存取、不可寫入/刪除、不可觸發 backup/download、必須強制 limit/pagination、必須記錄
存取。建議 MCP 工具（後期）：`list_sources`、`list_conversations`、
`search_messages`、`get_message_context`、`get_conversation_timeline`、
`list_attachments`、`get_attachment_metadata`、`get_backup_overview`。
