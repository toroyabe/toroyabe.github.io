# 用官方 BC MCP Server 連 Claude Desktop（Mac）

微軟在 2026 Wave 1 推出官方 Business Central MCP Server，這是建議做法（取代本資料夾的自製 `server.js`）。
本指南帶你把 **Claude Desktop（Mac）** 連到 BC，用自然語言查資料。

---

## 你的環境值（已填好）

| 項目 | 值 |
|---|---|
| Tenant ID | `d212bfb8-dfd0-4db0-8493-261a6393470f` |
| Environment | `Production` |
| BC 端 MCP 設定名稱 | `Claude` |
| 先連的公司 (Company) | `ILTM Pte Ltd` |
| Client ID | ⬜ 階段 2 註冊後填入 |

> 連線端點：`https://mcp.businesscentral.dynamics.com`（proxy 會自動處理，不用手動填）

---

## 階段 1：BC 端確認（已大致完成）

在 BC →「Model Context Protocol (MCP) Server Configurations」→ 開啟 `Claude` 設定：

- [x] 已 `Add All Standard APIs as Tools`（全部唯讀 Allow Read）
- [ ] **Active 開關 → 開啟**（務必！沒開不生效）
- [x] Dynamic Tool Mode → 開啟（建議；工具較精簡）
- [ ] 點 **Validate** 確認無誤
- Unblock Edit Tools → 保持關閉（維持唯讀，安全）

---

## 階段 2：在 Microsoft Entra 註冊 App（需管理員）

1. 進入 **Microsoft Entra 系統管理中心** → **Microsoft Entra ID** → **App registrations** → **New registration**
2. 名稱填 `BC MCP - Claude` → **Register**
3. 複製 **Application (client) ID** → 回填到上面表格的 Client ID

### 2a. 啟用公用用戶端流程
- 左側 **Authentication** → 最下方 **Allow public client flows** → 設為 **Yes** → Save

### 2b. 加 Redirect URI（桌面用）
- 同一頁 **Authentication** → **Add a platform** → **Mobile and desktop applications**
- 自訂 redirect URI 填（把 `<clientID>` 換成你剛複製的 Client ID）：
  ```
  ms-appx-web://Microsoft.AAD.BrokerPlugin/<clientID>
  ```
- Save

### 2c. 加 API 權限
- 左側 **API permissions** → **Add a permission** → **Microsoft APIs** → **Dynamics 365 Business Central** → **Delegated permissions**
- 勾選：
  - `user_impersonation`
  - `Financials.ReadWrite.All`
- **Add permissions**
- 點 **Grant admin consent for <tenant>** → 確認

> 註：雖然權限叫 ReadWrite，但實際能做什麼仍受兩層限制：①你 BC 帳號本身的權限、②`Claude` 這個 MCP 設定目前全唯讀。所以現在依然只能讀。

---

## 階段 3：安裝官方 proxy 並設定（Mac 終端機）

官方提供 `bc-mcp-proxy`，是一個小精靈，會幫你登入並產生 Claude Desktop 設定。

```bash
# 1. 安裝
python3 -m pip install --upgrade bc-mcp-proxy

# 2. 執行設定精靈（會問 tenant / client id / 環境 / 公司，並跳出登入）
python3 -m bc_mcp_proxy setup
```

精靈詢問時這樣填：

| 精靈問你 | 填入 |
|---|---|
| Tenant ID | `d212bfb8-dfd0-4db0-8493-261a6393470f` |
| Client ID | （階段 2 的 Application client ID） |
| Environment | `Production` |
| Company | `ILTM Pte Ltd` |
| (Config name，選填) | `Claude` |

或一行非互動式（把 `<CLIENT_ID>` 換掉）：

```bash
python3 -m bc_mcp_proxy --TenantId "d212bfb8-dfd0-4db0-8493-261a6393470f" \
  --ClientId "<CLIENT_ID>" \
  --Environment "Production" \
  --Company "ILTM Pte Ltd"
```

執行後會啟動 **device-code 登入**：終端機給你一組代碼，照指示在瀏覽器用你的公司帳號登入授權。Token 會快取在 `~/.cache/BcMCPProxyPython/`。

---

## 階段 4：把設定貼進 Claude Desktop

1. 精靈會印出一段 **Claude Desktop 用的 JSON snippet**（claude_mcp.json）。
2. 開啟設定檔（Mac 路徑）：
   ```
   ~/Library/Application Support/Claude/claude_desktop_config.json
   ```
   （沒有就新建）
3. 把 snippet 併進 `"mcpServers": { ... }` 區塊。大致長這樣：
   ```json
   {
     "mcpServers": {
       "business-central": {
         "command": "python3",
         "args": ["-m", "bc_mcp_proxy"],
         "env": {
           "BC_TENANT_ID": "d212bfb8-dfd0-4db0-8493-261a6393470f",
           "BC_CLIENT_ID": "<CLIENT_ID>",
           "BC_ENVIRONMENT": "Production",
           "BC_COMPANY": "ILTM Pte Ltd"
         }
       }
     }
   }
   ```
   （實際以精靈產生的內容為準。）
4. **完全關閉並重開 Claude Desktop**。

---

## 階段 5：測試

在 Claude Desktop 對話框輸入：

- 「列出 ILTM Pte Ltd 的客戶」
- 「查一下項目（items）清單」
- 「ILTM Pte Ltd 最近的銷售發票有哪些？」

能回資料就成功了 🎉

---

## 之後：加其他公司

20 間正式公司共用同一個 BC 設定與同一個 Entra App，只是 **Company 值不同**。
要多連一間，在 `claude_desktop_config.json` 複製一份、改 `BC_COMPANY` 和伺服器名稱即可，例如：

```json
"business-central-craveva": {
  "command": "python3",
  "args": ["-m", "bc_mcp_proxy"],
  "env": { "...": "...", "BC_COMPANY": "Craveva Pte Ltd" }
}
```

### 20 間正式公司的 Company 值（精確）
```
Craveva Pte Ltd
ILHA Formosa Holding Pte Ltd
ILHA Gourmet Pte Ltd
ILTM BK Pte Ltd
ILTM BP Pte Ltd
ILTM Central Pte Ltd
ILTM Clementi Pte Ltd
ILTM East Pte Ltd
ILTM JE Pte Ltd
ILTM North East Pte Ltd
ILTM North Point Pte Ltd
ILTM Pte Ltd
ILTM Punggol Pte Ltd
ILTM SG Pte Ltd
ILTM SRG Pte Ltd
ILTM Tampines Pte Ltd
ILTM West Pte Ltd
ILTM Woodleigh Pte Ltd
ILTM Yakitori Pte Ltd
ITLM Ventures Pte Ltd   ← 注意：Name 拼成 ITLM，要照這個填
```

> `Z_` 開頭的 8 間都是測試/勿動，不要連。

---

## 疑難排解

| 症狀 | 處理 |
|---|---|
| 登入後仍連不上 | 確認 BC 的 `Claude` 設定 **Active 已開** + 已 Validate |
| 找不到公司 | Company 名稱要與 BC 一字不差（含 `ITLM` 那個拼法） |
| 權限/consent 錯誤 | 回階段 2c 確認已 **Grant admin consent** |
| redirect 錯誤 | 確認 redirect URI 是 `ms-appx-web://Microsoft.AAD.BrokerPlugin/<clientID>` 且 client id 正確 |
| 只能讀不能改 | 正常，目前 MCP 設定全唯讀；要寫入需在 BC 端開對應 Create/Modify 權限 |

## 參考
- Business Central MCP Server Overview：https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview
- Connect to non-Microsoft clients：https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/use-mcp-server-non-microsoft
- 官方 proxy（BcMCPProxyPython）：https://github.com/microsoft/BCTech/tree/master/samples/BcMCPProxyPython
