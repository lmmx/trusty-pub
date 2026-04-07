/* 🔐 Trusty Pub — GitHub OAuth via Cloudflare Worker
 *
 * Handles login, token exchange, user display, and logout.
 * Exposes window.auth for use by app.js.
 */

const AUTH_CONFIG = {
  clientId: "Ov23liKcJGsVMGZpnbbs",
  worker: "https://trusty-pub-auth.louismmx.workers.dev",
  redirectUri: window.location.origin + "/trusty-pub",
  scope: "public_repo",
};

const auth = {
  getToken() {
    return sessionStorage.getItem("gh_token");
  },

  isLoggedIn() {
    return !!this.getToken();
  },

  login() {
    const state = crypto.randomUUID();
    sessionStorage.setItem("oauth_state", state);

    const params = new URLSearchParams({
      client_id: AUTH_CONFIG.clientId,
      redirect_uri: AUTH_CONFIG.redirectUri,
      scope: AUTH_CONFIG.scope,
      state,
    });

    window.location.href = `https://github.com/login/oauth/authorize?${params}`;
  },

  logout() {
    sessionStorage.removeItem("gh_token");
    sessionStorage.removeItem("gh_user");
    this.renderUI();
  },

  async handleCallback() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (!code) return false;

    const savedState = sessionStorage.getItem("oauth_state");
    sessionStorage.removeItem("oauth_state");

    if (state !== savedState) {
      console.error("State mismatch — possible CSRF");
      return false;
    }

    const res = await fetch(`${AUTH_CONFIG.worker}/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });

    const data = await res.json();

    if (data.access_token) {
      sessionStorage.setItem("gh_token", data.access_token);
      window.history.replaceState({}, "", AUTH_CONFIG.redirectUri);
      await this.fetchUser();
      return true;
    } else {
      console.error("Token exchange failed:", data);
      return false;
    }
  },

  async fetchUser() {
    const token = this.getToken();
    if (!token) return null;

    const cached = sessionStorage.getItem("gh_user");
    if (cached) return JSON.parse(cached);

    try {
      const res = await fetch("https://api.github.com/user", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(res.status);
      const user = await res.json();
      const info = { login: user.login, avatar: user.avatar_url };
      sessionStorage.setItem("gh_user", JSON.stringify(info));
      return info;
    } catch (e) {
      console.error("Failed to fetch user:", e);
      this.logout();
      return null;
    }
  },

  renderUI() {
    const container = document.getElementById("auth");
    if (!container) return;

    if (!this.isLoggedIn()) {
      container.innerHTML = `<button id="login-btn" class="auth-btn">
        <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
        </svg>
        Admin login
      </button>`;
      document.getElementById("login-btn").onclick = () => this.login();
      return;
    }

    const cached = sessionStorage.getItem("gh_user");
    const user = cached ? JSON.parse(cached) : null;

    if (user) {
      container.innerHTML = `<div class="auth-user">
        <img src="${user.avatar}" alt="${user.login}" class="auth-avatar">
        <span class="auth-name">${user.login}</span>
        <button id="logout-btn" class="auth-btn auth-btn-small">Sign out</button>
      </div>`;
    } else {
      container.innerHTML = `<div class="auth-user">
        <span class="auth-name">Signed in</span>
        <button id="logout-btn" class="auth-btn auth-btn-small">Sign out</button>
      </div>`;
    }

    document.getElementById("logout-btn").onclick = () => this.logout();

    const trackSection = document.getElementById("track-section");
    if (trackSection) trackSection.hidden = !this.isLoggedIn();
  },

  async init() {
    const didAuth = await this.handleCallback();
    if (!didAuth && this.isLoggedIn()) {
      await this.fetchUser();
    }
    this.renderUI();
  },
};

window.auth = auth;
auth.init();
