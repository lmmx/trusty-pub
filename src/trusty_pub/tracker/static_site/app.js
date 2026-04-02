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
          v === "tp" ? "🟢 trusted" : v === "notp" ? "🔴 missing" : "🟡 unknown"
        }</span>`)
      },
      { name: "Tracked", width: "80px",
        formatter: v => v ? gridjs.html(`<span class="tk">✓</span>`) : ""
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

const toRow = p => [p.rank, p.name, p.verdict, p.issues.length > 0, p.gh || ""];

function refresh() {
  grid.updateConfig({ data: filtered().map(toRow) }).forceRender();
  stats();
}

function stats() {
  const f = filtered();
  const tr = ALL.filter(p => p.issues.length > 0);
  const ni = tr.reduce((n, p) => n + p.issues.length, 0);
  $("#stats").textContent =
    `${tr.length} repos tracked · ${ni} issues · ` +
    `${f.length} shown of ${ALL.length} packages`;
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
