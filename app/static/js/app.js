/* ═══════════════════════════════════════════════════════════════════
   app.js — 个人知识库系统 通用工具函数
   ═══════════════════════════════════════════════════════════════════ */

const App = (() => {
  'use strict';

  /* ── Toast 通知 ──────────────────────────────────────────────── */
  let _toastContainer = null;

  function getToastContainer() {
    if (!_toastContainer) {
      _toastContainer = document.createElement('div');
      _toastContainer.className = 'toast-container';
      document.body.appendChild(_toastContainer);
    }
    return _toastContainer;
  }

  /**
   * 显示一条短暂的通知消息
   * @param {string} message - 消息文本
   * @param {'success'|'error'|'info'} type - 消息类型
   * @param {number} duration - 显示时长（毫秒），默认 3000
   */
  function toast(message, type = 'info', duration = 3000) {
    const container = getToastContainer();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;

    const icons = { success: '✔', error: '✘', info: 'ℹ' };
    el.innerHTML = `<span>${icons[type] || ''}</span><span>${escapeHtml(message)}</span>`;

    container.appendChild(el);

    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateX(40px)';
      el.style.transition = 'all 200ms ease';
      setTimeout(() => el.remove(), 200);
    }, duration);
  }

  /* ── Fetch 封装 ──────────────────────────────────────────────── */
  /**
   * 带错误处理的 JSON fetch
   * @param {string} url
   * @param {object} options - fetch options
   * @returns {Promise<any>}
   */
  async function fetchJSON(url, options = {}) {
    const defaultHeaders = {
      'Accept': 'application/json',
    };

    // 非 GET/HEAD 请求，若非 FormData 则默认 Content-Type
    if (options.method && options.method.toUpperCase() !== 'GET' && options.method.toUpperCase() !== 'HEAD') {
      if (!(options.body instanceof FormData)) {
        defaultHeaders['Content-Type'] = 'application/json';
      }
    }

    const resp = await fetch(url, {
      ...options,
      headers: {
        ...defaultHeaders,
        ...(options.headers || {}),
      },
    });

    if (!resp.ok) {
      let errMsg = `请求失败 (${resp.status})`;
      try {
        const errBody = await resp.json();
        errMsg = errBody.detail || errBody.message || errMsg;
      } catch (_) {
        // 非 JSON 错误响应
      }
      throw new Error(errMsg);
    }

    // 204 No Content
    if (resp.status === 204) return null;

    return resp.json();
  }

  /**
   * POST JSON 数据
   */
  function postJSON(url, data) {
    return fetchJSON(url, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /**
   * PUT JSON 数据
   */
  function putJSON(url, data) {
    return fetchJSON(url, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * DELETE 请求
   */
  function del(url) {
    return fetchJSON(url, { method: 'DELETE' });
  }

  /* ── 模态框 ──────────────────────────────────────────────────── */
  /**
   * 创建一个模态框并返回控制方法
   * @param {object} opts
   * @param {string} opts.title - 标题
   * @param {string|HTMLElement} opts.body - 内容
   * @param {Array<{text:string, cls:string, onClick:function}>} opts.buttons - 按钮
   * @param {function} opts.onClose - 关闭回调
   * @returns {{ show: function, close: function, overlay: HTMLElement }}
   */
  function createModal(opts = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    const modal = document.createElement('div');
    modal.className = 'modal';

    let bodyHTML = '';
    if (opts.title) {
      bodyHTML += `
        <div class="modal-header">
          <h2>${escapeHtml(opts.title)}</h2>
          <button class="modal-close">&times;</button>
        </div>`;
    }
    bodyHTML += `<div class="modal-body"></div>`;

    if (opts.buttons && opts.buttons.length > 0) {
      bodyHTML += '<div class="modal-footer">';
      opts.buttons.forEach(btn => {
        bodyHTML += `<button class="btn ${btn.cls || 'btn-secondary'}" data-action="${btn.text}">${escapeHtml(btn.text)}</button>`;
      });
      bodyHTML += '</div>';
    }

    modal.innerHTML = bodyHTML;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // 设置 body 内容
    const bodyEl = modal.querySelector('.modal-body');
    if (typeof opts.body === 'string') {
      bodyEl.innerHTML = opts.body;
    } else if (opts.body instanceof HTMLElement) {
      bodyEl.appendChild(opts.body);
    }

    // 关闭按钮
    const closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => close());
    }

    // 点击遮罩关闭
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });

    // 按钮事件
    if (opts.buttons) {
      opts.buttons.forEach(btn => {
        const btnEl = modal.querySelector(`[data-action="${btn.text}"]`);
        if (btnEl) {
          btnEl.addEventListener('click', () => {
            if (btn.onClick) btn.onClick();
            if (btn.closeOnClick !== false) close();
          });
        }
      });
    }

    function show() {
      overlay.classList.add('visible');
    }

    function close() {
      overlay.classList.remove('visible');
      if (opts.onClose) opts.onClose();
      setTimeout(() => overlay.remove(), 250);
    }

    return { show, close, overlay, modal };
  }

  /**
   * 确认对话框快捷方法
   * @param {string} message
   * @returns {Promise<boolean>}
   */
  function confirm(message) {
    return new Promise((resolve) => {
      const modal = createModal({
        title: '确认操作',
        body: `<div class="confirm-dialog">
          <div class="confirm-dialog-icon">&#9888;</div>
          <div class="confirm-dialog-message">${escapeHtml(message)}</div>
        </div>`,
        buttons: [
          { text: '取消', cls: 'btn-secondary', onClick: () => resolve(false) },
          { text: '确认', cls: 'btn-primary', onClick: () => resolve(true) },
        ],
      });
      modal.show();
    });
  }

  /* ── 日期格式化 ──────────────────────────────────────────────── */
  /**
   * 将 ISO 日期字符串格式化为友好的中文日期
   * @param {string} isoString
   * @returns {string}
   */
  function formatDate(isoString) {
    if (!isoString) return '-';
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '-';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${y}-${m}-${day} ${h}:${min}`;
  }

  /**
   * 相对时间（如 "3分钟前"）
   * @param {string} isoString
   * @returns {string}
   */
  function timeAgo(isoString) {
    if (!isoString) return '-';
    const now = Date.now();
    const then = new Date(isoString).getTime();
    const diff = Math.floor((now - then) / 1000);

    if (diff < 60) return '刚刚';
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}天前`;
    return formatDate(isoString);
  }

  /* ── HTML 转义 ───────────────────────────────────────────────── */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /* ── Markdown 简单渲染 ───────────────────────────────────────── */
  /**
   * 将简单 Markdown 转为 HTML（支持 **粗体**、*斜体*、`代码`、```代码块```、换行）
   * @param {string} md
   * @returns {string}
   */
  function renderMarkdown(md) {
    if (!md) return '';
    let html = escapeHtml(md);

    // 代码块（需在行内代码之前处理）
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code style="background:var(--paper-subtle);padding:1px 5px;border-radius:3px;font-family:var(--font-mono);font-size:0.85em;">$1</code>');

    // 粗体
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // 斜体
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // 换行
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  /* ── 防抖 ────────────────────────────────────────────────────── */
  function debounce(fn, delay = 300) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /* ── SSE 连接 ────────────────────────────────────────────────── */
  /**
   * 创建 SSE EventSource 连接并处理事件
   * @param {string} url
   * @param {object} handlers - { onChunk, onDone, onError }
   * @returns {EventSource}
   */
  function createSSE(url, handlers = {}) {
    const es = new EventSource(url);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'chunk':
            if (handlers.onChunk) handlers.onChunk(data.content);
            break;
          case 'done':
            if (handlers.onDone) handlers.onDone(data.content);
            es.close();
            break;
          case 'error':
            if (handlers.onError) handlers.onError(data.content);
            es.close();
            break;
          case 'heartbeat':
            // 心跳，忽略
            break;
          default:
            if (handlers.onChunk) handlers.onChunk(data.content || '');
        }
      } catch (_) {
        // 解析出错，忽略
      }
    };

    es.onerror = () => {
      if (handlers.onError) handlers.onError('SSE 连接中断');
      es.close();
    };

    return es;
  }

  /* ── 公开 API ────────────────────────────────────────────────── */
  return {
    toast,
    fetchJSON,
    postJSON,
    putJSON,
    del,
    createModal,
    confirm,
    formatDate,
    timeAgo,
    escapeHtml,
    renderMarkdown,
    debounce,
    createSSE,
  };
})();
