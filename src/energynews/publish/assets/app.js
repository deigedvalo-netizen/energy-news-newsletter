(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const plural = (n, one, many) => `${n} ${Number(n) === 1 ? one : many}`;
  const params = new URLSearchParams(location.search);
  const feedPath = /^archive\/\d{4}-W\d{2}\/feed\.json$/.test(params.get("feed") || "") ? params.get("feed") : "feed.json";
  const live = feedPath === "feed.json";
  let data, trends = [], issues = { issues: [] }, analyses = { issues: [] }, analysis = null, archives = { weeks: [] }, current = null;

  const get = async (p, fallback) => {
    try { const r = await fetch(p, { cache: "no-cache" }); return r.ok ? await r.json() : fallback; } catch { return fallback; }
  };
  const published = (m) => m.issues.filter((i) => i.status === "PUBLISHED" || i.status === "PUBLISHED_WITH_WARNINGS").sort((a, b) => b.date.localeCompare(a.date));
  const labelOf = (c) => (data.tabs.find((t) => t.commodity === c) || {}).label || c;
  const analysisFresh = () => analysis && (Date.now() - Date.parse(analysis.data_as_of)) / 36e5 <= (data.analysis_max_age_hours || 36);
  const warnNote = (entry) => entry && entry.status === "PUBLISHED_WITH_WARNINGS"
    ? `<p class="warnnote">Contains figures not machine-verified against the collected data (${esc(entry.warnings.filter((w) => w.code === "UNVERIFIED_NUMBER").map((w) => w.detail).join(", ") || "see notes")}).</p>` : "";

  function trendCard(v, compact) {
    const tl = (v.timeline || []).slice(0, compact ? 4 : 50);
    return `<article class="card">
      <div class="trend-head"><span class="badge ${esc(v.trajectory)}">${esc(v.trajectory)}</span><span class="badge ${esc(v.status)}">${esc(v.status)}</span>
        <h3>${esc(v.name)}</h3></div>
      <p>${esc(v.thesis)}</p>
      <p class="companies"><strong>Companies pushing it:</strong> ${esc(v.companies.join(", ") || "none verified yet")}</p>
      <p class="counts">${esc(plural(v.companies_current, "company", "companies"))} this week vs ${esc(v.companies_previous)} last week · ${esc(plural(v.mentions_current, "mention", "mentions"))} vs ${esc(v.mentions_previous)} · hotness ${esc(v.hotness)} · ${v.commodities.map((c) => `<span class="chip">${esc(labelOf(c))}</span>`).join(" ")}
        ${v.only_company_releases ? ' · <span class="flag">COMPANY RELEASES ONLY</span>' : ""}</p>
      <details><summary>Evidence timeline (${esc(v.timeline.length)})</summary><ul class="timeline">
        ${tl.map((m) => `<li class="${m.verified ? "" : "unv"}">${esc(m.date)} — <strong>${esc(m.company)}</strong>: ${esc(m.action)} · <a href="${esc(safeUrl(m.story_url))}" rel="noopener">${esc(m.outlet || "story")}</a>${m.verified ? "" : ` (${esc(m.reason || "unverified")}, not counted)`}</li>`).join("")}
      </ul><p class="counts">Trajectory compares verified companies in the last 7 days with the 7 days before. Confirmed = 2+ verified companies in 30 days.</p></details>
    </article>`;
  }

  function itemHtml(i) {
    return `<article class="item">
      <time datetime="${esc(i.first_published_at)}">${esc(i.published_local)}</time>
      <div>
        <h3><a href="${esc(safeUrl(i.sources[0]?.url))}" rel="noopener">${esc(i.title)}</a></h3>
        ${i.summary && i.summary !== i.title ? `<p>${esc(i.summary)}</p>` : ""}
        <p class="meta">${i.commodities.map((c) => `<span class="chip">${esc(labelOf(c))}</span>`).join(" ")} <span class="chip">${esc(i.topic_label)}</span>
          · ${esc(plural(i.distinct_source_count, "source", "sources"))} · best tier ${esc(i.best_tier)} · relevance ${esc(i.relevance)}
          ${(i.flags || []).map((f) => ` <span class="flag">${esc(f)}</span>`).join("")}</p>
        ${i.organizations.length ? `<p class="meta">${esc(i.organizations.map((o) => o.name).join(", "))}</p>` : ""}
        <details><summary>${esc(plural(i.sources.length, "source link", "source links"))}${i.figures.length ? " and figures" : ""}</summary><ul>
          ${i.sources.map((s) => `<li><a href="${esc(safeUrl(s.url))}" rel="noopener">${esc(s.title)}</a> — ${esc(s.outlet)} (tier ${esc(s.tier)}, ${esc(s.source_type)}), ${esc(s.published_local)}</li>`).join("")}
          ${i.figures.map((f) => `<li>“${esc(f.span)}” — ${esc(f.outlet)}</li>`).join("")}
        </ul></details>
      </div></article>`;
  }

  function feedList(items) {
    const box = document.createElement("section");
    box.className = "card";
    if (!items.length) { box.innerHTML = `<p class="empty">No qualifying news in the last ${esc(data.window_days)} days.</p>`; return box; }
    const list = document.createElement("div"), sentinel = document.createElement("div");
    sentinel.id = "sentinel"; box.append(list, sentinel);
    let shown = 0;
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && more(), { rootMargin: "600px" });
    const more = () => {
      const next = items.slice(shown, shown + data.page_size);
      list.insertAdjacentHTML("beforeend", next.map(itemHtml).join(""));
      shown += next.length;
      if (shown >= items.length) io.disconnect();
    };
    more(); io.observe(sentinel);
    return box;
  }

  function pinned(key) {
    const syn = key === "overall" ? data.synopsis.overall : data.synopsis.commodities[key];
    if (analysisFresh() && analysis.sections?.[key]) {
      return `<article class="card pinned"><div class="kicker">Analysis · What this means for energy traders</div><div class="md">${analysis.sections[key]}</div>
        <p class="meta">Written by Claude from the ${esc(analysis.date)} digest and checked by the validator. <a href="#analysis">Full analysis</a></p></article>`;
    }
    return syn ? `<article class="card pinned"><div class="kicker">Automated synopsis · data only</div><ul class="syn">${syn.sentences.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      <p class="meta">Today's written analysis isn't published yet.</p></article>` : "";
  }

  async function renderDoc(kind) {
    const main = $("#main"); main.innerHTML = "";
    const man = kind === "newsletter" ? issues : analyses;
    const dir = kind === "newsletter" ? "issues" : "analysis";
    const pub = published(man);
    const want = (location.hash.match(new RegExp(`^#${kind}/(\\d{4}-\\d{2}-\\d{2})$`)) || [])[1];
    const pick = pub.find((i) => i.date === want) || pub[0];
    if (!pick) {
      main.innerHTML = `<div class="card"><p class="empty">No ${kind === "newsletter" ? "newsletter" : "written analysis"} has been published yet.</p></div>`;
      if (kind === "analysis" && data.synopsis) main.insertAdjacentHTML("beforeend", pinned("overall"));
      return;
    }
    const r = await fetch(`${dir}/${pick.date}.html`, { cache: "no-cache" });
    const wrap = document.createElement("article"); wrap.className = "issue";
    wrap.innerHTML = warnNote(pick) + (r.ok ? await r.text() : `<p class="empty">Could not load.</p>`);
    main.append(wrap);
    if (kind === "analysis" && data.synopsis) {
      main.insertAdjacentHTML("beforeend", `<h2>Automated synopsis · data only · ${esc(data.data_as_of_local)}</h2><div class="card"><ul class="syn">${data.synopsis.overall.sentences.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>${
        Object.values(data.synopsis.commodities).map((c) => `<h3 class="subhead">${esc(c.label)}</h3><ul class="syn">${c.sentences.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`).join("")}</div>`);
    }
    main.insertAdjacentHTML("beforeend", `<h2>Past ${kind === "newsletter" ? "newsletters" : "analyses"}</h2><div class="card"><ul>${pub.map((i) => `<li><a href="#${kind}/${esc(i.date)}">${esc(i.date)}</a></li>`).join("")}</ul></div>`
      + (kind === "newsletter" && archives.weeks.length ? `<h2>Weekly archives</h2><div class="card"><ul>${archives.weeks.map((w) => `<li><a href="?feed=archive/${esc(w)}/feed.json#all">${esc(w)}</a></li>`).join("")}</ul></div>` : ""));
  }

  function renderTrends() {
    const main = $("#main"); main.innerHTML = "";
    const visible = trends.filter((v) => v.trajectory !== "DORMANT");
    const conf = visible.filter((v) => v.status === "CONFIRMED"), emer = visible.filter((v) => v.status === "EMERGING");
    main.insertAdjacentHTML("beforeend", `<h2>Confirmed trends · 2+ companies pushing</h2>` + (conf.length ? conf.map((v) => trendCard(v)).join("") : `<div class="card"><p class="empty">No confirmed trends yet. The daily task builds the ledger as it reads the news.</p></div>`));
    if (emer.length) main.insertAdjacentHTML("beforeend", `<h2>Emerging · one company so far</h2>` + emer.map((v) => trendCard(v)).join(""));
  }

  function renderTab(tab) {
    const main = $("#main"); main.innerHTML = "";
    main.insertAdjacentHTML("beforeend", pinned(tab.id === "all" ? "overall" : tab.commodity));
    const hot = trends.filter((v) => v.status === "CONFIRMED" && v.trajectory !== "DORMANT" && (tab.id === "all" || v.commodities.includes(tab.commodity))).slice(0, 5);
    main.insertAdjacentHTML("beforeend", `<h2>Hottest trends${tab.id === "all" ? "" : ` · ${esc(tab.label)}`}</h2>` + (hot.length ? hot.map((v) => trendCard(v, true)).join("") : `<div class="card"><p class="empty">No confirmed trends${tab.id === "all" ? "" : " for this commodity"} yet.</p></div>`));
    const refs = (data.reference_links || {})[tab.commodity] || [];
    if (refs.length) main.insertAdjacentHTML("beforeend", `<h2>Further reading</h2><div class="card refs"><ul>${refs.map((r) => `<li><a href="${esc(safeUrl(r.url))}" rel="noopener">${esc(r.name)}</a><br><span class="meta">${esc(r.note)}</span></li>`).join("")}</ul></div>`);
    const items = tab.id === "all" ? data.feed : data.feed.filter((i) => i.commodities.includes(tab.commodity));
    main.insertAdjacentHTML("beforeend", `<h2>News feed · last ${esc(data.window_days)} days · newest first</h2>`);
    main.append(feedList(items));
  }

  function route() {
    const h = location.hash.replace(/^#/, "");
    const tabs = [...(live ? [{ id: "newsletter", label: "Newsletter" }, { id: "analysis", label: "Analysis" }, { id: "trends", label: "Trends" }] : []), ...data.tabs];
    const id = h.split("/")[0] || (live && published(issues).length ? "newsletter" : "all");
    const tab = tabs.find((t) => t.id === id) || tabs[0];
    if (tab.id === current && !h.includes("/")) return;
    current = tab.id;
    $("#tabs").innerHTML = tabs.map((t) => `<button role="tab" aria-selected="${t.id === tab.id}" data-id="${esc(t.id)}">${esc(t.label)}</button>`).join("");
    if (tab.id === "newsletter" || tab.id === "analysis") renderDoc(tab.id);
    else if (tab.id === "trends") renderTrends();
    else renderTab(tab);
  }

  async function init() {
    data = await get(feedPath, null);
    if (!data) { $("#main").innerHTML = `<p class="empty">The digest has not been published yet.</p>`; $("#asof").textContent = ""; return; }
    const tv = live ? await get("trends/trends.json", null) : null;
    trends = tv ? tv.trends : data.trends.all;
    if (live) {
      issues = await get("issues/manifest.json", issues);
      analyses = await get("analysis/manifest.json", analyses);
      archives = await get("archive/index.json", archives);
      const latest = published(analyses)[0];
      if (latest) analysis = await get(`analysis/${latest.date}.json`, null);
    }
    $("#asof").textContent = `${live ? "Data as of" : "Archived"} ${data.data_as_of_local}`;
    const ageH = (Date.now() - Date.parse(data.data_as_of)) / 36e5;
    if (live && ageH > data.stale_after_hours) {
      const s = $("#stale"); s.hidden = false; s.textContent = `Data may be stale: last successful update ${Math.round(ageH)} hours ago (${data.data_as_of_local}).`;
    }
    $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) location.hash = b.dataset.id; });
    addEventListener("hashchange", () => { current = null; route(); });
    route();
  }
  init();
})();
