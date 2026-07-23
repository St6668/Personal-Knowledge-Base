/* ═══════════════════════════════════════════════════════════════════
   chat.js — AI 对话页交互逻辑（含 SSE 流式消息处理）
   ═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  let _currentConvId = null;
  let _currentConvMode = null;
  let _currentStreamingMessageEl = null;
  let _isStreaming = false;

  /* ── DOM 引用 ────────────────────────────────────────────────── */
  const convListEl = document.getElementById('conv-list');
  const chatMessagesEl = document.getElementById('chat-messages');
  const chatHeaderTitle = document.getElementById('chat-header-title');
  const chatHeaderBadge = document.getElementById('chat-header-badge');
  const chatEmptyEl = document.getElementById('chat-empty');
  const messageInput = document.getElementById('message-input');
  const sendBtn = document.getElementById('send-btn');
  const newConvBtn = document.getElementById('btn-new-conv');

  /* ── 初始化 ──────────────────────────────────────────────────── */
  function init() {
    loadConversations();
    bindSendMessage();
    if (newConvBtn) newConvBtn.addEventListener('click', openNewConvModal);
  }

  /* ── 加载对话列表 ────────────────────────────────────────────── */
  async function loadConversations() {
    try {
      const data = await App.fetchJSON('/chat/conversations');
      renderConvList(data);
    } catch (err) {
      App.toast('加载对话列表失败: ' + err.message, 'error');
    }
  }

  function renderConvList(convs) {
    if (!convListEl) return;

    if (convs.length === 0) {
      convListEl.innerHTML = '<div class="text-center text-muted text-sm" style="padding:24px;">暂无对话</div>';
      return;
    }

    convListEl.innerHTML = convs.map(c => `
      <div class="chat-conv-item ${c.id === _currentConvId ? 'active' : ''}" data-conv-id="${c.id}">
        <span class="chat-conv-title" title="${App.escapeHtml(c.title)}">${App.escapeHtml(c.title)}</span>
        <span class="chat-conv-mode">${getModeLabel(c.mode)}</span>
        <button class="chat-conv-delete" title="删除对话" data-delete-id="${c.id}">&times;</button>
      </div>
    `).join('');

    // 绑定点击
    convListEl.querySelectorAll('.chat-conv-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.chat-conv-delete')) return;
        selectConversation(parseInt(item.dataset.convId));
      });
    });

    // 绑定删除
    convListEl.querySelectorAll('.chat-conv-delete').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteConversation(parseInt(btn.dataset.deleteId));
      });
    });
  }

  function getModeLabel(mode) {
    const labels = { kb_qa: '知识库问答', free_chat: '自由对话', scope_locked: '范围锁定' };
    return labels[mode] || mode;
  }

  /* ── 选中对话并加载历史 ──────────────────────────────────────── */
  async function selectConversation(convId) {
    _currentConvId = convId;
    updateConvActiveState();
    showChatView();

    try {
      const data = await App.fetchJSON(`/chat/conversations/${convId}`);
      _currentConvMode = data.mode;
      renderMessages(data.messages || []);
      updateChatHeader(data);
    } catch (err) {
      App.toast('加载对话失败: ' + err.message, 'error');
    }
  }

  function updateConvActiveState() {
    if (!convListEl) return;
    convListEl.querySelectorAll('.chat-conv-item').forEach(item => {
      item.classList.toggle('active', parseInt(item.dataset.convId) === _currentConvId);
    });
  }

  function showChatView() {
    if (chatEmptyEl) chatEmptyEl.style.display = 'none';
    if (chatMessagesEl) chatMessagesEl.style.display = 'flex';
    // 启用输入框和发送按钮
    if (messageInput) messageInput.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
  }

  function showEmptyView() {
    if (chatEmptyEl) chatEmptyEl.style.display = 'flex';
    if (chatMessagesEl) chatMessagesEl.style.display = 'none';
    if (chatHeaderTitle) chatHeaderTitle.textContent = 'AI 对话';
    if (chatHeaderBadge) chatHeaderBadge.textContent = '';
  }

  function updateChatHeader(data) {
    if (chatHeaderTitle) chatHeaderTitle.textContent = data.title || '新对话';
    if (chatHeaderBadge) chatHeaderBadge.textContent = getModeLabel(data.mode);
  }

  /* ── 渲染消息列表 ────────────────────────────────────────────── */
  function renderMessages(messages) {
    if (!chatMessagesEl) return;

    if (messages.length === 0) {
      chatMessagesEl.innerHTML = '';
      return;
    }

    chatMessagesEl.innerHTML = messages.map(m => createMessageHTML(m)).join('');
    scrollToBottom();
  }

  function createMessageHTML(msg) {
    const role = msg.role === 'user' ? 'user' : 'assistant';
    const roleLabel = msg.role === 'user' ? '你' : 'AI';

    let refsHTML = '';
    if (msg.referenced_docs) {
      try {
        const refs = typeof msg.referenced_docs === 'string'
          ? JSON.parse(msg.referenced_docs)
          : msg.referenced_docs;
        if (Array.isArray(refs) && refs.length > 0) {
          refsHTML = `<div class="message-references">
            <span style="font-size:0.72rem;color:var(--text-muted);">📎 引用：</span>
            ${refs.map(r => `<span class="ref-tag">📄 ${App.escapeHtml(typeof r === 'string' ? r : r.title || r)}</span>`).join('')}
          </div>`;
        }
      } catch (_) { /* 引用格式错误，忽略 */ }
    }

    return `
      <div class="message ${role}">
        <div class="message-bubble">${App.renderMarkdown(msg.content)}</div>
        <div class="message-meta">${roleLabel} · ${App.timeAgo(msg.created_at)}</div>
        ${refsHTML}
      </div>`;
  }

  /* ── 发送消息 ────────────────────────────────────────────────── */
  function bindSendMessage() {
    if (!sendBtn) return;

    sendBtn.addEventListener('click', () => sendMessage());

    if (messageInput) {
      messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
    }
  }

  async function sendMessage() {
    if (_isStreaming) return;
    if (!_currentConvId) {
      App.toast('请先选择或创建一个对话', 'info');
      return;
    }

    const content = messageInput.value.trim();
    if (!content) return;

    // 禁用输入
    messageInput.value = '';
    messageInput.disabled = true;
    sendBtn.disabled = true;

    // 添加用户消息
    appendUserMessage(content);

    // 添加 AI 消息占位
    const aiMsgEl = appendAIMessagePlaceholder();
    _currentStreamingMessageEl = aiMsgEl;
    _isStreaming = true;

    try {
      // 使用 fetch 读取 SSE 流（POST 不支持 EventSource）
      const resp = await fetch(`/chat/conversations/${_currentConvId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: '请求失败' }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const data = JSON.parse(jsonStr);
              if (data.type === 'chunk') {
                fullContent += data.content;
                updateStreamingBubble(aiMsgEl, fullContent);
              } else if (data.type === 'done') {
                finishStreaming(aiMsgEl, fullContent);
              } else if (data.type === 'error') {
                throw new Error(data.content || 'AI 回复错误');
              }
            } catch (parseErr) {
              if (parseErr.message && !parseErr.message.includes('JSON')) {
                throw parseErr;
              }
            }
          }
        }
      }

      // 处理剩余 buffer
      if (buffer.startsWith('data: ')) {
        try {
          const data = JSON.parse(buffer.slice(6));
          if (data.type === 'done') {
            finishStreaming(aiMsgEl, fullContent);
          }
        } catch (_) { /* ignore */ }
      }

    } catch (err) {
      if (_currentStreamingMessageEl) {
        _currentStreamingMessageEl.querySelector('.message-bubble').innerHTML =
          `<span style="color:var(--cinnabar);">错误: ${App.escapeHtml(err.message)}</span>`;
        _currentStreamingMessageEl.querySelector('.message-bubble').classList.remove('streaming-cursor');
      }
      App.toast('发送失败: ' + err.message, 'error');
    } finally {
      _isStreaming = false;
      _currentStreamingMessageEl = null;
      messageInput.disabled = false;
      sendBtn.disabled = false;
      messageInput.focus();
    }
  }

  function appendUserMessage(content) {
    if (!chatMessagesEl) return;
    const el = document.createElement('div');
    el.innerHTML = createMessageHTML({ role: 'user', content, created_at: new Date().toISOString() });
    chatMessagesEl.appendChild(el.firstElementChild);
    scrollToBottom();
  }

  function appendAIMessagePlaceholder() {
    if (!chatMessagesEl) return null;
    const el = document.createElement('div');
    el.className = 'message assistant';
    el.innerHTML = `
      <div class="message-bubble streaming-cursor"></div>
      <div class="message-meta">AI · 正在生成...</div>
    `;
    chatMessagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function updateStreamingBubble(el, content) {
    if (!el) return;
    const bubble = el.querySelector('.message-bubble');
    if (bubble) {
      bubble.innerHTML = App.renderMarkdown(content);
      bubble.classList.add('streaming-cursor');
    }
    scrollToBottom();
  }

  function finishStreaming(el, content) {
    if (!el) return;
    const bubble = el.querySelector('.message-bubble');
    if (bubble) {
      bubble.innerHTML = App.renderMarkdown(content);
      bubble.classList.remove('streaming-cursor');
    }
    const meta = el.querySelector('.message-meta');
    if (meta) {
      meta.textContent = 'AI · 刚刚';
    }
    scrollToBottom();

    // 刷新对话列表以更新标题
    setTimeout(() => loadConversations(), 500);
  }

  function scrollToBottom() {
    if (chatMessagesEl) {
      chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    }
  }

  /* ── 新建对话 ────────────────────────────────────────────────── */
  function openNewConvModal() {
    const formEl = document.createElement('div');
    formEl.innerHTML = `
      <div class="form-group">
        <label class="form-label">对话模式</label>
        <select class="form-select" id="new-conv-mode">
          <option value="kb_qa">知识库问答 — 基于全部知识库检索回答</option>
          <option value="free_chat">自由对话 — 不检索知识库，直接对话</option>
          <option value="scope_locked">范围锁定 — 仅在某知识库内检索</option>
        </select>
      </div>
      <div class="form-group" id="kb-select-group" style="display:none;">
        <label class="form-label">锁定知识库</label>
        <select class="form-select" id="new-conv-kb-id">
          <option value="">加载中...</option>
        </select>
      </div>
    `;

    // 监听模式切换
    let modalInstance;
    setTimeout(() => {
      const modeSelect = document.getElementById('new-conv-mode');
      const kbGroup = document.getElementById('kb-select-group');
      if (modeSelect && kbGroup) {
        modeSelect.addEventListener('change', () => {
          kbGroup.style.display = modeSelect.value === 'scope_locked' ? 'block' : 'none';
        });
      }
    }, 50);

    // 加载知识库列表
    loadKbOptions();

    modalInstance = App.createModal({
      title: '新建对话',
      body: formEl,
      buttons: [
        { text: '取消', cls: 'btn-secondary', closeOnClick: true },
        {
          text: '创建',
          cls: 'btn-primary',
          closeOnClick: false,
          onClick: async () => {
            const mode = document.getElementById('new-conv-mode').value;
            const body = { mode };

            if (mode === 'scope_locked') {
              const kbId = document.getElementById('new-conv-kb-id').value;
              if (!kbId) { App.toast('请选择知识库', 'error'); return; }
              body.kb_id = parseInt(kbId);
            }

            try {
              const conv = await App.postJSON('/chat/conversations', body);
              App.toast('对话创建成功', 'success');
              await loadConversations();
              selectConversation(conv.id);
            } catch (err) {
              App.toast('创建失败: ' + err.message, 'error');
            }
          },
        },
      ],
    });
    modalInstance.show();
  }

  async function loadKbOptions() {
    try {
      const kbs = await App.fetchJSON('/knowledge/kb');
      const select = document.getElementById('new-conv-kb-id');
      if (select) {
        select.innerHTML = kbs.map(kb => `<option value="${kb.id}">${App.escapeHtml(kb.name)}</option>`).join('');
      }
    } catch (_) {
      const select = document.getElementById('new-conv-kb-id');
      if (select) select.innerHTML = '<option value="">加载失败</option>';
    }
  }

  /* ── 删除对话 ────────────────────────────────────────────────── */
  async function deleteConversation(convId) {
    const confirmed = await App.confirm('确定要删除此对话吗？');
    if (!confirmed) return;

    try {
      await App.del(`/chat/conversations/${convId}`);
      App.toast('对话已删除', 'success');

      if (_currentConvId === convId) {
        _currentConvId = null;
        _currentConvMode = null;
        showEmptyView();
        if (chatMessagesEl) chatMessagesEl.innerHTML = '';
      }

      await loadConversations();
    } catch (err) {
      App.toast('删除失败: ' + err.message, 'error');
    }
  }

  // 启动
  init();
})();
