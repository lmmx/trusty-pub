/* 🔗 Trusty Pub — issue tracking via GitHub Contents API
 *
 * Commits TOML files to data/tracker/repos/{owner}__{repo}/{number}.toml
 * Requires auth.js (for auth.getToken()) and app.js (for ALL, refresh).
 */

const TRACK = {
  repo: "lmmx/trusty-pub",
  basePath: "data/tracker/repos",
  keywords: ["trusted publishing", "trusted publisher", "OIDC publish"],
  issueRe: /^https:\/\/github\.com\/([a-zA-Z0-9._-]+)\/([a-zA-Z0-9._-]+)\/issues\/(\d+)$/,
};

function toBase64(str) {
  const bytes = new TextEncoder().encode(str);
  return btoa(Array.from(bytes, b => String.fromCodePoint(b)).join(""));
}

function escToml(s) {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");
}

function detectKeyword(title) {
  const lower = title.toLowerCase();
  for (const kw of TRACK.keywords) {
    if (lower.includes(kw.toLowerCase())) return kw;
  }
  return "";
}

function buildToml(issueUrl, title, state, keyword) {
  const now = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  return [
    `issue_url = "${escToml(issueUrl)}"`,
    `title = "${escToml(title)}"`,
    `state = "${escToml(state)}"`,
    `keyword = "${escToml(keyword)}"`,
    `tracked_at = "${now}"`,
  ].join("\n") + "\n";
}

async function trackIssueUrl(url) {
  const result = document.getElementById("track-result");
  const show = (html, err) => {
    result.className = err ? "error" : "flash";
    result.innerHTML = html;
    result.hidden = false;
  };

  const token = auth.getToken();
  if (!token) { show("Sign in with GitHub first.", true); return; }

  const m = url.trim().match(TRACK.issueRe);
  if (!m) { show("Not a valid GitHub issue URL (expected https://github.com/owner/repo/issues/123).", true); return; }

  const [, owner, repo, numStr] = m;
  const number = parseInt(numStr, 10);
  const slug = `${owner}__${repo}`;

  show("Fetching issue metadata…");

  try {
    // 1. fetch issue metadata from GitHub API
    const issueRes = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/issues/${number}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (!issueRes.ok) throw new Error(`GitHub API error ${issueRes.status}`);
    const issue = await issueRes.json();

    const title = issue.title;
    const state = issue.state.toUpperCase();
    const issueUrl = issue.html_url;
    const keyword = detectKeyword(title);

    // 2. build TOML
    const toml = buildToml(issueUrl, title, state, keyword);
    const path = `${TRACK.basePath}/${slug}/${number}.toml`;

    // 3. check if file already exists (need SHA for updates)
    show("Committing…");
    let sha;
    const existing = await fetch(
      `https://api.github.com/repos/${TRACK.repo}/contents/${path}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (existing.ok) {
      sha = (await existing.json()).sha;
    }

    // 4. commit the file
    const putRes = await fetch(
      `https://api.github.com/repos/${TRACK.repo}/contents/${path}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: `Track issue ${number} in ${owner}/${repo}`,
          content: toBase64(toml),
          ...(sha && { sha }),
        }),
      }
    );
    if (!putRes.ok) {
      const err = await putRes.json();
      throw new Error(err.message || `Commit failed (${putRes.status})`);
    }

    // 5. update local data so the grid reflects it immediately
    const ghUrl = `https://github.com/${owner}/${repo}`;
    const entry = [number, title, state, keyword, issueUrl];
    for (const pkg of ALL) {
      if (pkg.gh === ghUrl && !pkg.issues.some(i => i[0] === number)) {
        pkg.issues.push(entry);
      }
    }
    if (typeof refresh === "function") refresh();

    show(
      `Tracked <a href="${issueUrl}" target="_blank">${owner}/${repo}#${number}</a>` +
      ` — ${title}` +
      (keyword ? ` <span class="kw">${keyword}</span>` : ""),
      false
    );

    document.getElementById("track-url-input").value = "";

  } catch (e) {
    show(e.message, true);
  }
}

// wire up form
document.getElementById("track-form").addEventListener("submit", function (e) {
  e.preventDefault();
  const input = document.getElementById("track-url-input");
  if (input.value.trim()) trackIssueUrl(input.value.trim());
});
