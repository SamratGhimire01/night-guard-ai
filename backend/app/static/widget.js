(function () {
  "use strict";

  var scriptEl = document.currentScript;
  if (!scriptEl) return;

  var businessId = scriptEl.getAttribute("data-business-id");
  if (!businessId) {
    console.error("Night Guard AI widget: missing data-business-id on the <script> tag.");
    return;
  }

  var apiBase = new URL(scriptEl.src).origin;
  var endpoint = apiBase + "/api/v1/widget/" + encodeURIComponent(businessId) + "/messages";
  var storageKey = "nightguard_widget_session_" + businessId;

  function getSessionToken() {
    try {
      return window.localStorage.getItem(storageKey);
    } catch (e) {
      return null;
    }
  }

  function setSessionToken(token) {
    try {
      window.localStorage.setItem(storageKey, token);
    } catch (e) {
      /* localStorage unavailable (private mode, etc.) — session just won't persist across reloads */
    }
  }

  // ---- minimal UI, injected once, no external CSS/JS dependency ----

  var style = document.createElement("style");
  style.textContent =
    "#ng-widget-bubble{position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;" +
    "background:#2563eb;color:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;" +
    "box-shadow:0 2px 10px rgba(0,0,0,.2);font-family:sans-serif;font-size:24px;z-index:999999;}" +
    "#ng-widget-panel{position:fixed;bottom:86px;right:20px;width:320px;max-height:440px;background:#fff;" +
    "border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.25);display:none;flex-direction:column;" +
    "font-family:sans-serif;overflow:hidden;z-index:999999;}" +
    "#ng-widget-header{background:#2563eb;color:#fff;padding:10px 14px;font-size:14px;font-weight:600;}" +
    "#ng-widget-messages{flex:1;overflow-y:auto;padding:10px;font-size:13px;background:#f8fafc;min-height:200px;max-height:320px;}" +
    ".ng-msg{margin:6px 0;padding:8px 10px;border-radius:8px;max-width:85%;line-height:1.4;white-space:pre-wrap;}" +
    ".ng-msg-customer{background:#2563eb;color:#fff;margin-left:auto;}" +
    ".ng-msg-agent{background:#e5e7eb;color:#111;margin-right:auto;}" +
    "#ng-widget-form{display:flex;border-top:1px solid #e5e7eb;}" +
    "#ng-widget-input{flex:1;border:none;padding:10px;font-size:13px;outline:none;}" +
    "#ng-widget-send{border:none;background:#2563eb;color:#fff;padding:0 14px;cursor:pointer;font-size:13px;}" +
    "#ng-widget-send:disabled{opacity:.5;cursor:default;}";
  document.head.appendChild(style);

  var bubble = document.createElement("div");
  bubble.id = "ng-widget-bubble";
  bubble.textContent = "💬"; // speech balloon emoji, no image asset needed

  var panel = document.createElement("div");
  panel.id = "ng-widget-panel";
  panel.innerHTML =
    '<div id="ng-widget-header">Chat with us</div>' +
    '<div id="ng-widget-messages"></div>' +
    '<form id="ng-widget-form">' +
    '<input id="ng-widget-input" type="text" placeholder="Type a message..." autocomplete="off" />' +
    '<button id="ng-widget-send" type="submit">Send</button>' +
    "</form>";

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  var messagesEl = panel.querySelector("#ng-widget-messages");
  var formEl = panel.querySelector("#ng-widget-form");
  var inputEl = panel.querySelector("#ng-widget-input");
  var sendEl = panel.querySelector("#ng-widget-send");

  bubble.addEventListener("click", function () {
    panel.style.display = panel.style.display === "flex" ? "none" : "flex";
    if (panel.style.display === "flex") inputEl.focus();
  });

  function appendMessage(text, sender) {
    var el = document.createElement("div");
    el.className = "ng-msg " + (sender === "customer" ? "ng-msg-customer" : "ng-msg-agent");
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  formEl.addEventListener("submit", function (event) {
    event.preventDefault();
    var content = inputEl.value.trim();
    if (!content) return;

    appendMessage(content, "customer");
    inputEl.value = "";
    inputEl.disabled = true;
    sendEl.disabled = true;

    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_token: getSessionToken(), content: content }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("request failed: " + res.status);
        return res.json();
      })
      .then(function (data) {
        setSessionToken(data.session_token);
        appendMessage(data.response, "agent");
      })
      .catch(function () {
        appendMessage("Sorry, something went wrong. Please try again in a moment.", "agent");
      })
      .finally(function () {
        inputEl.disabled = false;
        sendEl.disabled = false;
        inputEl.focus();
      });
  });
})();
