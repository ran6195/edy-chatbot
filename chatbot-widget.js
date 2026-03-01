(function () {
  'use strict';

  // ── Configurazione ─────────────────────────────────────────────────────────
  var CLOUD_FUNCTION_URL = 'https://europe-west1-edy-chatbot.cloudfunctions.net/chatbot';
  var SITE_DOMAIN = window.CHATBOT_DOMAIN || window.location.hostname;
  var MAX_RETRIES = 1;

  // ── Stili ──────────────────────────────────────────────────────────────────
  var css = `
    #cb-widget-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9998;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, #667eea, #764ba2);
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 16px rgba(102,126,234,0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s;
    }
    #cb-widget-btn:hover { transform: scale(1.08); }
    #cb-widget-btn svg { width: 28px; height: 28px; fill: #fff; }

    #cb-modal {
      position: fixed;
      bottom: 92px;
      right: 24px;
      z-index: 9999;
      width: 420px;
      height: 550px;
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 8px 40px rgba(0,0,0,0.18);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 14px;
    }
    #cb-modal.cb-hidden { display: none; }

    #cb-header {
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: #fff;
      padding: 14px 18px;
      font-weight: 600;
      font-size: 15px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    #cb-close-btn {
      background: none;
      border: none;
      color: #fff;
      font-size: 22px;
      cursor: pointer;
      line-height: 1;
      padding: 0;
      opacity: 0.85;
    }
    #cb-close-btn:hover { opacity: 1; }

    #cb-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      background: #f7f8fc;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .cb-msg {
      max-width: 80%;
      padding: 10px 14px;
      border-radius: 10px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .cb-msg-user {
      align-self: flex-end;
      background: #667eea;
      color: #fff;
      border-bottom-right-radius: 3px;
    }
    .cb-msg-assistant {
      align-self: flex-start;
      background: #e8eaf6;
      color: #222;
      border-bottom-left-radius: 3px;
    }
    .cb-msg-loading {
      align-self: flex-start;
      background: #e8eaf6;
      color: #888;
      font-style: italic;
      border-bottom-left-radius: 3px;
    }

    #cb-input-area {
      display: flex;
      padding: 12px;
      gap: 8px;
      background: #fff;
      border-top: 1px solid #e0e0e0;
    }
    #cb-input {
      flex: 1;
      border: 1px solid #ccc;
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 14px;
      outline: none;
      resize: none;
      height: 38px;
      line-height: 1.4;
      transition: border-color 0.2s;
    }
    #cb-input:focus { border-color: #667eea; }
    #cb-send-btn {
      background: linear-gradient(135deg, #667eea, #764ba2);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 0 16px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      transition: opacity 0.2s;
    }
    #cb-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

    @media (max-width: 600px) {
      #cb-modal {
        width: 95vw;
        right: 2.5vw;
        bottom: 80px;
        height: 70vh;
      }
    }
  `;

  // ── Inject CSS ─────────────────────────────────────────────────────────────
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  // ── DOM ────────────────────────────────────────────────────────────────────
  var btn = document.createElement('button');
  btn.id = 'cb-widget-btn';
  btn.setAttribute('aria-label', 'Apri chat');
  btn.innerHTML = '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/></svg>';
  document.body.appendChild(btn);

  var modal = document.createElement('div');
  modal.id = 'cb-modal';
  modal.className = 'cb-hidden';
  modal.innerHTML = `
    <div id="cb-header">
      <span>Assistente Virtuale</span>
      <button id="cb-close-btn" aria-label="Chiudi">&times;</button>
    </div>
    <div id="cb-messages"></div>
    <div id="cb-input-area">
      <input id="cb-input" type="text" placeholder="Scrivi un messaggio..." autocomplete="off" />
      <button id="cb-send-btn">Invia</button>
    </div>
  `;
  document.body.appendChild(modal);

  var messagesEl = document.getElementById('cb-messages');
  var inputEl = document.getElementById('cb-input');
  var sendBtn = document.getElementById('cb-send-btn');

  // ── Helpers ────────────────────────────────────────────────────────────────
  function addMessage(text, role) {
    var div = document.createElement('div');
    div.className = 'cb-msg cb-msg-' + role;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function setLoading(active) {
    sendBtn.disabled = active;
    inputEl.disabled = active;
  }

  // ── API call con retry ─────────────────────────────────────────────────────
  function fetchAnswer(question, attempt) {
    attempt = attempt || 0;
    return fetch(CLOUD_FUNCTION_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question, site_domain: SITE_DOMAIN }),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || 'Errore del server');
        return data.answer;
      });
    }).catch(function (err) {
      if (attempt < MAX_RETRIES) return fetchAnswer(question, attempt + 1);
      throw err;
    });
  }

  // ── Invia messaggio ────────────────────────────────────────────────────────
  function sendMessage() {
    var question = inputEl.value.trim();
    if (!question) return;

    addMessage(question, 'user');
    inputEl.value = '';
    setLoading(true);

    var loadingEl = addMessage('Pensando...', 'loading');

    fetchAnswer(question)
      .then(function (answer) {
        messagesEl.removeChild(loadingEl);
        addMessage(answer, 'assistant');
      })
      .catch(function (err) {
        messagesEl.removeChild(loadingEl);
        addMessage('Errore: ' + err.message + '. Riprova tra qualche istante.', 'assistant');
      })
      .finally(function () {
        setLoading(false);
        inputEl.focus();
      });
  }

  // ── Event listeners ────────────────────────────────────────────────────────
  btn.addEventListener('click', function () {
    modal.classList.toggle('cb-hidden');
    if (!modal.classList.contains('cb-hidden')) inputEl.focus();
  });

  document.getElementById('cb-close-btn').addEventListener('click', function () {
    modal.classList.add('cb-hidden');
  });

  sendBtn.addEventListener('click', sendMessage);

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
})();
