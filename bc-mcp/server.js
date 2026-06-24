#!/usr/bin/env node
/**
 * Microsoft Dynamics 365 Business Central — MCP server
 *
 * Exposes Business Central's REST/OData v2.0 API to Claude Code as MCP tools,
 * so you can query your company's BC data through natural-language conversation.
 *
 * Auth: OAuth 2.0 client credentials (Entra ID app registration). Credentials
 * are read from environment variables only — see .env.example.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// ---------------------------------------------------------------------------
// Config — load a sibling .env if present (no extra dependency), then env vars.
// ---------------------------------------------------------------------------
function loadDotEnv() {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const raw = readFileSync(join(here, ".env"), "utf8");
    for (const line of raw.split("\n")) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (!m) continue;
      let val = m[2];
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (process.env[m[1]] === undefined) process.env[m[1]] = val;
    }
  } catch {
    // no .env file — rely on real environment variables
  }
}
loadDotEnv();

const CFG = {
  tenantId: process.env.BC_TENANT_ID,
  clientId: process.env.BC_CLIENT_ID,
  clientSecret: process.env.BC_CLIENT_SECRET,
  environment: process.env.BC_ENVIRONMENT || "Production",
  defaultCompany: process.env.BC_DEFAULT_COMPANY || "",
  apiRoute: process.env.BC_API_ROUTE || "v2.0",
};

const SCOPE = "https://api.businesscentral.dynamics.com/.default";
const apiBase = () =>
  `https://api.businesscentral.dynamics.com/v2.0/${CFG.tenantId}/${encodeURIComponent(
    CFG.environment
  )}/api/${CFG.apiRoute}`;

function assertConfigured() {
  const missing = [];
  if (!CFG.tenantId) missing.push("BC_TENANT_ID");
  if (!CFG.clientId) missing.push("BC_CLIENT_ID");
  if (!CFG.clientSecret) missing.push("BC_CLIENT_SECRET");
  if (missing.length) {
    throw new Error(
      `Business Central 尚未設定，缺少環境變數: ${missing.join(", ")}。` +
        ` 請參考 bc-mcp/.env.example 建立 .env。`
    );
  }
}

// ---------------------------------------------------------------------------
// OAuth token (cached until ~60s before expiry)
// ---------------------------------------------------------------------------
let tokenCache = { value: null, expiresAt: 0 };

async function getToken() {
  assertConfigured();
  const now = Date.now();
  if (tokenCache.value && now < tokenCache.expiresAt) return tokenCache.value;

  const url = `https://login.microsoftonline.com/${CFG.tenantId}/oauth2/v2.0/token`;
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: CFG.clientId,
    client_secret: CFG.clientSecret,
    scope: SCOPE,
  });

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`取得 token 失敗 (HTTP ${res.status}): ${text}`);
  }
  const json = await res.json();
  tokenCache = {
    value: json.access_token,
    expiresAt: now + (json.expires_in - 60) * 1000,
  };
  return tokenCache.value;
}

// ---------------------------------------------------------------------------
// Authenticated request against the BC API. `path` is relative to the API base.
// ---------------------------------------------------------------------------
async function bcRequest(path, { method = "GET", query, jsonBody } = {}) {
  const token = await getToken();
  let url = path.startsWith("http") ? path : `${apiBase()}/${path.replace(/^\/+/, "")}`;
  if (query && Object.keys(query).length) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      qs.set(k.startsWith("$") ? k : `$${k}`, String(v));
    }
    const sep = url.includes("?") ? "&" : "?";
    if ([...qs].length) url += sep + qs.toString();
  }

  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(jsonBody ? { "Content-Type": "application/json" } : {}),
    },
    body: jsonBody ? JSON.stringify(jsonBody) : undefined,
  });

  const text = await res.text();
  if (!res.ok) {
    throw new Error(`BC API ${method} ${url}\nHTTP ${res.status}: ${text}`);
  }
  return text ? JSON.parse(text) : {};
}

// Resolve a company name to its id (caches the company list for the process).
let companyCache = null;
async function getCompanies() {
  if (companyCache) return companyCache;
  const data = await bcRequest("companies");
  companyCache = data.value || [];
  return companyCache;
}

async function resolveCompanyId(nameOrId) {
  const target = nameOrId || CFG.defaultCompany;
  const companies = await getCompanies();
  if (!companies.length) throw new Error("這個環境找不到任何公司。");
  if (!target) {
    if (companies.length === 1) return companies[0].id;
    const names = companies.map((c) => `"${c.name}"`).join(", ");
    throw new Error(
      `有多家公司，請指定 company。可用: ${names}（或在 .env 設定 BC_DEFAULT_COMPANY）。`
    );
  }
  const hit = companies.find(
    (c) => c.id === target || c.name?.toLowerCase() === String(target).toLowerCase()
  );
  if (!hit) {
    const names = companies.map((c) => `"${c.name}"`).join(", ");
    throw new Error(`找不到公司 "${target}"。可用: ${names}`);
  }
  return hit.id;
}

const ok = (data) => ({
  content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
});
const fail = (e) => ({
  content: [{ type: "text", text: `錯誤: ${e?.message || String(e)}` }],
  isError: true,
});

// ---------------------------------------------------------------------------
// MCP server + tools
// ---------------------------------------------------------------------------
const server = new McpServer({ name: "business-central", version: "1.0.0" });

server.registerTool(
  "bc_check_connection",
  {
    title: "檢查 BC 連線",
    description:
      "驗證 Business Central 設定與認證是否正常，並回傳目前環境可存取的公司清單。連線前先用這個確認。",
    inputSchema: {},
  },
  async () => {
    try {
      assertConfigured();
      const companies = await getCompanies();
      return ok({
        status: "connected",
        environment: CFG.environment,
        apiBase: apiBase(),
        companyCount: companies.length,
        companies: companies.map((c) => ({ id: c.id, name: c.name })),
      });
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "bc_list_companies",
  {
    title: "列出公司",
    description: "列出此 Business Central 環境中所有可存取的公司（含 id 與名稱）。",
    inputSchema: {},
  },
  async () => {
    try {
      const companies = await getCompanies();
      return ok(companies.map((c) => ({ id: c.id, name: c.name, displayName: c.displayName })));
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "bc_query",
  {
    title: "查詢 BC 資料",
    description:
      "查詢某家公司底下的 BC 標準 API 實體（entity set）。常見 entity：customers、vendors、items、salesOrders、salesInvoices、purchaseOrders、generalLedgerEntries、accounts、employees、bankAccounts 等。支援 OData 參數做篩選、排序、欄位挑選與分頁。",
    inputSchema: {
      entity: z
        .string()
        .describe("實體名稱，例如 customers、items、salesOrders"),
      company: z
        .string()
        .optional()
        .describe("公司名稱或 id；省略時使用 BC_DEFAULT_COMPANY 或唯一公司"),
      filter: z
        .string()
        .optional()
        .describe('OData $filter，例如 "number eq \'C00010\'" 或 "totalAmountIncludingTax gt 1000"'),
      select: z.string().optional().describe("OData $select，逗號分隔的欄位，例如 number,displayName"),
      orderby: z.string().optional().describe("OData $orderby，例如 number desc"),
      top: z.number().int().positive().max(1000).optional().describe("最多回傳幾筆（預設 BC 端決定）"),
      skip: z.number().int().nonnegative().optional().describe("跳過幾筆，用於分頁"),
      expand: z.string().optional().describe("OData $expand，展開關聯資料"),
    },
  },
  async ({ entity, company, filter, select, orderby, top, skip, expand }) => {
    try {
      const companyId = await resolveCompanyId(company);
      const data = await bcRequest(`companies(${companyId})/${entity}`, {
        query: { filter, select, orderby, top, skip, expand },
      });
      return ok(data);
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "bc_get",
  {
    title: "依 id 取得單筆",
    description: "依 id 取得某公司底下某實體的單一筆資料。",
    inputSchema: {
      entity: z.string().describe("實體名稱，例如 customers"),
      id: z.string().describe("該筆資料的 GUID id"),
      company: z.string().optional().describe("公司名稱或 id"),
      expand: z.string().optional().describe("OData $expand"),
    },
  },
  async ({ entity, id, company, expand }) => {
    try {
      const companyId = await resolveCompanyId(company);
      const data = await bcRequest(`companies(${companyId})/${entity}(${id})`, {
        query: { expand },
      });
      return ok(data);
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "bc_list_entities",
  {
    title: "列出可用實體",
    description:
      "從 BC API 的 metadata 讀出此環境/路由下所有可查詢的 entity set 名稱，方便知道有哪些資料可以抓。",
    inputSchema: {},
  },
  async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${apiBase()}/$metadata`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/xml" },
      });
      const xml = await res.text();
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${xml}`);
      const sets = [...xml.matchAll(/<EntitySet\s+Name="([^"]+)"/g)].map((m) => m[1]);
      return ok([...new Set(sets)].sort());
    } catch (e) {
      return fail(e);
    }
  }
);

server.registerTool(
  "bc_raw",
  {
    title: "原始 API 呼叫",
    description:
      "對 BC API 做進階呼叫：傳入相對於 API base 的路徑（或完整 https URL）。適合自訂 API page、特殊 OData 查詢，或標準工具未涵蓋的情況。預設 GET。",
    inputSchema: {
      path: z
        .string()
        .describe('相對路徑，例如 "companies" 或 "companies(<id>)/customers"，也可給完整 URL'),
      method: z.enum(["GET", "POST", "PATCH", "DELETE"]).optional().describe("HTTP 方法，預設 GET"),
      body: z.record(z.any()).optional().describe("JSON body（POST/PATCH 用）"),
    },
  },
  async ({ path, method = "GET", body }) => {
    try {
      const data = await bcRequest(path, { method, jsonBody: body });
      return ok(data);
    } catch (e) {
      return fail(e);
    }
  }
);

// ---------------------------------------------------------------------------
const transport = new StdioServerTransport();
await server.connect(transport);
console.error("[bc-mcp] Business Central MCP server 已啟動 (stdio)");
