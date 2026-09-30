"use strict";

(() => {
  const DATA_URL = "challenges.json";
  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  const TYPE_LABELS = { daily: "Daily", weekly: "Weekly" };
  const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
  const ID_QUERY = /^#?(\d+)$/;
  const URL_PREFIX = "https://leetcode.com/problems/";
  const EMPTY_MESSAGE = "No challenges match the current filters.";
  const COLUMN_COUNT = 7;
  const numbers = new Intl.NumberFormat("en-US");

  const els = {
    range: document.getElementById("range"),
    counts: document.getElementById("counts"),
    error: document.getElementById("error"),
    rows: document.getElementById("rows"),
    form: document.getElementById("filters"),
    search: document.getElementById("search"),
    year: document.getElementById("year"),
    month: document.getElementById("month"),
    type: document.getElementById("type"),
    difficulty: document.getElementById("difficulty"),
    reset: document.getElementById("reset"),
  };
  const selectsByParam = { year: els.year, month: els.month, type: els.type, difficulty: els.difficulty };
  const selects = Object.values(selectsByParam);

  let challenges = [];
  let years = [];
  let months = [];
  const rowCache = new Map();

  // Split the ISO string instead of using Date, which would shift the day west of UTC.
  function formatDate(iso) {
    const [year, month, day] = iso.split("-");
    return `${MONTH_NAMES[Number(month) - 1]} ${Number(day)}, ${year}`;
  }

  function formatMonth(key) {
    const [year, month] = key.split("-");
    return `${MONTH_NAMES[Number(month) - 1]} ${year}`;
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
    if (list.length === 0) {
      const tr = document.createElement("tr");
      const td = cell(EMPTY_MESSAGE, "empty");
      td.colSpan = COLUMN_COUNT;
      tr.append(td);
      fragment.append(tr);
    }
    for (const challenge of list) fragment.append(rowFor(challenge));
    els.rows.replaceChildren(fragment);
    updateCounts(list.length);
  }

  function option(value, label) {
    const el = document.createElement("option");
    el.value = value;
    el.textContent = label;
    return el;
  }

  function fillSelect(select, allLabel, entries) {
    const fragment = document.createDocumentFragment();
    fragment.append(option("", allLabel));
    for (const [value, label] of entries) fragment.append(option(value, label));
    select.replaceChildren(fragment);
  }

  function monthsForYear(year) {
    return year ? months.filter((key) => key.startsWith(`${year}-`)) : months;
  }

  function populateMonths() {
    const selected = els.month.value;
    const available = monthsForYear(els.year.value);
    fillSelect(els.month, "All months", available.map((key) => [key, formatMonth(key)]));
    els.month.value = available.includes(selected) ? selected : "";
  }

  function searchMatcher(input) {
    const query = input.trim().toLowerCase();
    if (!query) return () => true;
    const id = ID_QUERY.exec(query);
    if (id) return (c) => c.id === id[1];
    return (c) => c.title.toLowerCase().includes(query)
      || c.slug.toLowerCase().includes(query)
      || c.date.includes(query);
  }

  function filtered() {
    const matchesSearch = searchMatcher(els.search.value);
    const year = els.year.value;
    const month = els.month.value;
    const type = els.type.value;
    const difficulty = els.difficulty.value;
    return challenges.filter((c) => (!year || c.date.startsWith(`${year}-`))
      && (!month || c.date.startsWith(`${month}-`))
      && (!type || c.type === type)
      && (!difficulty || c.difficulty.toLowerCase() === difficulty)
      && matchesSearch(c));
  }

  function isDefault() {
    return els.search.value === "" && selects.every((select) => select.value === "");
  }

  function readQuery() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    if (q !== null) els.search.value = q;
    const year = params.get("year");
    if (years.includes(year)) els.year.value = year;
    populateMonths();
    const month = params.get("month");
    if (monthsForYear(els.year.value).includes(month)) els.month.value = month;
    const type = params.get("type");
    if (type === "daily" || type === "weekly") els.type.value = type;
    const difficulty = params.get("difficulty");
    if (["easy", "medium", "hard"].includes(difficulty)) els.difficulty.value = difficulty;
  }

  function writeQuery() {
    const params = new URLSearchParams();
    const q = els.search.value.trim();
    if (q) params.set("q", q);
    for (const [name, select] of Object.entries(selectsByParam)) {
      if (select.value) params.set(name, select.value);
    }
    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
    if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      history.replaceState(null, "", url);
    }
  }

  function update() {
    els.reset.hidden = isDefault();
    render(filtered());
  }

  function change() {
    update();
    writeQuery();
  }

  function reset() {
    els.search.value = "";
    for (const select of selects) select.value = "";
    populateMonths();
    update();
    history.replaceState(null, "", `${window.location.pathname}${window.location.hash}`);
  }

  function bindControls() {
    els.form.addEventListener("submit", (event) => event.preventDefault());
    els.search.addEventListener("input", change);
    els.year.addEventListener("change", () => {
      populateMonths();
      change();
    });
    for (const select of [els.month, els.type, els.difficulty]) select.addEventListener("change", change);
    els.reset.addEventListener("click", reset);
  }

  function showError(message) {
    els.range.textContent = "The challenge list is unavailable.";
    els.counts.textContent = "";
    els.error.textContent = message;
    els.error.hidden = false;
  }

  function init(data) {
    challenges = data.challenges.slice().sort(compareNewestFirst);
    months = [...new Set(challenges.map((c) => c.date.slice(0, 7)))].sort().reverse();
    years = [...new Set(months.map((key) => key.slice(0, 4)))];
    els.range.textContent = `${formatDate(data.from)} – ${formatDate(data.to)}`;
    fillSelect(els.year, "All years", years.map((year) => [year, year]));
    readQuery();
    bindControls();
    update();
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
