"use strict";

(() => {
  const DATA_URL = "challenges.json";
  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const TYPE_LABELS = { daily: "Daily", weekly: "Weekly" };
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const URL_PREFIX = "https://leetcode.com/problems/";
  const numbers = new Intl.NumberFormat("en-US");

  const els = {
    range: document.getElementById("range"),
    counts: document.getElementById("counts"),
    error: document.getElementById("error"),
    rows: document.getElementById("rows"),
  };

  let challenges = [];
  const rowCache = new Map();

  // Split the ISO string instead of using Date, which would shift the day west of UTC.
  function formatDate(iso) {
    const [year, month, day] = iso.split("-");
    return `${MONTH_NAMES[Number(month) - 1]} ${Number(day)}, ${year}`;
  }

  function compareNewestFirst(a, b) {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1;
    if (a.type !== b.type) return a.type === "daily" ? -1 : 1;
    return Number(a.id) - Number(b.id);
  }

  function isChallenge(item) {
    return item !== null && typeof item === "object"
      && typeof item.date === "string" && DATE_PATTERN.test(item.date)
      && Object.hasOwn(TYPE_LABELS, item.type)
      && typeof item.id === "string" && /^\d+$/.test(item.id)
      && typeof item.title === "string"
      && typeof item.slug === "string"
      && typeof item.difficulty === "string"
      && typeof item.isPaidOnly === "boolean"
      && typeof item.url === "string" && item.url.startsWith(URL_PREFIX);
  }

  function parseData(data) {
    if (data === null || typeof data !== "object" || !Array.isArray(data.challenges)
        || typeof data.from !== "string" || !DATE_PATTERN.test(data.from)
        || typeof data.to !== "string" || !DATE_PATTERN.test(data.to)
        || !data.challenges.every(isChallenge)) {
      throw new Error("the file is malformed");
    }
    return data;
  }

  function cell(text, className) {
    const td = document.createElement("td");
    if (className) td.className = className;
    td.textContent = text;
    return td;
  }

  function problemLink(url, text) {
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = text;
    return a;
  }

  function buildRow(challenge) {
    const tr = document.createElement("tr");
    const title = cell("", "title");
    title.append(problemLink(challenge.url, challenge.title));
    const link = cell("");
    link.append(problemLink(challenge.url, "Open"));
    tr.append(
      cell(challenge.date),
      cell(TYPE_LABELS[challenge.type]),
      cell(challenge.id, "num"),
      title,
      cell(challenge.difficulty),
      cell(challenge.isPaidOnly ? "Premium" : "Free"),
      link,
    );
    return tr;
  }

  function rowFor(challenge) {
    let tr = rowCache.get(challenge);
    if (!tr) {
      tr = buildRow(challenge);
      rowCache.set(challenge, tr);
    }
    return tr;
  }

  function updateCounts(matched) {
    const daily = challenges.filter((c) => c.type === "daily").length;
    const weekly = challenges.length - daily;
    els.counts.textContent = `${numbers.format(challenges.length)} challenges: `
      + `${numbers.format(daily)} daily, ${numbers.format(weekly)} weekly. `
      + `${numbers.format(matched)} match the current filters.`;
  }

  function render(list) {
    const fragment = document.createDocumentFragment();
    for (const challenge of list) fragment.append(rowFor(challenge));
    els.rows.replaceChildren(fragment);
    updateCounts(list.length);
  }

  function showError(message) {
    els.range.textContent = "The challenge list is unavailable.";
    els.counts.textContent = "";
    els.error.textContent = message;
    els.error.hidden = false;
  }

  function init(data) {
    challenges = data.challenges.slice().sort(compareNewestFirst);
    els.range.textContent = `${formatDate(data.from)} – ${formatDate(data.to)}`;
    render(challenges);
  }

  async function load() {
    let data;
    try {
      const response = await fetch(DATA_URL);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      data = parseData(await response.json());
    } catch (err) {
      showError(`Could not load challenges.json: ${err.message}.`);
      return;
    }
    init(data);
  }

  load();
})();
