(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const plural = (n, one, many) => `${n} ${Number(n) === 1 ? one : many}`;
  const params = new URLSearchParams(location.search);
  const feedPath = /^archive\/\d{4}-W\d{2}\/feed\.json$/.test(params.get("feed") || "") ? params.get("feed") : "feed.json";
  const live = feedPath === "feed.json";
  const TZ = "America/Chicago";
  let data, trends = [], issues = { issues: [] }, analyses = { issues: [] }, analysis = null, archives = { weeks: [] }, current = null, started = false;

  const get = async (p, fallback) => {
    try { const r = await fetch(p, { cache: "no-cache" }); return r.ok ? await r.json() : fallback; } catch { return fallback; }
  };
  const published = (m) => m.issues.filter((i) => i.status === "PUBLISHED" || i.status === "PUBLISHED_WITH_WARNINGS").sort((a, b) => b.date.localeCompare(a.date));
  const tabFor = (c) => data.tabs.find((t) => t.commodity === c) || {};
  const labelOf = (c) => tabFor(c).label || c;
  const analysisFresh = () => analysis && (Date.now() - Date.parse(analysis.data_as_of)) / 36e5 <= (data.analysis_max_age_hours || 36);
  const outletName = (s) => {
    const o = String(s?.outlet || "");
    if (/\(via |NewsData/.test(o)) { try { return new URL(s.url).hostname.replace(/^www\./, ""); } catch { /* fall through */ } }
    return o.split(" — ")[0].replace(/ \(API\)$/, "");
  };
  const longDate = (d) => new Date(d).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: TZ });
  const isoLong = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
  const clock = (d) => new Date(d).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: TZ });
  const dayShort = (d) => new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: TZ });
  function ago(d) {
    const m = Math.max(0, Math.round((Date.now() - Date.parse(d)) / 6e4));
    if (m < 60) return `${m || 1} min ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h} hr${h === 1 ? "" : "s"} ago`;
    const days = Math.round(h / 24);
    return days < 7 ? `${days} day${days === 1 ? "" : "s"} ago` : dayShort(d);
  }
  const dot = (c) => `<span class="dot c-${esc(c)}"></span>`;
  const kicker = (i) => {
    const c = i.commodities[0];
    return `<div class="kicker c-${esc(c)}">${i.commodities.map((x) => `<a href="#${esc(tabFor(x).id)}">${esc(labelOf(x))}</a>`).join(" · ")}${i.topic_label ? ` <span style="color:var(--muted)">/ ${esc(i.topic_label)}</span>` : ""}</div>`;
  };
  const byline = (i) => {
    const s = i.sources[0] || {};
    return `<div class="byline"><span class="outlet">${esc(outletName(s))}</span><time datetime="${esc(i.first_published_at)}">${esc(ago(i.first_published_at))}</time>${
      i.distinct_source_count > 1 ? `<span class="sep"></span><span>${esc(plural(i.distinct_source_count, "source", "sources"))}</span>` : ""}${
      i.best_tier === 1 ? `<span class="tier1" title="Official source or major newsroom with a corrections policy">Tier 1</span>` : ""}${
      (i.flags || []).map((f) => `<span class="flag">${esc(f)}</span>`).join("")}</div>`;
  };
  const warnNote = (entry) => entry && entry.status === "PUBLISHED_WITH_WARNINGS"
    ? `<p class="warnnote">Contains figures not machine-verified against the collected data (${esc(entry.warnings.filter((w) => w.code === "UNVERIFIED_NUMBER").map((w) => w.detail).join(", ") || "see notes")}).</p>` : "";
  const secHead = (title, more) => `<div class="sec-head"><h2>${title}</h2>${more || ""}</div>`;
  const textOf = (html) => { const d = document.createElement("div"); d.innerHTML = html || ""; return d.textContent.replace(/\s+/g, " ").trim(); };
  const clip = (s, n) => (s.length > n ? s.slice(0, s.lastIndexOf(" ", n)) + "…" : s);

  // ---------- pieces ----------
  function storyCard(i, cls = "story") {
    const url = esc(safeUrl(i.sources[0]?.url));
    const sum = i.summary && i.summary !== i.title ? `<p>${esc(i.summary)}</p>` : "";
    if (cls === "lead") {
      return `<article class="lead">${kicker(i)}<h2><a href="${url}" rel="noopener">${esc(i.title)}</a></h2>${
        sum.replace("<p>", '<p class="standfirst">')}${byline(i)}</article>`;
    }
    return `<article class="story">${kicker(i)}<h3><a href="${url}" rel="noopener">${esc(i.title)}</a></h3>${sum}${byline(i)}</article>`;
  }

  function trendCard(v, full) {
    const c = v.commodities[0];
    const tl = v.timeline || [];
    return `<article class="trend c-${esc(c)}${full ? " full" : ""}">
      <div class="badges"><span class="badge ${esc(v.trajectory)}">${esc(v.trajectory)}</span><span class="badge ${esc(v.status)}">${esc(v.status)}</span>${v.only_company_releases ? '<span class="flag">Company releases only</span>' : ""}</div>
      <h3>${esc(v.name)}</h3>
      <p class="thesis">${esc(v.thesis)}</p>
      <p class="cos"><b>Backed by:</b> ${esc(v.companies.join(", ") || "no verified companies yet")}</p>
      ${full ? `<details><summary>Evidence (${esc(tl.length)})</summary><ul class="timeline">${tl.map((m) => `<li class="${m.verified ? "" : "unv"}"><time>${esc(m.date)}</time><strong>${esc(m.company)}</strong> — ${esc(m.action)} · <a href="${esc(safeUrl(m.story_url))}" rel="noopener">${esc(m.outlet || "story")}</a>${m.verified ? "" : ` (${esc(m.reason || "unverified")}, not counted)`}</li>`).join("")}</ul></details>` : ""}
      <div class="trend-meta"><span class="t-comms">${v.commodities.map((x) => `<span class="c-${esc(x)}">${dot(x)} ${esc(labelOf(x))}</span>`).join("")}</span><span class="t-nums">${esc(plural(v.companies_current, "company", "companies"))} this week · hotness ${esc(v.hotness)}</span></div>
    </article>`;
  }

  function riverRow(i) {
    const d = i.first_published_at;
    return `<article class="row">
      <time datetime="${esc(d)}"><b>${esc(clock(d))}</b>${esc(dayShort(d))}</time>
      <div>
        ${kicker(i)}
        <h3><a href="${esc(safeUrl(i.sources[0]?.url))}" rel="noopener">${esc(i.title)}</a></h3>
        ${i.summary && i.summary !== i.title ? `<p>${esc(i.summary)}</p>` : ""}
        ${byline(i)}
        ${i.organizations.length ? `<div class="orgs">Companies: ${esc(i.organizations.map((o) => o.name).join(", "))}</div>` : ""}
        ${i.sources.length > 1 || i.figures.length ? `<details><summary>${esc(plural(i.sources.length, "source", "sources"))}${i.figures.length ? " and figures" : ""}</summary><ul>
          ${i.sources.map((s) => `<li><a href="${esc(safeUrl(s.url))}" rel="noopener">${esc(s.title)}</a> — ${esc(outletName(s))} · tier ${esc(s.tier)} · ${esc(s.published_local)}</li>`).join("")}
          ${i.figures.map((f) => `<li>“${esc(f.span)}” — ${esc(f.outlet)}</li>`).join("")}</ul></details>` : ""}
      </div></article>`;
  }

  function river(items) {
    const box = document.createElement("section");
    box.className = "river";
    if (!items.length) { box.innerHTML = `<p class="empty">No qualifying news in the last ${esc(data.window_days)} days.</p>`; return box; }
    const list = document.createElement("div"), sentinel = document.createElement("div");
    sentinel.id = "sentinel"; box.append(list, sentinel);
    let shown = 0;
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && more(), { rootMargin: "800px" });
    const more = () => {
      const next = items.slice(shown, shown + data.page_size);
      list.insertAdjacentHTML("beforeend", next.map(riverRow).join(""));
      shown += next.length;
      if (shown >= items.length) io.disconnect();
    };
    more(); io.observe(sentinel);
    return box;
  }

  const byNewest = (a, b) => b.first_published_at.localeCompare(a.first_published_at);
  function ranked(items) {
    const latest = Math.max(...items.map((i) => Date.parse(i.first_published_at)));
    const recent = items.filter((i) => latest - Date.parse(i.first_published_at) <= 48 * 36e5);
    const pool = recent.length >= 5 ? recent : items;
    return [...pool].sort((a, b) => b.relevance - a.relevance || b.distinct_source_count - a.distinct_source_count || byNewest(a, b));
  }
  function pickTop(items, n) {
    const out = [], seen = new Set();
    for (const i of ranked(items)) { if (!seen.has(i.commodities[0]) || out.length >= 4) { out.push(i); seen.add(i.commodities[0]); } if (out.length >= n) break; }
    for (const i of ranked(items)) { if (out.length >= n) break; if (!out.includes(i)) out.push(i); }
    return out;
  }
  const hotTrends = (commodity) => trends.filter((v) => v.status === "CONFIRMED" && v.trajectory !== "DORMANT" && (!commodity || v.commodities.includes(commodity)))
    .sort((a, b) => Number(b.hotness) - Number(a.hotness));

  function briefingBox() {
    const nl = published(issues)[0], an = published(analyses)[0];
    if (!nl && !an) return `<div class="box briefing"><div class="box-h">The Briefing</div><p class="empty">Today's newsletter is written each morning around 7:30 CT.</p></div>`;
    const teaser = analysis?.sections?.overall ? clip(textOf(analysis.sections.overall), 220) : "";
    return `<div class="box briefing"><div class="box-h"><span>The Briefing</span><span>${esc(nl ? dayShort(`${nl.date}T17:00:00Z`) : "")}</span></div>
      <h3>${esc(analysis?.title ? "What today's news means for energy traders" : "Today's newsletter")}</h3>
      ${teaser ? `<p>${esc(teaser)}</p>` : ""}
      <div class="btn-row">${nl ? `<a class="btn" href="#newsletter">Read the newsletter →</a>` : ""}${an ? `<a class="btn ghost" href="#analysis">Trader analysis</a>` : ""}</div></div>`;
  }
  function calendarBox(commodity) {
    const cal = (data.calendar || []).filter((e) => !commodity || e.commodities.includes(commodity)).slice(0, 4);
    if (!cal.length) return "";
    return `<div class="box"><div class="box-h">Coming up</div><ul class="list">${cal.map((e) => `<li><span class="cal-when">${esc(e.at_local)}</span><span class="cal-name">${esc(e.name)}</span></li>`).join("")}</ul></div>`;
  }
  function companiesBox(commodity) {
    const cos = (data.most_active_companies || []).filter((c) => !commodity || c.commodities.includes(commodity)).slice(0, 6);
    if (!cos.length) return "";
    return `<div class="box"><div class="box-h">Most active companies</div><ul class="list">${cos.map((c) => `<li class="co"><span>${esc(c.name)}</span><span>${esc(plural(c.stories, "story", "stories"))}</span></li>`).join("")}</ul></div>`;
  }
  function statsBox() {
    const counts = Object.fromEntries(data.tabs.filter((t) => t.commodity).map((t) => [t.commodity, data.feed.filter((i) => i.commodities.includes(t.commodity)).length]));
    return `<div class="box"><div class="box-h"><span>This week</span><span>${esc(plural(data.feed.length, "story", "stories"))}</span></div><div class="stats">${
      Object.entries(counts).map(([c, n]) => `<a class="stat c-${esc(c)}" href="#${esc(tabFor(c).id)}"><b>${esc(n)}</b><span>${dot(c)}${esc(labelOf(c))}</span></a>`).join("")}</div></div>`;
  }
  function referencesBox(commodity) {
    const refs = (data.reference_links || {})[commodity] || [];
    return refs.length ? `<div class="box"><div class="box-h">Further reading</div><ul class="list">${refs.map((r) => `<li><a href="${esc(safeUrl(r.url))}" rel="noopener"><strong>${esc(r.name)}</strong></a><br><span class="cal-when">${esc(r.note)}</span></li>`).join("")}</ul></div>` : "";
  }

  // ---------- pages ----------
  function renderToday() {
    const main = $("#main");
    const feed = data.feed;
    if (!feed.length) { main.innerHTML = `<p class="empty">No qualifying news in the last ${esc(data.window_days)} days.</p>`; return; }
    const top = pickTop(feed, 5);
    const [lead, ...second] = top;
    const hot = hotTrends().slice(0, 3);
    const markets = data.tabs.filter((t) => t.commodity);
    main.innerHTML = `
      <div class="front">
        <div class="front-main">${storyCard(lead, "lead")}<div class="second">${second.map((i) => storyCard(i)).join("")}</div></div>
        <aside class="rail">${live ? briefingBox() : ""}${statsBox()}${calendarBox()}</aside>
      </div>
      ${secHead("Hottest trends", `<a class="more" href="#trends">All trends →</a>`)}
      ${hot.length ? `<div class="trend-grid">${hot.map((v) => trendCard(v)).join("")}</div>` : `<p class="empty">No confirmed trends yet — a trend needs two or more companies pushing the same idea.</p>`}
      ${secHead("Markets")}
      <div class="markets">${markets.map((t) => {
        const items = ranked(feed.filter((i) => i.commodities.includes(t.commodity) && !top.includes(i))).slice(0, 4);
        const n = feed.filter((i) => i.commodities.includes(t.commodity)).length;
        return `<section class="market c-${esc(t.commodity)}"><div class="market-h"><a href="#${esc(t.id)}">${esc(t.label)}</a><span>${esc(n)} this week</span></div>
          ${items.length ? `<ol>${items.map((i) => `<li><a href="${esc(safeUrl(i.sources[0]?.url))}" rel="noopener">${esc(i.title)}</a>${byline(i)}</li>`).join("")}</ol>` : `<p class="empty">No other stories this week.</p>`}</section>`;
      }).join("")}</div>
      ${secHead("Latest", `<a class="more" href="#all">Full feed →</a>`)}`;
    main.append(river([...feed].filter((i) => !top.includes(i)).sort(byNewest).slice(0, 12)));
  }

  function renderFeedPage() {
    const main = $("#main");
    main.innerHTML = `<header class="page-head"><div class="kicker">All markets</div><h1>Latest news</h1><p>Every qualifying story from the last ${esc(data.window_days)} days, newest first.</p></header>
      <div class="filters" id="filters"><button aria-pressed="true" data-c="">All</button>${data.tabs.filter((t) => t.commodity).map((t) => `<button aria-pressed="false" data-c="${esc(t.commodity)}" class="c-${esc(t.commodity)}">${dot(t.commodity)} ${esc(t.label)}</button>`).join("")}</div>`;
    const holder = document.createElement("div"); main.append(holder);
    const draw = (c) => { holder.innerHTML = ""; holder.append(river([...data.feed].filter((i) => !c || i.commodities.includes(c)).sort(byNewest))); };
    $("#filters").addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      main.querySelectorAll("#filters button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw(b.dataset.c);
    });
    draw("");
  }

  function renderCommodity(tab) {
    const main = $("#main");
    const c = tab.commodity;
    const items = data.feed.filter((i) => i.commodities.includes(c));
    const syn = data.synopsis?.commodities?.[c];
    const view = analysisFresh() && analysis.sections?.[c]
      ? `<div class="view c-${esc(c)}"><div class="kicker">Trader's view</div><div class="md">${analysis.sections[c]}</div><p class="note">From today's analysis, written by Claude from the ${esc(analysis.date)} digest and checked by the validator. <a href="#analysis">Read the full analysis</a></p></div>`
      : syn ? `<div class="view c-${esc(c)}"><div class="kicker">Automated synopsis · data only</div><ul class="syn">${syn.sentences.map((s) => `<li>${esc(s)}</li>`).join("")}</ul><p class="note">Today's written analysis isn't published yet.</p></div>` : "";
    const top = items.length ? pickTop(items, 3) : [];
    const hot = hotTrends(c);
    main.innerHTML = `<header class="page-head c-${esc(c)}"><div class="kicker">${dot(c)} Markets</div><h1>${esc(tab.label)}</h1><p>${esc(plural(items.length, "qualifying story", "qualifying stories"))} from reputable sources in the last ${esc(data.window_days)} days.</p></header>
      <div class="split">
        <div class="front-main">${view}${top.length ? storyCard(top[0], "lead") + `<div class="second">${top.slice(1).map((i) => storyCard(i)).join("")}</div>` : `<p class="empty">No qualifying news in the last ${esc(data.window_days)} days.</p>`}</div>
        <aside class="rail">${calendarBox(c)}${companiesBox(c)}${referencesBox(c)}</aside>
      </div>
      ${hot.length ? secHead(`Trends in ${esc(tab.label)}`, `<a class="more" href="#trends">All trends →</a>`) + `<div class="trend-grid">${hot.slice(0, 3).map((v) => trendCard(v)).join("")}</div>` : ""}
      ${secHead("All stories")}`;
    main.append(river([...items].filter((i) => !top.includes(i)).sort(byNewest)));
  }

  function renderTrends() {
    const main = $("#main");
    const visible = trends.filter((v) => v.trajectory !== "DORMANT").sort((a, b) => Number(b.hotness) - Number(a.hotness));
    const conf = visible.filter((v) => v.status === "CONFIRMED"), emer = visible.filter((v) => v.status === "EMERGING");
    main.innerHTML = `<header class="page-head"><div class="kicker">Trend tracker</div><h1>What companies are pushing</h1>
      <p>A trend is an idea several companies are backing. It's confirmed once two or more verified companies push it within 30 days; trajectory compares this week with last.</p></header>
      ${secHead(`Confirmed <span style="color:var(--muted);font-weight:400">· ${esc(conf.length)}</span>`)}
      ${conf.length ? `<div class="trend-grid">${conf.map((v) => trendCard(v, true)).join("")}</div>` : `<p class="empty">No confirmed trends yet.</p>`}
      ${emer.length ? secHead(`Emerging <span style="color:var(--muted);font-weight:400">· one company so far</span>`) + `<div class="trend-grid">${emer.map((v) => trendCard(v, true)).join("")}</div>` : ""}`;
  }

  async function renderDoc(kind) {
    const main = $("#main");
    const man = kind === "newsletter" ? issues : analyses;
    const dir = kind === "newsletter" ? "issues" : "analysis";
    const pub = published(man);
    const want = (location.hash.match(new RegExp(`^#${kind}/(\\d{4}-\\d{2}-\\d{2})$`)) || [])[1];
    const pick = pub.find((i) => i.date === want) || pub[0];
    const label = kind === "newsletter" ? "The Newsletter" : "Trader Analysis";
    if (!pick) {
      main.innerHTML = `<header class="page-head"><div class="kicker">${label}</div><h1>Not published yet</h1><p>The ${kind === "newsletter" ? "newsletter" : "written analysis"} is written each morning around 7:30 CT.</p></header>`;
      return;
    }
    main.innerHTML = `<p class="empty">Loading…</p>`;
    const r = await fetch(`${dir}/${pick.date}.html`, { cache: "no-cache" });
    const body = r.ok ? await r.text() : `<p class="empty">Could not load.</p>`;
    const other = kind === "newsletter" ? published(analyses).find((i) => i.date === pick.date) : published(issues).find((i) => i.date === pick.date);
    main.innerHTML = `<div class="article-wrap">
      <article>
        <div class="article-kicker"><span class="kicker">${label}</span><span class="byline">${esc(isoLong(pick.date))}</span></div>
        ${warnNote(pick)}
        <div class="prose">${body}</div>
      </article>
      <aside class="aside">
        ${other ? `<div class="box briefing"><div class="box-h">${kind === "newsletter" ? "Go deeper" : "The headlines"}</div><h3>${kind === "newsletter" ? "What this means for energy traders" : "Today's newsletter"}</h3><a class="btn" href="#${kind === "newsletter" ? "analysis" : "newsletter"}/${esc(pick.date)}">${kind === "newsletter" ? "Read the analysis" : "Read the newsletter"} →</a></div>` : ""}
        <div class="box"><div class="box-h">Past editions</div><ul class="list issues-list">${pub.slice(0, 14).map((i) => `<li><a href="#${kind}/${esc(i.date)}" aria-current="${i.date === pick.date}"><span>${esc(isoLong(i.date).replace(/^\w+, /, ""))}</span><span>›</span></a></li>`).join("")}</ul></div>
        ${kind === "newsletter" && archives.weeks.length ? `<div class="box"><div class="box-h">Weekly archives</div><ul class="list">${archives.weeks.map((w) => `<li><a href="?feed=archive/${esc(w)}/feed.json#all">${esc(w)}</a></li>`).join("")}</ul></div>` : ""}
        <div class="box"><div class="box-h">How this is made</div><p class="foot-copy">Written by Claude from the day's digest of reputable sources, then checked by an automated validator for sourcing and advice-like language. Unverified; not investment advice.</p></div>
      </aside></div>`;
  }

  // ---------- routing ----------
  function navTabs() {
    const base = live ? [{ id: "today", label: "Today" }, { id: "newsletter", label: "Newsletter" }, { id: "analysis", label: "Analysis" }, { id: "trends", label: "Trends" }] : [{ id: "today", label: "Front page" }];
    return [...base, { sep: true }, ...data.tabs.filter((t) => t.commodity), { id: "all", label: "Latest" }];
  }
  function route() {
    const h = location.hash.replace(/^#/, "");
    const tabs = navTabs().filter((t) => !t.sep);
    const id = h.split("/")[0] || "today";
    const tab = tabs.find((t) => t.id === id) || tabs[0];
    if (tab.id === current && !h.includes("/")) return;
    const changed = started;
    started = true;
    current = tab.id;
    $("#tabs").innerHTML = navTabs().map((t) => t.sep ? `<span class="sep" aria-hidden="true"></span>`
      : `<button role="tab" aria-selected="${t.id === tab.id}" data-id="${esc(t.id)}">${t.commodity ? dot(t.commodity).replace('class="dot', `class="dot c-${esc(t.commodity)}`) : ""}${esc(t.label)}</button>`).join("");
    const sel = $("#tabs [aria-selected=true]"); sel?.scrollIntoView({ block: "nearest", inline: "center" });
    if (tab.id === "newsletter" || tab.id === "analysis") renderDoc(tab.id);
    else if (tab.id === "trends") renderTrends();
    else if (tab.id === "today") renderToday();
    else if (tab.id === "all") renderFeedPage();
    else renderCommodity(tab);
    if (changed) window.scrollTo({ top: Math.min(window.scrollY, $(".sections").offsetTop), behavior: "instant" });
  }

  function initTheme() {
    const btn = $("#theme");
    btn.addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("end-theme", next); } catch {}
    });
  }

  async function init() {
    initTheme();
    $("#today").textContent = longDate(Date.now());
    data = await get(feedPath, null);
    if (!data) { $("#main").innerHTML = `<p class="empty">The digest has not been published yet.</p>`; $("#asof").textContent = ""; return; }
    const tv = live ? await get("trends/trends.json", null) : null;
    trends = tv ? tv.trends : (data.trends.all || []);
    if (live) {
      [issues, analyses, archives] = await Promise.all([get("issues/manifest.json", issues), get("analysis/manifest.json", analyses), get("archive/index.json", archives)]);
      const latest = published(analyses)[0];
      if (latest) analysis = await get(`analysis/${latest.date}.json`, null);
    }
    $("#asof").textContent = `${live ? "Updated" : "Archived"} ${data.data_as_of_local}`;
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
