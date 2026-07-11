// 管理画面共通のJavaScriptユーティリティ。
//
// - APIRunのベースURLとセッショントークンをlocalStorageで管理する。
// - fetch()のラッパー（Authorizationヘッダーの自動付与、401時のログイン画面への
//   リダイレクト）を提供する。
// - すべての管理画面ページ（dashboard.html, resources.html, requests.html,
//   stats.html, users.html）から読み込む共通スクリプト。

const ADMIN_BASE_URL_KEY = "admin_api_base_url";
const ADMIN_SESSION_TOKEN_KEY = "admin_session_token";
const ADMIN_DISPLAY_NAME_KEY = "admin_display_name";

function getApiBaseUrl() {
  return localStorage.getItem(ADMIN_BASE_URL_KEY) || "";
}

function setApiBaseUrl(url) {
  localStorage.setItem(ADMIN_BASE_URL_KEY, url.replace(/\/$/, ""));
}

function getSessionToken() {
  return localStorage.getItem(ADMIN_SESSION_TOKEN_KEY) || "";
}

function setSessionToken(token) {
  localStorage.setItem(ADMIN_SESSION_TOKEN_KEY, token);
}

function clearSession() {
  localStorage.removeItem(ADMIN_SESSION_TOKEN_KEY);
  localStorage.removeItem(ADMIN_DISPLAY_NAME_KEY);
}

function getDisplayName() {
  return localStorage.getItem(ADMIN_DISPLAY_NAME_KEY) || "";
}

function setDisplayName(name) {
  localStorage.setItem(ADMIN_DISPLAY_NAME_KEY, name);
}

// ログイン済みであることを要求するページの先頭で呼び出す。
// ベースURL・トークンが無い場合はログイン画面に戻す。
function requireLogin() {
  if (!getApiBaseUrl() || !getSessionToken()) {
    window.location.href = "index.html";
  }
}

// 管理API呼び出しの共通ラッパー。
// 401が返った場合はセッションを破棄してログイン画面に戻す。
async function adminFetch(path, options = {}) {
  const baseUrl = getApiBaseUrl();
  const token = getSessionToken();
  const headers = Object.assign({}, options.headers || {}, {
    Authorization: `Bearer ${token}`,
  });
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(baseUrl + path, Object.assign({}, options, { headers }));

  if (res.status === 401) {
    clearSession();
    window.location.href = "index.html";
    throw new Error("ログインが必要です");
  }
  return res;
}

async function adminLogout() {
  try {
    await adminFetch("/admin/auth/logout", { method: "POST" });
  } catch (e) {
    // ログアウトAPI呼び出し失敗時も、ローカルのセッション情報は消す。
  }
  clearSession();
  window.location.href = "index.html";
}

// ナビゲーションバーをページ上部に挿入する共通関数。
function renderAdminNav(activePage) {
  const nav = document.createElement("nav");
  nav.className = "admin-nav";
  const links = [
    { href: "dashboard.html", label: "ダッシュボード", key: "dashboard" },
    { href: "resources.html", label: "データ更新", key: "resources" },
    { href: "requests.html", label: "更新依頼", key: "requests" },
    { href: "stats.html", label: "統計情報", key: "stats" },
    { href: "users.html", label: "管理ユーザー", key: "users" },
  ];
  nav.innerHTML =
    `<div class="admin-nav-brand">いぬきんじょ管理画面</div>` +
    `<div class="admin-nav-links">` +
    links
      .map(
        (l) =>
          `<a href="${l.href}" class="${l.key === activePage ? "active" : ""}">${l.label}</a>`
      )
      .join("") +
    `</div>` +
    `<div class="admin-nav-user">${getDisplayName()} さん ` +
    `<button id="admin-logout-btn">ログアウト</button></div>`;
  document.body.prepend(nav);
  document.getElementById("admin-logout-btn").addEventListener("click", adminLogout);
}
