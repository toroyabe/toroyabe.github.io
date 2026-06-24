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
| Client ID | `274ce507-78d3-458f-9e0e-29351b13eec0` |

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
  --ClientId "274ce507-78d3-458f-9e0e-29351b13eec0" \
  --Environment "Production" \
  --Company "ILTM Pte Ltd"
```

執行後會啟動 **device-code 登入**：終端機給你一組代碼，照指示在瀏覽器用你的公司帳號登入授權。Token 會快取在 `~/.cache/BcMCPProxyPython/`。

---

## 階段 4：把設定貼進 Claude Desktop

> ⚠️ 實測重點：精靈產生的 `~/.bc_mcp_proxy/claude_mcp.json` **只有「裡面那一塊」**
> （`command` + `args`），**少了外層 `mcpServers` 包裝與伺服器名字**。直接複製整個檔案會無效，必須包起來。
> 另外 `command` 是**實際的 Python 絕對路徑**（例如本機是 miniconda：
> `/opt/homebrew/Caskroom/miniconda/base/bin/python3`），不是 `python3`。

最穩的做法：用一行指令讀取精靈產生的檔案、自動包好、寫進 Claude Desktop 設定檔。

**macOS（單一公司 = ILTM Pte Ltd）：**
```bash
mkdir -p ~/Library/Application\ Support/Claude && python3 -c "import json,os; s=json.load(open(os.path.expanduser('~/.bc_mcp_proxy/claude_mcp.json'))); d=os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json'); json.dump({'mcpServers':{'business-central':s}}, open(d,'w'), indent=2); print('OK ->', d)"
```

設定檔位置：`~/Library/Application Support/Claude/claude_desktop_config.json`

最後 **⌘ + Q 完全關閉 Claude Desktop** 再重開（不是只關視窗）。

> 多行貼上（heredoc）在終端機常會卡在 `>` 等待 `EOF`，看起來「沒反應」。用上面的**單行 / 一行 `python -c`** 最不易出錯。

---

## 階段 5：測試

在 Claude Desktop 對話框輸入：

- 「列出 ILTM Pte Ltd 的客戶」
- 「查一下項目（items）清單」
- 「ILTM Pte Ltd 最近的銷售發票有哪些？」

能回資料就成功了 🎉

---

## 在 Windows 電腦設定（公司電腦）

Entra App **不用重做**（全公司共用）。只要在 Windows 做「裝 proxy → 跑精靈 → 寫設定 → 重開」。
用「命令提示字元 (Command Prompt)」或 PowerShell：

```bat
:: 0. 確認有 Python（沒有就到 Microsoft Store 或 python.org 裝，安裝勾 Add to PATH）
python --version

:: 1. 安裝 proxy
python -m pip install --upgrade bc-mcp-proxy

:: 2. 跑精靈（填 Tenant / Client / Production / ILTM Pte Ltd / Claude，並 device-code 登入）
python -m bc_mcp_proxy setup
```

寫入 Claude Desktop 設定（Windows 路徑是 `%APPDATA%\Claude\`，與 Mac 不同）：

```bat
python -c "import json,os; s=json.load(open(os.path.join(os.path.expanduser('~'),'.bc_mcp_proxy','claude_mcp.json'))); d=os.path.join(os.environ['APPDATA'],'Claude','claude_desktop_config.json'); os.makedirs(os.path.dirname(d),exist_ok=True); json.dump({'mcpServers':{'business-central':s}},open(d,'w'),indent=2); print('OK ->',d)"
```

最後完全結束 Claude Desktop（工作列圖示右鍵 → Quit）再重開。

---

## 之後：加其他公司

20 間正式公司共用同一個 BC 設定與同一個 Entra App，只是 **Company 值不同**。
每間 = `claude_desktop_config.json` 裡一條 connector（同 Tenant/Client，只差 `--Company`）。

下面一行指令會**一次產生全部 20 間**具名 connector（`business-central-iltm`、`business-central-craveva`…），
並自動沿用精靈產生的 Python 路徑（跨平台都對）。

**macOS：**
```bash
python3 -c "import json,os,re; base=json.load(open(os.path.expanduser('~/.bc_mcp_proxy/claude_mcp.json'))); cmd=base['command']; C=['Craveva Pte Ltd','ILHA Formosa Holding Pte Ltd','ILHA Gourmet Pte Ltd','ILTM BK Pte Ltd','ILTM BP Pte Ltd','ILTM Central Pte Ltd','ILTM Clementi Pte Ltd','ILTM East Pte Ltd','ILTM JE Pte Ltd','ILTM North East Pte Ltd','ILTM North Point Pte Ltd','ILTM Pte Ltd','ILTM Punggol Pte Ltd','ILTM SG Pte Ltd','ILTM SRG Pte Ltd','ILTM Tampines Pte Ltd','ILTM West Pte Ltd','ILTM Woodleigh Pte Ltd','ILTM Yakitori Pte Ltd','ITLM Ventures Pte Ltd']; tid='d212bfb8-dfd0-4db0-8493-261a6393470f'; cid='274ce507-78d3-458f-9e0e-29351b13eec0'; S={('business-central-'+re.sub('[^a-z0-9]+','-',c.lower().replace(' pte ltd','')).strip('-')):{'command':cmd,'args':['-m','bc_mcp_proxy','--TenantId',tid,'--ClientId',cid,'--Environment','Production','--Company',c,'--ConfigurationName','Claude']} for c in C}; d=os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json'); json.dump({'mcpServers':S},open(d,'w'),indent=2); print('OK',len(S),'->',d)"
```

**Windows：**（與上相同，只差結尾路徑用 `%APPDATA%`）
```bat
python -c "import json,os,re; base=json.load(open(os.path.join(os.path.expanduser('~'),'.bc_mcp_proxy','claude_mcp.json'))); cmd=base['command']; C=['Craveva Pte Ltd','ILHA Formosa Holding Pte Ltd','ILHA Gourmet Pte Ltd','ILTM BK Pte Ltd','ILTM BP Pte Ltd','ILTM Central Pte Ltd','ILTM Clementi Pte Ltd','ILTM East Pte Ltd','ILTM JE Pte Ltd','ILTM North East Pte Ltd','ILTM North Point Pte Ltd','ILTM Pte Ltd','ILTM Punggol Pte Ltd','ILTM SG Pte Ltd','ILTM SRG Pte Ltd','ILTM Tampines Pte Ltd','ILTM West Pte Ltd','ILTM Woodleigh Pte Ltd','ILTM Yakitori Pte Ltd','ITLM Ventures Pte Ltd']; tid='d212bfb8-dfd0-4db0-8493-261a6393470f'; cid='274ce507-78d3-458f-9e0e-29351b13eec0'; S={('business-central-'+re.sub('[^a-z0-9]+','-',c.lower().replace(' pte ltd','')).strip('-')):{'command':cmd,'args':['-m','bc_mcp_proxy','--TenantId',tid,'--ClientId',cid,'--Environment','Production','--Company',c,'--ConfigurationName','Claude']} for c in C}; d=os.path.join(os.environ['APPDATA'],'Claude','claude_desktop_config.json'); json.dump({'mcpServers':S},open(d,'w'),indent=2); print('OK',len(S),'->',d)"
```

> ⚠️ 別把 Windows 版跑在 Mac（會出 `KeyError: 'APPDATA'`），反之亦然。差別只在最後設定檔路徑。
> 用法：在 Claude 說「用 iltm-tampines 列出客戶」「craveva 最近的發票」。

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

### 20 條連接器名稱對照表
用法：在 Claude 直接指定確切名稱最穩，例如「用 `business-central-craveva` 查 company information」。

| 公司 | 連接器名稱 |
|---|---|
| Craveva Pte Ltd | `business-central-craveva` |
| ILHA Formosa Holding Pte Ltd | `business-central-ilha-formosa-holding` |
| ILHA Gourmet Pte Ltd | `business-central-ilha-gourmet` |
| ILTM Pte Ltd | `business-central-iltm` |
| ILTM BK Pte Ltd | `business-central-iltm-bk` |
| ILTM BP Pte Ltd | `business-central-iltm-bp` |
| ILTM Central Pte Ltd | `business-central-iltm-central` |
| ILTM Clementi Pte Ltd | `business-central-iltm-clementi` |
| ILTM East Pte Ltd | `business-central-iltm-east` |
| ILTM JE Pte Ltd | `business-central-iltm-je` |
| ILTM North East Pte Ltd | `business-central-iltm-north-east` |
| ILTM North Point Pte Ltd | `business-central-iltm-north-point` |
| ILTM Punggol Pte Ltd | `business-central-iltm-punggol` |
| ILTM SG Pte Ltd | `business-central-iltm-sg` |
| ILTM SRG Pte Ltd | `business-central-iltm-srg` |
| ILTM Tampines Pte Ltd | `business-central-iltm-tampines` |
| ILTM West Pte Ltd | `business-central-iltm-west` |
| ILTM Woodleigh Pte Ltd | `business-central-iltm-woodleigh` |
| ILTM Yakitori Pte Ltd | `business-central-iltm-yakitori` |
| ITLM Ventures Pte Ltd | `business-central-itlm-ventures` |

---

## 常用查詢問法

對話時建議「**指定連接器 + 要做什麼**」。範例：

**基本資料**
- 「用 `business-central-iltm` 查 company information」
- 「用 `business-central-craveva` 列出所有客戶」
- 「用 `business-central-iltm-yakitori` 列出項目（items）和庫存數量」

**銷售 / 應收**
- 「用 `business-central-iltm` 列出本月的銷售發票」
- 「用 `business-central-iltm` 查未結清的應收帳款（open customer ledger entries）」
- 「用 `business-central-iltm` 查客戶 XXX 的所有交易明細」

**採購 / 應付**
- 「用 `business-central-iltm` 列出供應商（vendors）」
- 「用 `business-central-iltm` 查未付的採購發票」

**庫存**
- 「用 `business-central-iltm` 查項目 XXX 目前庫存」
- 「用 `business-central-iltm` 列出庫存量低於 10 的項目」

**跨店比較（無單一工具，需逐間問再彙總）**
- 「分別用 iltm、iltm-tampines、iltm-yakitori 查本月銷售發票總額，再幫我做成比較表」

> 小技巧：
> - 不確定某資料叫什麼，先問「你有哪些跟 customer/invoice 相關的 actions？」(它會跑 `bc_actions_search`)。
> - 目前全唯讀，問「列出/查詢」類最順；改資料/過帳目前會被 BC 擋。

---

## 疑難排解

| 症狀 | 處理 |
|---|---|
| 登入後仍連不上 | 確認 BC 的 `Claude` 設定 **Active 已開** + 已 Validate |
| 找不到公司 | Company 名稱要與 BC 一字不差（含 `ITLM` 那個拼法） |
| 權限/consent 錯誤 | 回階段 2c 確認已 **Grant admin consent** |
| redirect 錯誤 | 確認 redirect URI 是 `ms-appx-web://Microsoft.AAD.BrokerPlugin/<clientID>` 且 client id 正確 |
| 只能讀不能改 | 正常，目前 MCP 設定全唯讀；要寫入需在 BC 端開對應 Create/Modify 權限 |
| 工具呼叫卡住/timeout（等很久沒回） | ① token 過期 → 終端機重跑一次 `python3 -m bc_mcp_proxy setup` 重新登入；② 在 Claude Desktop 完全 ⌘+Q 重開讓 proxy 重啟；③ 首次呼叫某間公司可能要再授權一次。timeout ≠「0 筆資料」 |
| 改了設定檔沒生效 | 一定要 **⌘+Q（Mac）/ 工作列右鍵 Quit（Win）完全結束**再開，只關視窗不會重讀設定 |

## 參考
- Business Central MCP Server Overview：https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/mcp-overview
- Connect to non-Microsoft clients：https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/ai/use-mcp-server-non-microsoft
- 官方 proxy（BcMCPProxyPython）：https://github.com/microsoft/BCTech/tree/master/samples/BcMCPProxyPython
