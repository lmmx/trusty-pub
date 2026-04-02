/* 🛡️ Trusty Pub — static frontend
 *
 * data.json row: [rank, name, verdict, ?github_url, ?issues]
 * issues:        [[number, title, state, keyword, url], ...]
 */

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

const parse = r => ({
  rank: r[0], name: r[1], verdict: r[2],
  gh: r[3] || null, issues: r[4] || [],
});

let ALL = [];
let grid;

// ── tabs ──

$$(".tab").forEach(btn => {
  btn.onclick = () => {
    $$(".tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const id = btn.dataset.tab;
    $$("#tab-tracker, #tab-resources").forEach(s => s.hidden = true);
    $(`#tab-${id}`).hidden = false;
  };
});

// ── tracker ──

async function init() {
  const raw = await (await fetch("data.json")).json();
  ALL = raw.map(parse);

  grid = new gridjs.Grid({
    columns: [
      { name: "Rank", width: "65px" },
      { name: "Package", formatter: (_, row) => {
        const name = row.cells[1].data, gh = row.cells[4].data;
        return gh
          ? gridjs.html(`<a href="${gh}" target="_blank">${name}</a>`)
          : name;
      }},
      { name: "Status", width: "95px", formatter: v =>
        gridjs.html(`<span class="badge badge-${v}">${
          v === "tp" ? "Trusted" : v === "notp" ? "Missing" : "Unknown"
        }</span>`)
      },
      { name: "Tracking Issue", width: "120px",
        formatter: (v) => v
          ? gridjs.html(`<a href="${v}" target="_blank" title="View tracking issue on GitHub"><svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:text-bottom"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg></a>`)
          : ""
      },
      { name: "gh", hidden: true },
    ],
    data: () => filtered().map(toRow),
    search: true,
    sort: true,
    pagination: { limit: 50 },
  }).render($("#table"));

  $("#show-tp").onchange = refresh;
  $("#show-notp").onchange = refresh;
  $("#tracked-only").onchange = refresh;

  $("#table").addEventListener("click", e => {
    const tr = e.target.closest("tr.gridjs-tr");
    if (!tr) return;
    const name = tr.querySelector("td:nth-child(2)")?.textContent?.trim();
    if (name) showDetail(name);
  });

  stats();
  loadResources();
}

const filtered = () => {
  const tp = $("#show-tp").checked;
  const notp = $("#show-notp").checked;
  const to = $("#tracked-only").checked;
  return ALL.filter(p =>
    (p.verdict === "tp" ? tp : p.verdict === "notp" ? notp : true) &&
    (!to || p.issues.length > 0)
  );
};

const toRow = (p) => [
  p.rank, p.name, p.verdict,
  p.issues.length > 0 ? p.issues[0][4] : null,
  p.gh || "",
];

function refresh() {
  grid.updateConfig({ data: filtered().map(toRow) }).forceRender();
  stats();
}

function stats() {
  const f = filtered();

  const repoIssues = new Map();
  for (const p of ALL) {
    if (p.gh && p.issues.length > 0 && !repoIssues.has(p.gh)) {
      repoIssues.set(p.gh, p.issues);
    }
  }
  const ni = [...repoIssues.values()].reduce((n, iss) => n + iss.length, 0);
  const covered = ALL.filter(p => p.issues.length > 0).length;
  const tp = ALL.filter(p => p.verdict === "tp").length;
  const notp = ALL.filter(p => p.verdict === "notp").length;

  $("#stats").textContent =
    `${ni} issues tracked in ${repoIssues.size} repos · ` +
    `${covered} packages covered of ${ALL.length} total ` +
    `(${tp} trusted, ${notp} missing)`;
}

function showDetail(name) {
  const pkg = ALL.find(p => p.name === name);
  if (!pkg?.issues.length) { $("#detail").innerHTML = ""; return; }

  const repo = pkg.gh?.replace("https://github.com/", "") ?? name;
  const html = pkg.issues.map(([num, title, state, kw, url]) => `
    <div class="issue">
      <a href="${url}" target="_blank">#${num}</a>
      <span style="flex:1">${title}</span>
      <span class="st st-${state}">${state}</span>
      ${kw ? `<span class="kw">${kw}</span>` : ""}
    </div>`).join("");

  $("#detail").innerHTML = `
    <h2>${repo}</h2>
    <a href="${pkg.gh}" target="_blank">${pkg.gh}</a>
    <h3 style="margin:.75rem 0 .25rem;color:#444">Tracked issues (${pkg.issues.length})</h3>
    ${html}`;
}

// ── resources ──

async function loadResources() {
  const res = await (await fetch("resources.json")).json();
  const groups = {};
  res.forEach(r => {
    (groups[r.type] = groups[r.type] || []).push(r);
  });

  const labels = {
    incident: "Incident Reports",
    blog: "Blog Posts & Guides",
    docs: "Documentation",
    howto: "How-To",
  };

  $("#resources").innerHTML = Object.entries(groups).map(([type, items]) => `
    <div class="res-section">
      <h2>${labels[type] || type}</h2>
      ${items.map(i => `
        <div class="res-item">
          <a href="${i.url}" target="_blank">${i.title}</a>
          <span class="res-tag">${i.type}</span>
          ${i.packages ? i.packages.map(p =>
            `<span class="res-tag">${p}</span>`).join("") : ""}
          ${i.desc ? `<div class="res-desc">${i.desc}</div>` : ""}
        </div>`).join("")}
    </div>`).join("");
}

init();
