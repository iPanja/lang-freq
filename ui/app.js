const SAVED_KEY = "story-vocabulary:saved:v1";
const STATUS_KEY = "story-vocabulary:status:v1";
const state = { rows: [], filtered: [], selectedRank: null, detailRequest: 0, sort: "rank", query: "", pos: "", studyFilter: "all", saved: new Set(), statuses: {} };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = (value) => new Intl.NumberFormat().format(value || 0);
const prettyPos = (value) => {
  const labels = {v:"verb", n:"noun", adj:"adjective", adv:"adverb", art:"article", prep:"preposition", conj:"conjunction", pron:"pronoun", prop:"proper noun", "":"unclassified"};
  return String(value || "").split(",").map((part) => labels[part] || part || "unclassified").join(" · ");
};
const wordKey = (row) => row.lemma.toLocaleLowerCase();

try {
  const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || "[]");
  if (Array.isArray(saved)) state.saved = new Set(saved.filter((value) => typeof value === "string").map((value) => value.split("::")[0].toLocaleLowerCase()));
} catch { /* The vocabulary browser still works if storage is unavailable. */ }
try {
  const savedStatuses = JSON.parse(localStorage.getItem(STATUS_KEY) || "{}");
  if (savedStatuses && typeof savedStatuses === "object" && !Array.isArray(savedStatuses)) state.statuses = savedStatuses;
} catch { /* Progress remains usable in memory if storage is unavailable. */ }

async function init() {
  try {
    const response = await fetch("/api/vocab");
    if (!response.ok) throw new Error("Could not load vocab.csv");
    state.rows = await response.json();
    $("#total-count").textContent = number(state.rows.length);
    populatePos();
    renderRows();
  } catch (error) {
    $("#vocab-rows").innerHTML = `<tr><td colspan="4" class="no-results">${escapeHtml(error.message)}. Start the app from the repository root.</td></tr>`;
  }
}

function populatePos() {
  const values = [...new Set(state.rows.flatMap((row) => row.pos_tags || []).filter(Boolean))].sort();
  $("#pos-filter").insertAdjacentHTML("beforeend", values.map((pos) => `<option value="${escapeHtml(pos)}">${escapeHtml(prettyPos(pos))}</option>`).join(""));
}

function matchesQuery(row, query) {
  if (!query) return true;
  return `${row.lemma} ${row.pos} ${row.observed_forms}`.toLocaleLowerCase().includes(query);
}

function renderRows() {
  const query = state.query.trim().toLocaleLowerCase();
  state.filtered = state.rows.filter((row) => {
    const status = state.statuses[wordKey(row)] || "";
    const passesStudy = state.studyFilter === "all"
      || (state.studyFilter === "saved" && state.saved.has(wordKey(row)))
      || (state.studyFilter === "learning" && status === "learning")
      || (state.studyFilter === "known" && status === "known")
      || (state.studyFilter === "review" && (row.ambiguous || row.possible_analyses.length > 0));
    return (!state.pos || (row.pos_tags || []).includes(state.pos)) && passesStudy && matchesQuery(row, query);
  });
  state.filtered.sort((a, b) => state.sort === "count" ? b.count - a.count || a.rank - b.rank : state.sort === "alpha" ? a.lemma.localeCompare(b.lemma) || a.rank - b.rank : a.rank - b.rank);
  const displayRows = state.filtered;
  $("#visible-count").textContent = `${number(state.filtered.length)} entries`;
  $(".list-footer b").textContent = state.sort === "count" ? "story frequency" : state.sort === "alpha" ? "alphabetically" : "story frequency rank";
  renderReadiness();
  if (!displayRows.length) {
    $("#vocab-rows").innerHTML = '<tr><td colspan="4" class="no-results">No matching words. Try a shorter search.</td></tr>';
    return;
  }
  $("#vocab-rows").innerHTML = displayRows.map((row) => {
    const selected = row.rank === state.selectedRank ? " selected" : "";
    const forms = row.observed_forms.split(";").slice(0, 3).map((item) => item.trim().split(" (")[0]).join(" · ");
    const saved = state.saved.has(wordKey(row));
    const status = state.statuses[wordKey(row)] || "";
    const posLabel = row.pos_tags.length ? row.pos_tags.map(prettyPos).join(" · ") : "Needs review";
    const stateLabel = status ? `<span class="row-state ${status}">${status}</span>` : "";
    const reviewLabel = row.ambiguous ? '<span class="row-state review">review</span>' : "";
    return `<tr class="${selected}" data-rank="${row.rank}" tabindex="0" aria-label="${escapeHtml(row.lemma)}, ${number(row.count)} occurrences">
      <td class="word-cell"><span class="rank">${row.rank}</span><button class="lemma-link" type="button">${escapeHtml(row.lemma)}</button><div class="subform">${escapeHtml(forms)} ${stateLabel} ${reviewLabel}</div></td>
      <td><span class="pos-pill">${escapeHtml(posLabel)}</span></td><td class="numeric">${number(row.count)}</td>
      <td class="save-cell"><button class="save-star${saved ? " is-saved" : ""}" type="button" data-save-rank="${row.rank}" aria-label="${saved ? "Remove saved word" : "Save word"}" aria-pressed="${saved}" title="${saved ? "Saved" : "Save word"}">${saved ? "★" : "☆"}</button></td>
    </tr>`;
  }).join("");
}

function renderReadiness() {
  const total = state.rows.reduce((sum, row) => sum + row.count, 0);
  const known = state.rows.reduce((sum, row) => sum + (state.statuses[wordKey(row)] === "known" ? row.count : 0), 0);
  const learning = state.rows.reduce((sum, row) => sum + (state.statuses[wordKey(row)] === "learning" ? row.count : 0), 0);
  const review = state.rows.reduce((sum, row) => sum + row.ambiguous_count, 0);
  const likely = state.rows.reduce((sum, row) => sum + row.likely_count, 0);
  const percent = total ? Math.round(known * 100 / total) : 0;
  $("#readiness-percent").textContent = `${percent}%`;
  $("#readiness-bar").style.width = `${percent}%`;
  $("#readiness-summary").textContent = `${number(known)} known · ${number(learning)} learning · ${number(Math.max(0, total - known - learning))} unmarked · ${number(likely)} assigned by corpus frequency · ${number(review)} unresolved`;
}

function parseForms(text) {
  if (!text) return [];
  return text.split(";").map((item) => {
    const match = item.trim().match(/^(.*?)\s+\((\d+)\)$/);
    return match ? {form: match[1], count: Number(match[2])} : {form: item.trim(), count: null};
  }).filter((item) => item.form);
}

function clipboardButton(text, label = "Copy fields") {
  const encoded = encodeURIComponent(text);
  return `<button class="icon-button copy-button" data-copy="${encoded}" type="button">${label}</button>`;
}

function renderDetail(entry) {
  const forms = parseForms(entry.observed_forms);
  const copyText = [entry.lemma, prettyPos(entry.pos), `Story frequency: ${entry.count}`, `Observed forms: ${forms.map((f) => `${f.form} (${f.count ?? ""})`).join(", ")}`].join("\n");
  const glosses = [];
  const usage = [];
  for (const item of entry.dictionary || []) {
    for (const gloss of item.glosses || []) if (!glosses.includes(gloss)) glosses.push(gloss);
    for (const note of item.usage || []) if (!usage.includes(note)) usage.push(note);
  }
  const general = entry.general_frequency || [];
  const examples = entry.examples || [];
  const storyExamples = entry.story_examples || [];
  const copyButton = clipboardButton(copyText);
  const saved = state.saved.has(wordKey(entry));
  const status = state.statuses[wordKey(entry)] || "";
  const spanishDictUrl = `https://www.spanishdict.com/translate/${encodeURIComponent(entry.lemma)}`;
  const analyses = entry.possible_analyses || [];
  const resolution = entry.form_resolution || {};
  $("#detail-pane").innerHTML = `<div class="detail-content">
    <div class="detail-top"><span class="detail-rank">STORY FREQUENCY RANK #${entry.rank}</span><div class="detail-actions"><button class="icon-button detail-save${saved ? " is-saved" : ""}" data-save-rank="${entry.rank}" type="button" aria-pressed="${saved}">${saved ? "★ Saved" : "☆ Save word"}</button><a class="icon-button spanishdict-link" href="${escapeHtml(spanishDictUrl)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(entry.lemma)} on SpanishDict">SpanishDict ↗</a>${copyButton}</div></div>
    <h2 class="detail-title">${escapeHtml(entry.lemma)}</h2>
    <div class="detail-subtitle"><span class="pos-pill">${escapeHtml(prettyPos(entry.pos))}</span><span>Story vocabulary</span></div>
    <div class="study-control"><label for="word-status">Learning status</label><select id="word-status" data-status-lemma="${escapeHtml(entry.lemma)}"><option value=""${status === "" ? " selected" : ""}>Not marked</option><option value="learning"${status === "learning" ? " selected" : ""}>Learning</option><option value="known"${status === "known" ? " selected" : ""}>Known</option></select></div>
    <div class="detail-stats"><div class="stat-card"><span class="stat-label">IN YOUR STORY</span><span class="stat-value">${number(entry.count)}</span><span class="stat-caption">occurrences</span></div><div class="stat-card"><span class="stat-label">GENERAL SPANISH</span><span class="stat-value">${general.length ? number(general[0].count) : "—"}</span><span class="stat-caption">${general.length ? "corpus count" : "no exact match"}</span></div></div>
    <section class="section"><div class="section-heading"><h3>FORMS IN YOUR STORY</h3><small>${forms.length} forms</small></div>${forms.length ? `<div class="forms-list">${forms.map((form) => `<span class="form-chip">${escapeHtml(form.form)} <b>${number(form.count)}</b></span>`).join("")}</div>` : '<p class="section-empty">No observed forms recorded.</p>'}</section>
    ${analyses.length ? `<section class="section analysis-note"><div class="section-heading"><h3>AMBIGUOUS FORMS</h3><small>Corpus frequency suggests; context decides</small></div><p class="section-empty">${number(resolution.corpus_prior)} tokens were assigned using general corpus frequency. ${number(resolution.unresolved)} remain unresolved. Review these candidate analyses against the story context:</p><ul class="analysis-list">${analyses.map((item) => `<li><b>${escapeHtml(item.lemma)}</b> · ${escapeHtml(prettyPos(item.pos))}${item.warning ? ` <span>${escapeHtml(item.warning)}</span>` : ""}${item.glosses?.length ? `<small>${escapeHtml(item.glosses.join(" · "))}</small>` : ""}<small>forms: ${escapeHtml((item.forms || []).join(", "))}; corpus count ${number(item.corpus_form_count)}</small></li>`).join("")}</ul></section>` : ""}
    <section class="section"><div class="section-heading"><h3>DICTIONARY</h3><small>Wiktionary-derived</small></div>${glosses.length ? `<ul class="gloss-list">${glosses.slice(0, 12).map((gloss) => `<li>${escapeHtml(gloss)}</li>`).join("")}</ul>${usage.slice(0, 2).map((note) => `<p class="usage-note">${escapeHtml(note)}</p>`).join("")}` : '<p class="section-empty">No dictionary entry found for this lemma.</p>'}</section>
    <section class="section"><div class="section-heading"><h3>GENERAL FREQUENCY</h3><small>spanish_data frequency.csv</small></div>${general.length ? `<div class="frequency-list">${general.map((item) => `<div><div class="frequency-row"><span>${number(item.count)} corpus occurrences</span><span>${escapeHtml(item.flags || "")}</span></div><div class="frequency-forms">${escapeHtml(item.usage.split("|").slice(0, 12).join(" · "))}</div></div>`).join("")}</div>` : '<p class="section-empty">No exact lemma and part-of-speech match in the general list.</p>'}</section>
    <section class="section"><div class="section-heading"><h3>EXAMPLES FROM YOUR BOOK</h3><small>${storyExamples.length ? `${storyExamples.length} excerpts` : "local EPUB"}</small></div>${storyExamples.length ? storyExamples.map((example) => `<article class="example"><div class="example-es">${escapeHtml(example.text)}</div><div class="example-meta">${escapeHtml([example.source, example.chapter || example.section.split("/").pop()].filter(Boolean).join(" · "))} · matched ${escapeHtml((example.matched_forms || []).join(", "))}</div></article>`).join("") : `<p class="section-empty">${entry.story_examples_available ? "No matching sentence was captured for this word." : "No sentence sidecar loaded. Regenerate the vocabulary with --examples-output, then restart the app."}</p>`}</section>
    <section class="section"><div class="section-heading"><h3>COMMUNITY EXAMPLES · TATOEBA</h3><small>${entry.example_count ? `${number(entry.example_count)} matches` : "tagged by lemma + type"}</small></div>${examples.length ? examples.map((example) => `<article class="example"><div class="example-es">${escapeHtml(example.spanish)}</div><div class="example-en">${escapeHtml(example.english)}</div><div class="example-meta">${escapeHtml(example.attribution)}</div></article>`).join("") : '<p class="section-empty">No community example matched this exact lemma and part of speech.</p>'}</section>
    <p class="copy-note">Copy fields includes the headword, type, story count, and observed forms.</p>
  </div>`;
}

async function selectEntry(rank) {
  state.selectedRank = rank;
  const requestId = ++state.detailRequest;
  renderRows();
  document.querySelector(`tr[data-rank="${rank}"]`)?.focus();
  $("#detail-pane").innerHTML = '<div class="empty-state"><p class="eyebrow">A CLOSER LOOK</p><h2>Gathering the details…</h2><p>Looking through the local dictionary and example sentences.</p></div>';
  try {
    const response = await fetch(`/api/entry?rank=${encodeURIComponent(rank)}`);
    if (!response.ok) throw new Error("Could not load this entry");
    if (requestId !== state.detailRequest) return;
    renderDetail(await response.json());
  } catch (error) {
    if (requestId !== state.detailRequest) return;
    $("#detail-pane").innerHTML = `<div class="empty-state"><h2>Entry unavailable.</h2><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function toggleSaved(rank) {
  const row = state.rows.find((item) => item.rank === rank);
  if (!row) return;
  const key = wordKey(row);
  if (state.saved.has(key)) state.saved.delete(key);
  else state.saved.add(key);
  let persisted = true;
  try { localStorage.setItem(SAVED_KEY, JSON.stringify([...state.saved])); }
  catch { persisted = false; }
  renderRows();
  if (state.selectedRank === rank) {
    const detail = $("#detail-pane");
    const button = detail.querySelector(".detail-save");
    if (button) {
      const isSaved = state.saved.has(key);
      button.classList.toggle("is-saved", isSaved);
      button.setAttribute("aria-pressed", String(isSaved));
      button.textContent = isSaved ? "★ Saved" : "☆ Save word";
    }
  }
  showToast(persisted ? (state.saved.has(key) ? "Word saved" : "Word removed from saved list") : "Saved for this session only");
}

function setStatus(rank, status) {
  const row = state.rows.find((item) => item.rank === rank);
  if (!row) return;
  const key = wordKey(row);
  if (status) state.statuses[key] = status;
  else delete state.statuses[key];
  let persisted = true;
  try { localStorage.setItem(STATUS_KEY, JSON.stringify(state.statuses)); } catch { persisted = false; }
  renderRows();
  const select = $("#word-status");
  if (state.selectedRank === rank && select) select.value = status;
  showToast(persisted ? (status ? `Marked ${status}` : "Learning status cleared") : "Status updated for this session only");
}

let toastTimer;
async function copyText(button) {
  try {
    await navigator.clipboard.writeText(decodeURIComponent(button.dataset.copy));
    showToast("Study fields copied");
  } catch {
    showToast("Clipboard access is unavailable in this browser");
  }
}
function showToast(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
}

$("#search").addEventListener("input", (event) => { state.query = event.target.value; renderRows(); });
$("#pos-filter").addEventListener("change", (event) => { state.pos = event.target.value; renderRows(); });
$("#study-filter").addEventListener("change", (event) => { state.studyFilter = event.target.value; renderRows(); });
$("#sort").addEventListener("change", (event) => { state.sort = event.target.value; renderRows(); });
$("#vocab-rows").addEventListener("click", (event) => {
  const save = event.target.closest("[data-save-rank]");
  if (save) { event.stopPropagation(); toggleSaved(Number(save.dataset.saveRank)); return; }
  const row = event.target.closest("tr[data-rank]"); if (row) selectEntry(Number(row.dataset.rank));
});
$("#detail-pane").addEventListener("click", (event) => {
  const save = event.target.closest("[data-save-rank]"); if (save) { toggleSaved(Number(save.dataset.saveRank)); return; }
  const button = event.target.closest(".copy-button"); if (button) copyText(button);
});
$("#detail-pane").addEventListener("change", (event) => {
  if (event.target.id !== "word-status") return;
  setStatus(state.selectedRank, event.target.value);
});
document.addEventListener("keydown", (event) => {
  const active = document.activeElement;
  const typing = active.matches("input, textarea, select, [contenteditable='true']");
  if (event.key === "/" && !typing) { event.preventDefault(); $("#search").focus(); return; }
  if (event.key === "Escape" && active === $("#search")) { $("#search").value = ""; state.query = ""; renderRows(); $("#search").blur(); return; }
  if (typing || active.matches("button, a")) return;

  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    if (!state.filtered.length) return;
    event.preventDefault();
    const current = state.filtered.findIndex((row) => row.rank === state.selectedRank);
    const next = current < 0
      ? (event.key === "ArrowDown" ? 0 : state.filtered.length - 1)
      : Math.max(0, Math.min(state.filtered.length - 1, current + (event.key === "ArrowDown" ? 1 : -1)));
    selectEntry(state.filtered[next].rank);
    return;
  }
  if (event.key === "Enter" && state.selectedRank !== null) {
    event.preventDefault();
    selectEntry(state.selectedRank);
    return;
  }
  if (state.selectedRank === null) return;
  const key = event.key.toLocaleLowerCase();
  if (key === "k") { event.preventDefault(); setStatus(state.selectedRank, "known"); }
  else if (key === "l") { event.preventDefault(); setStatus(state.selectedRank, "learning"); }
  else if (key === "u") { event.preventDefault(); setStatus(state.selectedRank, ""); }
  else if (key === "s") { event.preventDefault(); toggleSaved(state.selectedRank); }
  else if (key === "c") {
    const button = $("#detail-pane .copy-button");
    if (button) { event.preventDefault(); copyText(button); }
  }
});
init();
