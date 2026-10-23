const SAVED_KEY = "story-vocabulary:saved:v1";
const state = { rows: [], filtered: [], selectedRank: null, sort: "rank", query: "", pos: "", savedOnly: false, saved: new Set() };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = (value) => new Intl.NumberFormat().format(value || 0);
const prettyPos = (value) => ({v:"verb", n:"noun", adj:"adjective", adv:"adverb", art:"article", prep:"preposition", conj:"conjunction", pron:"pronoun", prop:"proper noun", "":"unclassified"}[value] || value);
const wordKey = (row) => `${row.lemma.toLocaleLowerCase()}::${row.pos}`;

try {
  const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || "[]");
  if (Array.isArray(saved)) state.saved = new Set(saved.filter((value) => typeof value === "string"));
} catch { /* The vocabulary browser still works if storage is unavailable. */ }

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
  const values = [...new Set(state.rows.map((row) => row.pos).filter(Boolean))].sort();
  $("#pos-filter").insertAdjacentHTML("beforeend", values.map((pos) => `<option value="${escapeHtml(pos)}">${escapeHtml(prettyPos(pos))}</option>`).join(""));
}

function matchesQuery(row, query) {
  if (!query) return true;
  return `${row.lemma} ${row.pos} ${row.observed_forms}`.toLocaleLowerCase().includes(query);
}

function renderRows() {
  const query = state.query.trim().toLocaleLowerCase();
  state.filtered = state.rows.filter((row) => (!state.pos || row.pos === state.pos) && (!state.savedOnly || state.saved.has(wordKey(row))) && matchesQuery(row, query));
  state.filtered.sort((a, b) => state.sort === "count" ? b.count - a.count || a.rank - b.rank : state.sort === "alpha" ? a.lemma.localeCompare(b.lemma) || a.rank - b.rank : a.rank - b.rank);
  const displayRows = state.filtered;
  $("#visible-count").textContent = `${number(state.filtered.length)} entries`;
  $(".list-footer b").textContent = state.sort === "count" ? "story frequency" : state.sort === "alpha" ? "alphabetically" : "story frequency rank";
  if (!displayRows.length) {
    $("#vocab-rows").innerHTML = '<tr><td colspan="4" class="no-results">No matching words. Try a shorter search.</td></tr>';
    return;
  }
  $("#vocab-rows").innerHTML = displayRows.map((row) => {
    const selected = row.rank === state.selectedRank ? " selected" : "";
    const forms = row.observed_forms.split(";").slice(0, 3).map((item) => item.trim().split(" (")[0]).join(" · ");
    const saved = state.saved.has(wordKey(row));
    return `<tr class="${selected}" data-rank="${row.rank}" tabindex="0" aria-label="${escapeHtml(row.lemma)}, ${number(row.count)} occurrences">
      <td class="word-cell"><span class="rank">${row.rank}</span><button class="lemma-link" type="button">${escapeHtml(row.lemma)}</button><div class="subform">${escapeHtml(forms)}</div></td>
      <td><span class="pos-pill">${escapeHtml(row.pos || "?")}</span></td><td class="numeric">${number(row.count)}</td>
      <td class="save-cell"><button class="save-star${saved ? " is-saved" : ""}" type="button" data-save-rank="${row.rank}" aria-label="${saved ? "Remove saved word" : "Save word"}" aria-pressed="${saved}" title="${saved ? "Saved" : "Save word"}">${saved ? "★" : "☆"}</button></td>
    </tr>`;
  }).join("");
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
  const spanishDictUrl = `https://www.spanishdict.com/translate/${encodeURIComponent(entry.lemma)}`;
  $("#detail-pane").innerHTML = `<div class="detail-content">
    <div class="detail-top"><span class="detail-rank">STORY FREQUENCY RANK #${entry.rank}</span><div class="detail-actions"><button class="icon-button detail-save${saved ? " is-saved" : ""}" data-save-rank="${entry.rank}" type="button" aria-pressed="${saved}">${saved ? "★ Saved" : "☆ Save word"}</button><a class="icon-button spanishdict-link" href="${escapeHtml(spanishDictUrl)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(entry.lemma)} on SpanishDict">SpanishDict ↗</a>${copyButton}</div></div>
    <h2 class="detail-title">${escapeHtml(entry.lemma)}</h2>
    <div class="detail-subtitle"><span class="pos-pill">${escapeHtml(prettyPos(entry.pos))}</span><span>Story vocabulary</span></div>
    <div class="detail-stats"><div class="stat-card"><span class="stat-label">IN YOUR STORY</span><span class="stat-value">${number(entry.count)}</span><span class="stat-caption">occurrences</span></div><div class="stat-card"><span class="stat-label">GENERAL SPANISH</span><span class="stat-value">${general.length ? number(general[0].count) : "—"}</span><span class="stat-caption">${general.length ? "corpus count" : "no exact match"}</span></div></div>
    <section class="section"><div class="section-heading"><h3>FORMS IN YOUR STORY</h3><small>${forms.length} forms</small></div>${forms.length ? `<div class="forms-list">${forms.map((form) => `<span class="form-chip">${escapeHtml(form.form)} <b>${number(form.count)}</b></span>`).join("")}</div>` : '<p class="section-empty">No observed forms recorded.</p>'}</section>
    <section class="section"><div class="section-heading"><h3>DICTIONARY</h3><small>Wiktionary-derived</small></div>${glosses.length ? `<ul class="gloss-list">${glosses.slice(0, 12).map((gloss) => `<li>${escapeHtml(gloss)}</li>`).join("")}</ul>${usage.slice(0, 2).map((note) => `<p class="usage-note">${escapeHtml(note)}</p>`).join("")}` : '<p class="section-empty">No dictionary entry found for this lemma.</p>'}</section>
    <section class="section"><div class="section-heading"><h3>GENERAL FREQUENCY</h3><small>spanish_data frequency.csv</small></div>${general.length ? `<div class="frequency-list">${general.map((item) => `<div><div class="frequency-row"><span>${number(item.count)} corpus occurrences</span><span>${escapeHtml(item.flags || "")}</span></div><div class="frequency-forms">${escapeHtml(item.usage.split("|").slice(0, 12).join(" · "))}</div></div>`).join("")}</div>` : '<p class="section-empty">No exact lemma and part-of-speech match in the general list.</p>'}</section>
    <section class="section"><div class="section-heading"><h3>EXAMPLES FROM YOUR BOOK</h3><small>${storyExamples.length ? `${storyExamples.length} excerpts` : "local EPUB"}</small></div>${storyExamples.length ? storyExamples.map((example) => `<article class="example"><div class="example-es">${escapeHtml(example.text)}</div><div class="example-meta">${escapeHtml([example.source, example.section.split("/").pop()].filter(Boolean).join(" · "))} · matched ${escapeHtml((example.matched_forms || []).join(", "))}</div></article>`).join("") : `<p class="section-empty">${entry.story_examples_available ? "No matching sentence was captured for this word." : "No sentence sidecar loaded. Regenerate the vocabulary with --examples-output, then restart the app."}</p>`}</section>
    <section class="section"><div class="section-heading"><h3>COMMUNITY EXAMPLES · TATOEBA</h3><small>${entry.example_count ? `${number(entry.example_count)} matches` : "tagged by lemma + type"}</small></div>${examples.length ? examples.map((example) => `<article class="example"><div class="example-es">${escapeHtml(example.spanish)}</div><div class="example-en">${escapeHtml(example.english)}</div><div class="example-meta">${escapeHtml(example.attribution)}</div></article>`).join("") : '<p class="section-empty">No community example matched this exact lemma and part of speech.</p>'}</section>
    <p class="copy-note">Copy fields includes the headword, type, story count, and observed forms.</p>
  </div>`;
}

async function selectEntry(rank) {
  state.selectedRank = rank;
  renderRows();
  $("#detail-pane").innerHTML = '<div class="empty-state"><p class="eyebrow">A CLOSER LOOK</p><h2>Gathering the details…</h2><p>Looking through the local dictionary and example sentences.</p></div>';
  try {
    const response = await fetch(`/api/entry?rank=${encodeURIComponent(rank)}`);
    if (!response.ok) throw new Error("Could not load this entry");
    renderDetail(await response.json());
  } catch (error) {
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
$("#saved-filter").addEventListener("change", (event) => { state.savedOnly = event.target.value === "saved"; renderRows(); });
$("#sort").addEventListener("change", (event) => { state.sort = event.target.value; renderRows(); });
$("#vocab-rows").addEventListener("click", (event) => {
  const save = event.target.closest("[data-save-rank]");
  if (save) { event.stopPropagation(); toggleSaved(Number(save.dataset.saveRank)); return; }
  const row = event.target.closest("tr[data-rank]"); if (row) selectEntry(Number(row.dataset.rank));
});
$("#vocab-rows").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr[data-rank]");
  if (event.target.closest("button")) return;
  if (row && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); selectEntry(Number(row.dataset.rank)); }
});
$("#detail-pane").addEventListener("click", (event) => {
  const save = event.target.closest("[data-save-rank]"); if (save) { toggleSaved(Number(save.dataset.saveRank)); return; }
  const button = event.target.closest(".copy-button"); if (button) copyText(button);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) { event.preventDefault(); $("#search").focus(); }
  if (event.key === "Escape" && document.activeElement === $("#search")) { $("#search").value = ""; state.query = ""; renderRows(); $("#search").blur(); }
});
init();
