"use strict";

const $ = (selector) => document.querySelector(selector);
let currentTopic = null;
let allTopics = [];
let busy = false;

async function api(path, method = "GET", body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) {
    const detail = typeof result.detail === "string"
      ? result.detail : "输入内容不符合要求，请检查各项字段。";
    throw new Error(detail);
  }
  return result;
}

function notify(message, success = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("success", success);
  notice.hidden = false;
}

function setBusy(value) {
  busy = value;
  document.querySelectorAll("button").forEach((button) => { button.disabled = value; });
  $("#message-input").disabled = value || Boolean(currentTopic?.confirmed);
  $("#send-message").disabled = value || Boolean(currentTopic?.confirmed);
  $("#chat-status").textContent = value
    ? "正在检索相关论文并整理研究思路…"
    : currentTopic?.confirmed ? "选题已敲定，讨论记录保存在本地" : "可以从兴趣、现有资源或一个疑问说起";
}

async function perform(action) {
  if (busy) return;
  $("#notice").hidden = true;
  setBusy(true);
  try {
    await action();
  } catch (error) {
    notify(error.message || "请求未完成，请检查本地服务是否正在运行。");
  } finally {
    setBusy(false);
  }
}

function showPage(page) {
  const isTopic = page === "topics";
  $("#topic-view").hidden = !isTopic;
  $("#workbench-view").hidden = isTopic;
  $("#topic-nav").classList.toggle("active", isTopic);
  $("#workbench-nav").classList.toggle("active", !isTopic);
  $("#breadcrumb").textContent = `${isTopic ? "选题" : "研究工作台"} / ${currentTopic?.draft?.title || "新的研究方向"}`;
  document.title = `论文研究工作台 · ${isTopic ? "选题" : "研究档案"}`;
  if (location.hash !== `#${page}`) location.hash = page;
}

function renderTopicList() {
  const list = $("#topic-list");
  list.replaceChildren();
  if (!allTopics.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "还没有选题，从讨论开始。";
    list.append(empty);
    return;
  }
  for (const topic of allTopics) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "saved-topic";
    button.classList.toggle("selected", topic.id === currentTopic?.id);
    const title = document.createElement("span");
    title.textContent = topic.draft?.title || topic.existing_title || topic.messages[0]?.content || "新的选题讨论";
    button.title = title.textContent;
    const state = document.createElement("small");
    state.textContent = topic.confirmed ? "已敲定 · 本地档案" : "讨论中";
    button.append(title, state);
    button.addEventListener("click", () => perform(async () => {
      currentTopic = await api(`/api/topics/${topic.id}`);
      render();
      showPage(currentTopic.confirmed ? "workbench" : "topics");
    }));
    list.append(button);
  }
}

function renderMessages() {
  const area = $("#messages");
  area.replaceChildren();
  if (!currentTopic?.messages.length) {
    const welcome = document.createElement("div");
    welcome.className = "chat-welcome";
    const line = document.createElement("div");
    line.className = "welcome-line";
    const heading = document.createElement("h3");
    heading.textContent = "你想研究什么？";
    const text = document.createElement("p");
    text.textContent = "说说你关注的方向、已有的数据或可用的计算资源。选题 Agent 会检索相关论文，和你一起明确研究问题。";
    welcome.append(line, heading, text);
    area.append(welcome);
  }
  for (const message of currentTopic?.messages || []) {
    const article = document.createElement("article");
    article.className = `chat-message ${message.role}`;
    const speaker = document.createElement("div");
    speaker.className = "speaker";
    speaker.textContent = message.role === "user" ? "你" : "选题 Agent";
    const text = document.createElement("p");
    text.textContent = message.content;
    article.append(speaker, text);
    area.append(article);
  }
  area.scrollTop = area.scrollHeight;
}

function renderPapers(container, papers) {
  container.replaceChildren();
  if (!papers.length) {
    const text = document.createElement("p");
    text.className = "muted";
    text.textContent = currentTopic?.messages.length
      ? "当前检索没有找到论文，可以补充更具体的关键词。" : "发送研究方向后开始检索相关论文。";
    container.append(text);
    return;
  }
  for (const paper of papers) {
    const card = document.createElement("article");
    card.className = "paper-card";
    const link = document.createElement("a");
    link.textContent = paper.title;
    link.href = paper.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const meta = document.createElement("div");
    meta.className = "paper-meta";
    meta.textContent = `arXiv:${paper.paper_id} · ${paper.published}`;
    const authors = document.createElement("small");
    authors.textContent = paper.authors.join(", ");
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "查看摘要";
    const abstract = document.createElement("p");
    abstract.textContent = paper.abstract;
    details.append(summary, abstract);
    card.append(link, meta, authors, details);
    container.append(card);
  }
}

function renderDraft() {
  const draft = currentTopic?.draft;
  $("#draft-empty").hidden = Boolean(draft);
  $("#draft-form").hidden = !draft;
  $("#draft-state").textContent = currentTopic?.confirmed ? "已敲定" : draft ? "可修改" : "待形成";
  if (draft) {
    $("#draft-title").value = draft.title;
    $("#draft-question").value = draft.research_question;
    $("#draft-innovations").value = draft.innovation_points.join("\n");
    $("#draft-experiment").value = draft.experiment_plan;
    $("#draft-resources").value = draft.resources;
  }
  $("#confirm-topic").hidden = Boolean(currentTopic?.confirmed);
  $("#draft-form").querySelectorAll("textarea").forEach((field) => { field.readOnly = Boolean(currentTopic?.confirmed); });
  const papers = currentTopic?.papers || [];
  $("#paper-count").textContent = `${papers.length} 篇`;
  renderPapers($("#topic-papers"), papers);
}

function renderWorkbench() {
  const ready = Boolean(currentTopic?.confirmed && currentTopic?.draft);
  $("#workbench-empty").hidden = ready;
  $("#workbench-content").hidden = !ready;
  $("#workbench-title").textContent = ready ? currentTopic.draft.title : "研究工作台";
  $("#workbench-description").textContent = ready
    ? "选题已保存，可以查看研究档案并配置后续任务。" : "先敲定一个选题，再查看研究档案与任务配置。";
  if (!ready) return;
  const { draft, configuration, papers } = currentTopic;
  renderPapers($("#workbench-papers"), papers);
  $("#experiment-plan").textContent = draft.experiment_plan;
  $("#experiment-resources").textContent = draft.resources;
  $("#research-question").textContent = draft.research_question;
  $("#innovation-list").replaceChildren(...draft.innovation_points.map((point) => {
    const item = document.createElement("li");
    item.textContent = point;
    return item;
  }));
  const form = $("#configuration-form");
  for (const name of ["language", "purpose", "target", "execution", "max_minutes", "max_experiments", "max_model_calls"]) {
    form.elements.namedItem(name).value = configuration[name] ?? "";
  }
  form.querySelectorAll("[name=formats]").forEach((checkbox) => {
    checkbox.checked = configuration.formats.includes(checkbox.value);
  });
}

function render() {
  renderTopicList();
  renderMessages();
  renderDraft();
  renderWorkbench();
}

async function refreshTopics() {
  allTopics = await api("/api/topics");
  renderTopicList();
}

async function sendDiscussion(text) {
  if (!currentTopic) {
    currentTopic = await api("/api/topics", "POST", {});
  }
  currentTopic = await api(`/api/topics/${currentTopic.id}/messages`, "POST", { message: text });
  $("#message-input").value = "";
  await refreshTopics();
  render();
}

$("#message-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("#message-input").value.trim();
  if (text) perform(() => sendDiscussion(text));
});

$("#draft-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const draft = {
    title: $("#draft-title").value.trim(),
    research_question: $("#draft-question").value.trim(),
    innovation_points: $("#draft-innovations").value.split("\n").map((value) => value.trim()).filter(Boolean),
    experiment_plan: $("#draft-experiment").value.trim(),
    resources: $("#draft-resources").value.trim(),
  };
  perform(async () => {
    currentTopic = await api(`/api/topics/${currentTopic.id}/confirm`, "POST", draft);
    await refreshTopics();
    render();
    showPage("workbench");
    notify("选题档案已保存到本地。", true);
  });
});

$("#configuration-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const configuration = Object.fromEntries(data.entries());
  configuration.formats = data.getAll("formats");
  for (const name of ["max_minutes", "max_experiments", "max_model_calls"]) {
    configuration[name] = data.get(name) ? Number(data.get(name)) : null;
  }
  if (!configuration.formats.length) {
    notify("请至少选择一种交付格式。");
    return;
  }
  perform(async () => {
    currentTopic = await api(`/api/topics/${currentTopic.id}/configuration`, "PUT", configuration);
    renderWorkbench();
    notify("任务配置已保存。", true);
  });
});

$("#new-topic").addEventListener("click", () => {
  if (busy) return;
  currentTopic = null;
  $("#message-input").value = "";
  $("#notice").hidden = true;
  render();
  setBusy(false);
  showPage("topics");
});

$("#existing-topic").addEventListener("click", () => $("#existing-dialog").showModal());
$("#cancel-existing").addEventListener("click", () => $("#existing-dialog").close());
$("#existing-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const title = $("#existing-title").value.trim();
  if (!title) return;
  $("#existing-dialog").close();
  perform(async () => {
    currentTopic = await api("/api/topics", "POST", { existing_title: title });
    render();
    showPage("topics");
    const text = `我的选题已经确定：${title}。请保持题目，检索相关论文并整理完整选题档案，不需要重新选题。`;
    // Retain the submitted text in the composer if an upstream request fails.
    $("#message-input").value = text;
    await sendDiscussion(text);
  });
});

$("#topic-nav").addEventListener("click", () => showPage("topics"));
$("#workbench-nav").addEventListener("click", () => showPage("workbench"));
$("#back-to-topic").addEventListener("click", () => showPage("topics"));
$("#go-to-topic").addEventListener("click", () => showPage("topics"));
document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    for (const tab of document.querySelectorAll("[data-tab]")) {
      const active = tab === button;
      tab.setAttribute("aria-selected", String(active));
      $(`#${tab.dataset.tab}-panel`).hidden = !active;
    }
  });
});
window.addEventListener("hashchange", () => showPage(location.hash === "#workbench" ? "workbench" : "topics"));

render();
showPage(location.hash === "#workbench" ? "workbench" : "topics");
perform(refreshTopics);
