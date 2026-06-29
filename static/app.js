const state = {
  allItems: [],
  queue: [],
  index: 0,
  seen: 0,
  correct: 0,
  wrong: 0,
  answered: false,
  currentDefinition: null,
  lastAnswer: null,
  mode: "all",
  restored: false,
  serverSavedAt: 0,
};

const els = {
  seen: document.getElementById("stat-seen"),
  correct: document.getElementById("stat-correct"),
  wrong: document.getElementById("stat-wrong"),
  modeAll: document.getElementById("mode-all"),
  modeMc: document.getElementById("mode-mc"),
  modeForm: document.getElementById("mode-form"),
  reset: document.getElementById("reset-progress-btn"),
  saveStatus: document.getElementById("save-status"),
  pill: document.getElementById("category-pill"),
  progress: document.getElementById("progress-text"),
  question: document.getElementById("question-area"),
  answer: document.getElementById("answer-area"),
  feedback: document.getElementById("feedback"),
  next: document.getElementById("next-btn"),
};

function normalizeAnswer(value) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function definitionSourceLabel(source) {
  if (source === "local_oxford") return "Local Oxford Dictionary";
  if (source === "local_longman") return "Local Longman Dictionary";
  if (source === "local_longman_phrasal") return "Local Longman Phrasal Verbs";
  if (source === "wiktionary_dictionary") return "FreeDictionaryAPI.com / Wiktionary";
  if (source === "free_dictionary") return "Free Dictionary API";
  if (source === "oxford") return "Oxford Dictionaries API";
  return String(source || "unknown").replaceAll("_", " ");
}

function updateStats() {
  els.seen.textContent = state.seen;
  els.correct.textContent = state.correct;
  els.wrong.textContent = state.wrong;
  const current = state.queue.length ? Math.min(state.index + 1, state.queue.length) : 0;
  els.progress.textContent = `${current} / ${state.queue.length}`;
}

function setSaveStatus(text) {
  if (els.saveStatus) {
    els.saveStatus.textContent = text;
  }
}

function setModeButtons() {
  for (const [button, value] of [
    [els.modeAll, "all"],
    [els.modeMc, "multiple_choice"],
    [els.modeForm, "word_form"],
  ]) {
    button.classList.toggle("active", state.mode === value || (state.mode === "all" && value === "all"));
  }
}

function setMode(mode) {
  state.mode = mode;
  setModeButtons();
  rebuildQueue(true);
}

function filteredItems() {
  let filtered = state.allItems;
  if (state.mode !== "all") {
    filtered = filtered.filter((item) => item.type === state.mode);
  }
  return filtered;
}

function rebuildQueue(resetStats = true) {
  const filtered = filteredItems();
  state.queue = [...filtered];
  state.index = 0;
  state.answered = false;
  if (resetStats) {
    state.seen = 0;
    state.correct = 0;
    state.wrong = 0;
  }
  saveProgress();
  renderCurrent();
}

function currentItem() {
  return state.queue[state.index];
}

async function loadDefinition(item) {
  const params = new URLSearchParams({
    word: item.lookup_word,
    pos: item.pos || "",
    meaning: item.meaning || "",
    note: item.note || "",
    sense: String(item.sense_index || 0),
  });
  const response = await fetch(`/api/definition?${params.toString()}`);
  if (!response.ok) {
    return { source: "missing", definition: "No definition found.", partOfSpeech: "" };
  }
  return response.json();
}

function progressPayload(indexOverride = null) {
  const defaultIndex = state.answered ? Math.min(state.index + 1, state.queue.length) : state.index;
  const savedIndex = indexOverride ?? defaultIndex;
  return {
    version: 3,
    mode: state.mode,
    index: Math.max(0, Math.min(savedIndex, state.queue.length)),
    seen: state.seen,
    correct: state.correct,
    wrong: state.wrong,
    queue_ids: state.queue.map((item) => item.id),
    total: state.queue.length,
    client_base_saved_at: state.serverSavedAt || 0,
  };
}

async function saveProgress(indexOverride = null) {
  if (!state.queue.length) return;
  setSaveStatus("Saving progress...");
  try {
    const response = await fetch("/api/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(progressPayload(indexOverride)),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 409 && data.progress) {
      if (restoreProgress(data.progress)) {
        renderCurrent();
        setSaveStatus("Progress synced from server");
        return;
      }
    }
    if (!response.ok) throw new Error("Progress save failed");
    state.serverSavedAt = Number(data.progress?.saved_at) || state.serverSavedAt;
    setSaveStatus("Progress saved");
  } catch {
    setSaveStatus("Progress not saved");
  }
}

async function loadSavedProgress() {
  try {
    const response = await fetch(`/api/progress?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) return null;
    const data = await response.json();
    return data.progress || null;
  } catch {
    return null;
  }
}

function restoreProgress(progress) {
  if (!progress || !Array.isArray(progress.queue_ids)) {
    return false;
  }
  const validModes = new Set(["all", "multiple_choice", "word_form"]);
  const restoredMode = validModes.has(progress.mode) ? progress.mode : "all";
  const byId = new Map(state.allItems.map((item) => [item.id, item]));
  const savedQueue = progress.queue_ids.map((id) => byId.get(id)).filter(Boolean);
  const completedCount = Math.max(0, Math.min(Number(progress.index) || 0, savedQueue.length));
  const completed = savedQueue.slice(0, completedCount);
  const completedIds = new Set(completed.map((item) => item.id));
  const orderedRemaining = state.allItems.filter((item) => {
    if (completedIds.has(item.id)) return false;
    return restoredMode === "all" || item.type === restoredMode;
  });
  const queue = [...completed, ...orderedRemaining];
  if (!queue.length) {
    return false;
  }
  state.mode = restoredMode;
  setModeButtons();
  state.queue = queue;
  state.index = completed.length;
  state.seen = Number(progress.seen) || 0;
  state.correct = Number(progress.correct) || 0;
  state.wrong = Number(progress.wrong) || 0;
  state.restored = true;
  state.serverSavedAt = Number(progress.saved_at) || 0;
  setSaveStatus("Progress restored");
  return true;
}

async function renderCurrent() {
  state.answered = false;
  state.currentDefinition = null;
  state.lastAnswer = null;
  els.next.disabled = true;
  els.feedback.className = "feedback hidden";
  els.feedback.innerHTML = "";
  els.answer.innerHTML = "";
  updateStats();

  const item = currentItem();
  if (!item) {
    els.pill.textContent = "Done";
    els.question.innerHTML = `<p class="definition">Session complete.</p>`;
    updateStats();
    saveProgress(state.queue.length);
    return;
  }

  els.pill.textContent = item.type === "word_form" ? "Word form" : "Definition";

  if (item.type === "multiple_choice") {
    els.question.innerHTML = `
      <p class="question-type">Definition</p>
      <p class="definition loading">Looking up definition...</p>
      <div class="meta">
        <span>${escapeHtml(item.pos || "word")}</span>
        <span>${escapeHtml(item.source_sheet)} row ${item.row}</span>
      </div>
    `;
    renderChoices(item);
    const definition = await loadDefinition(item);
    state.currentDefinition = definition;
    const sourceLabel = definitionSourceLabel(definition.source);
    const validSources = [
      "local_oxford",
      "local_longman",
      "local_longman_phrasal",
      "wiktionary_dictionary",
      "free_dictionary",
      "oxford",
    ];
    if (!validSources.includes(definition.source)) {
      els.question.innerHTML = `
        <p class="question-type">Definition unavailable</p>
        <p class="definition">Original word: ${escapeHtml(item.display_word)}</p>
        <div class="meta">
          <span>${escapeHtml(item.pos || "word")}</span>
          <span>${escapeHtml(item.source_sheet)} row ${item.row}</span>
        </div>
      `;
      els.answer.innerHTML = "";
      els.feedback.className = "feedback";
      els.feedback.innerHTML = `
        <h2>Definition unavailable</h2>
        <p>No English definition was found. Press Enter or use Next to continue.</p>
      `;
      els.next.disabled = false;
      return;
    }
    const sourceMarkup = definition.sourceUrl
      ? `<a class="source-link" href="${escapeHtml(definition.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(sourceLabel)}</a>`
      : `<span>${escapeHtml(sourceLabel)}</span>`;
    els.question.innerHTML = `
      <p class="question-type">Definition</p>
      <p class="definition">${escapeHtml(definition.definition)}</p>
      <div class="meta">
        <span>${escapeHtml(item.pos || "word")}</span>
        ${sourceMarkup}
        <span>${escapeHtml(item.source_sheet)} row ${item.row}</span>
      </div>
      <div class="example-hint">
        <button id="show-example-btn" class="example-button" type="button">Show example sentence</button>
        <div id="example-sentence" class="example-sentence hidden"></div>
      </div>
    `;
    document.getElementById("show-example-btn").addEventListener("click", () => showExample(item));
    return;
  }

  renderFormQuestion(item);
}

async function showExample(item) {
  const button = document.getElementById("show-example-btn");
  const panel = document.getElementById("example-sentence");
  if (!button || !panel) return;

  button.disabled = true;
  button.textContent = "Loading example...";
  panel.className = "example-sentence";
  panel.textContent = "";

  try {
    const params = new URLSearchParams({ word: item.lookup_word });
    const response = await fetch(`/api/example?${params.toString()}`);
    const result = await response.json();
    const sourceMarkup = result.sourceUrl
      ? `<a href="${escapeHtml(result.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(definitionSourceLabel(result.source))}</a>`
      : `<span>${escapeHtml(definitionSourceLabel(result.source))}</span>`;
    panel.innerHTML = `
      <p>${escapeHtml(result.example)}</p>
      ${sourceMarkup}
    `;
    button.textContent = "Example shown";
  } catch {
    panel.textContent = "Example sentence unavailable.";
    button.textContent = "Example unavailable";
  }
}

function renderChoices(item) {
  els.answer.innerHTML = "";
  item.choices.forEach((choice, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "choice-btn";
    button.dataset.choiceIndex = String(index);
    button.dataset.choice = choice;
    button.innerHTML = `<span class="choice-key">${index + 1}</span><span>${escapeHtml(choice)}</span>`;
    button.addEventListener("click", () => answerMultipleChoice(item, choice));
    els.answer.appendChild(button);
  });
}

function renderFormQuestion(item) {
  els.question.innerHTML = `
    <p class="question-type">Word form</p>
    <p class="definition">Convert "${escapeHtml(item.source_word)}" to ${escapeHtml(item.target_pos)}.</p>
    <div class="meta">
      <span>${escapeHtml(item.source_pos || "word")}</span>
      <span>${escapeHtml(item.source_sheet)} row ${item.row}</span>
    </div>
  `;
  els.answer.innerHTML = `
    <div class="form-row">
      <input id="typed-answer" class="text-input" type="text" autocomplete="off" autofocus>
      <button id="submit-typed" type="button">Check</button>
    </div>
  `;
  const input = document.getElementById("typed-answer");
  const submit = document.getElementById("submit-typed");
  submit.addEventListener("click", () => answerForm(item, input.value));
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      answerForm(item, input.value);
    }
  });
  input.focus();
}

function answerMultipleChoice(item, choice) {
  if (state.answered) return;
  const correct = normalizeAnswer(choice) === normalizeAnswer(item.display_word);
  for (const button of els.answer.querySelectorAll("button")) {
    const buttonChoice = button.dataset.choice || "";
    button.disabled = true;
    if (normalizeAnswer(buttonChoice) === normalizeAnswer(item.display_word)) {
      button.classList.add("correct");
    }
    if (buttonChoice === choice && !correct) {
      button.classList.add("wrong");
    }
  }
  finishAnswer({
    item,
    userAnswer: choice,
    correctAnswer: item.display_word,
    correct,
    choices: item.choices,
  });
}

function answerForm(item, value) {
  if (state.answered) return;
  const accepted = item.accepted_answers.map(normalizeAnswer);
  const correct = accepted.includes(normalizeAnswer(value));
  const input = document.getElementById("typed-answer");
  const submit = document.getElementById("submit-typed");
  input.disabled = true;
  submit.disabled = true;
  finishAnswer({
    item,
    userAnswer: value,
    correctAnswer: item.answer,
    correct,
    choices: [],
  });
}

function finishAnswer({ item, userAnswer, correctAnswer, correct, choices }) {
  state.answered = true;
  state.lastAnswer = { item, userAnswer, correctAnswer, correct, choices };
  state.seen += 1;
  if (correct) state.correct += 1;
  else state.wrong += 1;
  updateStats();
  els.next.disabled = false;

  els.feedback.className = `feedback ${correct ? "good" : "bad"}`;
  const choiceList = choices.length
    ? `<ul>${choices
        .map(
          (choice, index) =>
            `<li><button class="choice-definition-btn" type="button" data-choice-index="${index}">${escapeHtml(choice)}</button></li>`,
        )
        .join("")}</ul><div id="choice-definition" class="choice-definition hidden"></div>`
    : "";
  els.feedback.innerHTML = `
    <h2>${correct ? "Correct" : "Incorrect"}</h2>
    <p><strong>Correct answer:</strong> ${escapeHtml(correctAnswer)}</p>
    ${choiceList}
    ${item.type === "multiple_choice" ? '<button id="undo-choice-btn" class="undo-button" type="button">Undo choice</button>' : ""}
  `;

  for (const button of els.feedback.querySelectorAll(".choice-definition-btn")) {
    button.addEventListener("click", () => {
      const choice = choices[Number(button.dataset.choiceIndex)];
      showChoiceDefinition(choice);
    });
  }
  document.getElementById("undo-choice-btn")?.addEventListener("click", withdrawChoice);

  const saveRequest = fetch("/api/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      item,
      user_answer: userAnswer,
      correct_answer: correctAnswer,
      correct,
      choices,
      definition: state.currentDefinition,
    }),
  }).catch(() => {});
  state.lastAnswer.saveRequest = saveRequest;
  saveProgress(Math.min(state.index + 1, state.queue.length));
}

async function withdrawChoice() {
  const answer = state.lastAnswer;
  if (!answer || answer.item.type !== "multiple_choice") return;

  state.answered = false;
  state.seen = Math.max(0, state.seen - 1);
  if (answer.correct) {
    state.correct = Math.max(0, state.correct - 1);
  } else {
    state.wrong = Math.max(0, state.wrong - 1);
    await answer.saveRequest;
    fetch("/api/answer", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: answer.item.id }),
    }).catch(() => {});
  }
  state.lastAnswer = null;

  for (const button of els.answer.querySelectorAll(".choice-btn")) {
    button.disabled = false;
    button.classList.remove("correct", "wrong");
  }
  els.feedback.className = "feedback hidden";
  els.feedback.innerHTML = "";
  els.next.disabled = true;
  updateStats();
  saveProgress(state.index);
}

async function showChoiceDefinition(choice) {
  const panel = document.getElementById("choice-definition");
  if (!panel) return;

  const matchingItem = state.allItems.find(
    (item) => item.type === "multiple_choice" && normalizeAnswer(item.display_word) === normalizeAnswer(choice),
  );
  const lookup = matchingItem?.lookup_word || choice.split(/\s+\/\s+/)[0];
  const params = new URLSearchParams({
    word: lookup,
    pos: matchingItem?.pos || "",
    meaning: "",
    note: "",
    sense: "0",
  });

  panel.className = "choice-definition";
  panel.innerHTML = `<strong>${escapeHtml(choice)}</strong><p class="loading">Looking up definition...</p>`;

  try {
    const response = await fetch(`/api/definition?${params.toString()}`);
    const definition = await response.json();
    const sourceMarkup = definition.sourceUrl
      ? `<a href="${escapeHtml(definition.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(definitionSourceLabel(definition.source))}</a>`
      : `<span>${escapeHtml(definitionSourceLabel(definition.source))}</span>`;
    panel.innerHTML = `
      <strong>${escapeHtml(choice)}</strong>
      <p>${escapeHtml(definition.definition)}</p>
      ${sourceMarkup}
      <div class="choice-example">
        <button class="example-button choice-example-btn" type="button">Show example sentence</button>
        <div class="example-sentence hidden"></div>
      </div>
    `;
    const exampleButton = panel.querySelector(".choice-example-btn");
    const examplePanel = panel.querySelector(".example-sentence");
    exampleButton.addEventListener("click", () => showWordExample(lookup, exampleButton, examplePanel));
  } catch {
    panel.innerHTML = `<strong>${escapeHtml(choice)}</strong><p>Definition unavailable.</p>`;
  }
}

async function showWordExample(word, button, panel) {
  button.disabled = true;
  button.textContent = "Loading example...";
  panel.className = "example-sentence";
  panel.textContent = "";

  try {
    const params = new URLSearchParams({ word });
    const response = await fetch(`/api/example?${params.toString()}`);
    const result = await response.json();
    const sourceMarkup = result.sourceUrl
      ? `<a href="${escapeHtml(result.sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(definitionSourceLabel(result.source))}</a>`
      : `<span>${escapeHtml(definitionSourceLabel(result.source))}</span>`;
    panel.innerHTML = `
      <p>${escapeHtml(result.example)}</p>
      ${sourceMarkup}
    `;
    button.textContent = "Example shown";
  } catch {
    panel.textContent = "Example sentence unavailable.";
    button.textContent = "Example unavailable";
  }
}

function nextQuestion() {
  if (state.index < state.queue.length - 1) {
    state.index += 1;
    renderCurrent();
  } else {
    state.index = state.queue.length;
    renderCurrent();
  }
  saveProgress();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function syncProgressFromServer() {
  if (!state.allItems.length || !state.queue.length) return;
  const saved = await loadSavedProgress();
  const remoteSavedAt = Number(saved?.saved_at) || 0;
  if (remoteSavedAt && remoteSavedAt > (state.serverSavedAt || 0) && restoreProgress(saved)) {
    renderCurrent();
    setSaveStatus("Progress synced from server");
  }
}

async function init() {
  const response = await fetch("/api/items");
  const data = await response.json();
  state.allItems = data.items;
  const saved = await loadSavedProgress();
  if (restoreProgress(saved)) {
    renderCurrent();
  } else {
    rebuildQueue(true);
  }
}

els.next.addEventListener("click", nextQuestion);
els.reset.addEventListener("click", async () => {
  await fetch("/api/progress", { method: "DELETE" }).catch(() => {});
  state.serverSavedAt = 0;
  setSaveStatus("Progress reset");
  rebuildQueue(true);
});
els.modeAll.addEventListener("click", () => setMode("all"));
els.modeMc.addEventListener("click", () => setMode("multiple_choice"));
els.modeForm.addEventListener("click", () => setMode("word_form"));
document.addEventListener("keydown", (event) => {
  if (
    !state.answered &&
    currentItem()?.type === "multiple_choice" &&
    /^[1-5]$/.test(event.key) &&
    !event.target.matches("input, textarea")
  ) {
    const button = els.answer.querySelector(`[data-choice-index="${Number(event.key) - 1}"]`);
    if (button && !button.disabled) {
      event.preventDefault();
      button.click();
    }
    return;
  }
  if (event.key !== "Enter" || event.repeat || els.next.disabled) return;
  if (event.target.matches("input, textarea")) return;
  event.preventDefault();
  nextQuestion();
});

function saveProgressBeforeExit() {
  if (!state.queue.length) return;
  const payload = JSON.stringify(progressPayload());
  navigator.sendBeacon("/api/progress", new Blob([payload], { type: "application/json" }));
}

window.addEventListener("pagehide", saveProgressBeforeExit);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    saveProgressBeforeExit();
  } else {
    syncProgressFromServer();
  }
});
window.addEventListener("focus", syncProgressFromServer);

init().catch((error) => {
  els.question.innerHTML = `<p class="definition">Could not load quiz data.</p><p>${escapeHtml(error.message)}</p>`;
});
