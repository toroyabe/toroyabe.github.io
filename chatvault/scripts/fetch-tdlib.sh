#!/usr/bin/env bash
#
# fetch-tdlib.sh
#
# 下載並校驗 TDLibFramework.xcframework（約 333MB），解壓到本機 ThirdParty 目錄。
# 此二進位不進 git；clone 後在 Mac 上跑此腳本還原。
#
# 用法：
#   bash chatvault/scripts/fetch-tdlib.sh
#
# 注意：
# - 這支腳本在 Linux 雲端環境「未經實際執行驗證」。請在 Mac 上首次執行時確認下列
#   兩個變數是否正確：
#     1) TDLIB_URL  —— 下載來源 URL（spike 當時是手動 curl 成功的那個來源）
#     2) EXPECTED_SHA256 —— 已驗證相符的 checksum
# - spike 已驗證的 checksum 為 0929...6830（見下方）。URL 請依你 spike 實際使用的填入。

set -euo pipefail

# ---- 可調設定 ----------------------------------------------------------------

# TODO(Mac): 填入 spike 當時 curl 成功的實際下載 URL。
# 留空會讓腳本停下並提示，避免抓到錯誤來源。
TDLIB_URL="${TDLIB_URL:-}"

# spike 已驗證相符的 checksum（請勿隨意更動；這是守門員）。
EXPECTED_SHA256="0929dbd7d79ca301b60612431aa4e811c946110e4f8439e41ae1b7410436b830"

# 解壓目的地（依計畫第 5 節）。
DEST_DIR="${DEST_DIR:-ThirdParty/TDLibFrameworkLocal}"

# 下載暫存檔。
ZIP_PATH="${ZIP_PATH:-TDLibFramework.zip}"

# ---- 前置檢查 ----------------------------------------------------------------

if [[ -z "${TDLIB_URL}" ]]; then
  echo "ERROR: TDLIB_URL 尚未設定。" >&2
  echo "請編輯本腳本填入 spike 當時 curl 成功的下載 URL，或用環境變數覆寫：" >&2
  echo "  TDLIB_URL='https://...' bash chatvault/scripts/fetch-tdlib.sh" >&2
  exit 1
fi

# 選擇可用的 sha256 工具（macOS: shasum -a 256；Linux: sha256sum）。
sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    echo "ERROR: 找不到 shasum 或 sha256sum。" >&2
    exit 1
  fi
}

# ---- 若已存在且 checksum 相符，直接略過 --------------------------------------

if [[ -f "${ZIP_PATH}" ]]; then
  echo "偵測到既有 ${ZIP_PATH}，校驗中..."
  ACTUAL="$(sha256_of "${ZIP_PATH}")"
  if [[ "${ACTUAL}" == "${EXPECTED_SHA256}" ]]; then
    echo "既有檔案 checksum 相符，略過下載。"
  else
    echo "既有檔案 checksum 不符，重新下載。"
    rm -f "${ZIP_PATH}"
  fi
fi

# ---- 下載 --------------------------------------------------------------------

if [[ ! -f "${ZIP_PATH}" ]]; then
  echo "下載 TDLibFramework（約 333MB）自：${TDLIB_URL}"
  # -L 跟隨重導向；--fail 在 HTTP 錯誤時非零退出；-o 輸出檔。
  curl -L --fail -o "${ZIP_PATH}" "${TDLIB_URL}"
fi

# ---- 校驗 --------------------------------------------------------------------

echo "校驗 checksum..."
ACTUAL="$(sha256_of "${ZIP_PATH}")"
if [[ "${ACTUAL}" != "${EXPECTED_SHA256}" ]]; then
  echo "ERROR: checksum 不符！" >&2
  echo "  expected: ${EXPECTED_SHA256}" >&2
  echo "  actual:   ${ACTUAL}" >&2
  echo "為安全起見不解壓。請確認下載來源。" >&2
  exit 1
fi
echo "checksum 相符：${ACTUAL}"

# ---- 解壓 --------------------------------------------------------------------

echo "解壓到 ${DEST_DIR} ..."
mkdir -p "${DEST_DIR}"
# -o 覆寫、-q 安靜。
unzip -o -q "${ZIP_PATH}" -d "${DEST_DIR}"

echo "完成。TDLibFramework 已還原到：${DEST_DIR}"
echo "（提醒：此 xcframework 已被 .gitignore 排除，不會進 git。）"
