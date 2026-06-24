# Business Central MCP server（給 Claude Code 用）

> ⚠️ **首選請用官方做法**：微軟在 2026 Wave 1 已內建官方 BC MCP Server。
> 你的環境（Application 28.1）完全支援，建議照 [`官方做法-Claude-Desktop.md`](./官方做法-Claude-Desktop.md) 設定。
> 本資料夾的自製 server 僅作為**備案**（例如環境版本過舊時使用）。

讓 **Claude Code 直接串接 Microsoft Dynamics 365 Business Central**，裝好之後你就能用對話的方式查 BC 資料，例如：

> 「列出未結清的銷售訂單」、「查客戶 C00010 的資料」、「這個月開了哪些發票？」

底層是一個 [MCP](https://modelcontextprotocol.io) server，透過 BC 官方 REST/OData v2.0 API 取資料，認證用 OAuth 2.0 client credentials。

---

## 一、在 Azure / Business Central 端設定（一次性）

需要請有權限的人（IT 或 BC 管理員）做下面的事。

### 1. 在 Entra ID（Azure AD）建立應用程式註冊
1. 進入 [Entra 系統管理中心](https://entra.microsoft.com) → **應用程式** → **應用程式註冊** → **新增註冊**。
2. 取個名字（例如 `claude-bc-mcp`），帳戶類型選「僅此組織目錄」。註冊後記下：
   - **應用程式 (用戶端) 識別碼** → 之後填 `BC_CLIENT_ID`
   - **目錄 (租用戶) 識別碼** → 之後填 `BC_TENANT_ID`
3. 左側 **憑證與祕密** → **新增用戶端密碼**，建立後**立刻複製「值」**（離開頁面就看不到了）→ 之後填 `BC_CLIENT_SECRET`。

> 用 client credentials（服務對服務）就不需要設定 API 權限/redirect URI；授權是在 BC 端用下一步綁定。

### 2. 在 Business Central 端授權這個應用程式
1. BC 後台搜尋並開啟 **Microsoft Entra Applications**（或「Microsoft Entra 應用程式」）。
2. **新增**一筆，**Client ID** 填上面的應用程式識別碼。
3. **State** 設為 **Enabled**。
4. 指派權限集：要查資料至少給 **D365 BUS FULL ACCESS**（或依需求給較小的權限集）。

### 3. 確認環境名稱
BC 後台 → **Admin Center** 可看到環境名稱（例如 `Production` 或 `Sandbox`），填 `BC_ENVIRONMENT`。

---

## 二、在本機安裝這個 server

```bash
cd bc-mcp
npm install
cp .env.example .env
# 編輯 .env，填入上面拿到的 tenant / client id / secret / environment
```

> `.env` 已被 `.gitignore` 排除，**密鑰不會被 commit**。這個 repo 是公開的，務必只把密鑰放在本機 `.env`。

---

## 三、把它加進 Claude Code

在專案根目錄執行（把路徑換成你的實際路徑）：

```bash
claude mcp add business-central -- node /絕對路徑/到/toroyabe.github.io/bc-mcp/server.js
```

或手動編輯 `~/.claude.json` / 專案的 `.mcp.json`：

```json
{
  "mcpServers": {
    "business-central": {
      "command": "node",
      "args": ["/絕對路徑/到/toroyabe.github.io/bc-mcp/server.js"]
    }
  }
}
```

重啟 Claude Code 後，用 `/mcp` 應該會看到 `business-central`。

---

## 四、開始對話

先確認連線：

> 「用 bc_check_connection 檢查 Business Central 連線」

成功的話會列出可存取的公司。接著就能自由問，例如：

- 「列出前 10 筆客戶」
- 「查 items 裡 inventory 大於 100 的品項」
- 「salesInvoices 這個月（postingDate）的清單」

---

## 工具一覽

| 工具 | 用途 |
|------|------|
| `bc_check_connection` | 驗證設定與認證，列出可存取公司 |
| `bc_list_companies` | 列出所有公司 |
| `bc_list_entities` | 從 metadata 列出可查詢的 entity set |
| `bc_query` | 查某 entity，支援 `$filter/$select/$orderby/$top/$skip/$expand` |
| `bc_get` | 依 id 取得單筆 |
| `bc_raw` | 進階：自訂 API page、特殊 OData、或寫入（POST/PATCH/DELETE） |

## 設定變數（.env）

| 變數 | 必填 | 說明 |
|------|------|------|
| `BC_TENANT_ID` | ✅ | Entra 租戶 ID（GUID 或網域） |
| `BC_CLIENT_ID` | ✅ | 應用程式 (client) ID |
| `BC_CLIENT_SECRET` | ✅ | client secret 值 |
| `BC_ENVIRONMENT` | | 環境名稱，預設 `Production` |
| `BC_DEFAULT_COMPANY` | | 預設公司名稱，多公司時免每次指定 |
| `BC_API_ROUTE` | | API 路由，預設 `v2.0`（標準 API） |

## 疑難排解

- **取得 token 失敗 (401/invalid_client)**：client id/secret 或 tenant 不對；secret 過期要重建。
- **BC API 401/403**：第 2 步的 Entra Application 沒啟用或權限集不足。
- **找不到公司 / 多家公司**：用 `bc_list_companies` 看名稱，或在 `.env` 設 `BC_DEFAULT_COMPANY`。
- **某 entity 404**：用 `bc_list_entities` 確認正確名稱；自訂 page 要改用 `bc_raw` 或設定 `BC_API_ROUTE`。
