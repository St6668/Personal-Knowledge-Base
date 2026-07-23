/* ═══════════════════════════════════════════════════════════════════
   knowledge.js — 知识管理页交互逻辑
   ═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  let _currentKbId = null;
  let _knowledgeBases = [];
  let _documents = [];

  /* ── DOM 引用 ────────────────────────────────────────────────── */
  const kbListEl = document.getElementById('kb-list');
  const docGridEl = document.getElementById('doc-grid');
  const docCountEl = document.getElementById('doc-count');
  const searchInput = document.getElementById('search-input');
  const searchResultsEl = document.getElementById('search-results');
  const uploadBtn = document.getElementById('btn-upload');
  const newNoteBtn = document.getElementById('btn-new-note');
  const newKbBtn = document.getElementById('btn-new-kb');

  /* ── 初始化 ──────────────────────────────────────────────────── */
  function init() {
    loadKnowledgeBases();
    bindSearch();
    if (uploadBtn) uploadBtn.addEventListener('click', openUploadModal);
    if (newNoteBtn) newNoteBtn.addEventListener('click', openNoteModal);
    if (newKbBtn) newKbBtn.addEventListener('click', openCreateKbModal);
  }

  /* ── 加载知识库列表 ──────────────────────────────────────────── */
  async function loadKnowledgeBases() {
    try {
      const data = await App.fetchJSON('/knowledge/kb');
      _knowledgeBases = data;
      renderKbList();
      // 默认选中第一个
      if (data.length > 0 && _currentKbId === null) {
        selectKb(data[0].id);
      } else if (data.length === 0) {
        _currentKbId = null;
        renderDocuments([]);
      }
    } catch (err) {
      App.toast('加载知识库失败: ' + err.message, 'error');
    }
  }

  function renderKbList() {
    if (!kbListEl) return;

    if (_knowledgeBases.length === 0) {
      kbListEl.innerHTML = '<div class="empty-state"><div class="empty-state-desc">暂无知识库</div></div>';
      return;
    }

    kbListEl.innerHTML = _knowledgeBases.map(kb => `
      <div class="kb-item ${kb.id === _currentKbId ? 'active' : ''}" data-kb-id="${kb.id}">
        <span class="kb-item-name">
          <span>📁</span>
          <span>${App.escapeHtml(kb.name)}</span>
        </span>
        <span class="kb-item-count">${kb.document_count}</span>
      </div>
    `).join('');

    // 绑定点击事件
    kbListEl.querySelectorAll('.kb-item').forEach(item => {
      item.addEventListener('click', () => selectKb(parseInt(item.dataset.kbId)));
    });
  }

  /* ── 选中知识库并加载文档 ────────────────────────────────────── */
  function selectKb(kbId) {
    _currentKbId = kbId;
    renderKbList();
    loadDocuments(kbId);
  }

  async function loadDocuments(kbId) {
    if (!docGridEl) return;

    docGridEl.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>加载文档中...</span></div>';

    try {
      // 调用 API 获取该知识库下的文档列表
      const docs = await App.fetchJSON(`/knowledge/documents?kb_id=${kbId}`);
      renderDocuments(docs);

      if (docCountEl) {
        docCountEl.textContent = `${docs.length} 个文档`;
      }
    } catch (err) {
      App.toast('加载文档失败: ' + err.message, 'error');
      renderDocuments([]);
    }
  }

  function renderDocuments(docs) {
    if (!docGridEl) return;

    _documents = docs;

    if (docs.length === 0) {
      docGridEl.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-state-icon">📄</div>
          <div class="empty-state-title">暂无文档</div>
          <div class="empty-state-desc">上传文档或创建笔记来开始构建知识库</div>
        </div>`;
      return;
    }

    docGridEl.innerHTML = docs.map(doc => `
      <div class="card doc-card" data-doc-id="${doc.id}">
        <div class="card-header">
          <span class="card-title truncate">${getDocIcon(doc.doc_type)} ${App.escapeHtml(doc.title)}</span>
        </div>
        <div class="card-meta">
          <span class="doc-type-badge doc-type-${doc.doc_type}">${doc.doc_type.toUpperCase()}</span>
        </div>
        ${doc.tags && doc.tags.length > 0 ? `
          <div class="flex gap-xs mt-sm" style="flex-wrap:wrap;">
            ${doc.tags.map(t => `<span class="tag">${App.escapeHtml(t)}</span>`).join('')}
          </div>
        ` : ''}
        <div class="card-footer">
          <span class="text-xs text-muted">${App.formatDate(doc.created_at)}</span>
          <div class="flex gap-xs">
            <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); KnowledgePage.viewDocument(${doc.id})" title="查看">👁</button>
            <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); KnowledgePage.deleteDocument(${doc.id})" title="删除">🗑</button>
          </div>
        </div>
      </div>
    `).join('');

    // 绑定卡片点击事件
    docGridEl.querySelectorAll('.doc-card').forEach(card => {
      card.addEventListener('click', () => {
        KnowledgePage.viewDocument(parseInt(card.dataset.docId));
      });
    });
  }

  function getDocIcon(docType) {
    const icons = {
      pdf: '📕',
      word: '📘',
      txt: '📄',
      markdown: '📝',
      note: '📒',
      xmind: '🧠',
    };
    return icons[docType] || '📄';
  }

  /* ── 查看文档详情 ────────────────────────────────────────────── */
  async function viewDocument(docId) {
    try {
      const doc = await App.fetchJSON(`/knowledge/document/${docId}`);

      // 合并所有分块为完整内容（按序号排序）
      const fullText = (doc.chunks || [])
        .sort((a, b) => a.chunk_index - b.chunk_index)
        .map(c => c.content)
        .join('\n\n');

      const modal = App.createModal({
        title: `${getDocIcon(doc.doc_type)} ${doc.title}`,
        body: `
          <div class="flex gap-sm mb-md" style="flex-wrap:wrap;">
            <span class="doc-type-badge doc-type-${doc.doc_type}">${doc.doc_type.toUpperCase()}</span>
            ${doc.tags.map(t => `<span class="tag">${App.escapeHtml(t)}</span>`).join('')}
          </div>
          <div class="text-sm text-muted mb-sm">创建于 ${App.formatDate(doc.created_at)}</div>
          <div class="doc-preview-content">${App.renderMarkdown(fullText)}</div>
        `,
        buttons: [
          { text: '关闭', cls: 'btn-secondary' },
        ],
      });
      modal.show();
    } catch (err) {
      App.toast('查看文档失败: ' + err.message, 'error');
    }
  }

  /* ── 删除文档 ────────────────────────────────────────────────── */
  async function deleteDocument(docId) {
    const confirmed = await App.confirm('确定要删除此文档吗？此操作不可恢复。');
    if (!confirmed) return;

    try {
      await App.del(`/knowledge/document/${docId}`);
      App.toast('文档已删除', 'success');
      if (_currentKbId) {
        loadKnowledgeBases();
        loadDocuments(_currentKbId);
      }
    } catch (err) {
      App.toast('删除失败: ' + err.message, 'error');
    }
  }

  /* ── 上传文档 ────────────────────────────────────────────────── */
  function openUploadModal() {
    if (_knowledgeBases.length === 0) {
      App.toast('请先创建知识库', 'info');
      return;
    }

    const formEl = document.createElement('div');
    formEl.innerHTML = `
      <div class="form-group">
        <label class="form-label">选择知识库</label>
        <select class="form-select" id="upload-kb-select">
          ${_knowledgeBases.map(kb => `<option value="${kb.id}">${App.escapeHtml(kb.name)}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">选择文件</label>
        <input type="file" class="form-input" id="upload-file-input" accept=".pdf,.docx,.doc,.txt,.md,.markdown,.xmind">
        <div class="form-hint">支持 PDF、Word、TXT、Markdown、XMind 格式</div>
      </div>
      <div class="form-group">
        <label class="form-label">标签（可选）</label>
        <input type="text" class="form-input" id="upload-tags-input" placeholder="多个标签用逗号分隔，如：Python, 后端">
      </div>
    `;

    let uploading = false;
    const modal = App.createModal({
      title: '上传文档',
      body: formEl,
      buttons: [
        { text: '取消', cls: 'btn-secondary', closeOnClick: true },
        {
          text: '上传',
          cls: 'btn-primary',
          closeOnClick: false,
          onClick: async () => {
            if (uploading) return;
            const kbId = document.getElementById('upload-kb-select').value;
            const fileInput = document.getElementById('upload-file-input');
            const tagsInput = document.getElementById('upload-tags-input');

            if (!fileInput.files || fileInput.files.length === 0) {
              App.toast('请选择文件', 'error');
              return;
            }

            uploading = true;
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('kb_id', kbId);
            if (tagsInput.value.trim()) {
              formData.append('tags', tagsInput.value.trim());
            }

            try {
              await App.fetchJSON('/knowledge/upload', {
                method: 'POST',
                body: formData,
                headers: {},  // let browser set Content-Type for multipart
              });
              App.toast('上传成功', 'success');
              modal.close();
              loadKnowledgeBases();
              if (_currentKbId) loadDocuments(_currentKbId);
              else selectKb(parseInt(kbId));
            } catch (err) {
              App.toast('上传失败: ' + err.message, 'error');
            } finally {
              uploading = false;
            }
          },
        },
      ],
    });
    modal.show();
  }

  /* ── 新建笔记 ────────────────────────────────────────────────── */
  function openNoteModal() {
    if (_knowledgeBases.length === 0) {
      App.toast('请先创建知识库', 'info');
      return;
    }

    const formEl = document.createElement('div');
    formEl.innerHTML = `
      <div class="form-group">
        <label class="form-label">选择知识库</label>
        <select class="form-select" id="note-kb-select">
          ${_knowledgeBases.map(kb => `<option value="${kb.id}" ${kb.id === _currentKbId ? 'selected' : ''}>${App.escapeHtml(kb.name)}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">笔记标题</label>
        <input type="text" class="form-input" id="note-title-input" placeholder="输入笔记标题">
      </div>
      <div class="form-group">
        <label class="form-label">笔记内容（支持 Markdown）</label>
        <textarea class="form-textarea" id="note-content-input" rows="8" placeholder="在此编写笔记内容..."></textarea>
      </div>
      <div class="form-group">
        <label class="form-label">标签（可选）</label>
        <input type="text" class="form-input" id="note-tags-input" placeholder="多个标签用逗号分隔">
      </div>
    `;

    let saving = false;
    const modal = App.createModal({
      title: '新建笔记',
      body: formEl,
      buttons: [
        { text: '取消', cls: 'btn-secondary', closeOnClick: true },
        {
          text: '保存',
          cls: 'btn-primary',
          closeOnClick: false,
          onClick: async () => {
            if (saving) return;
            const kbId = document.getElementById('note-kb-select').value;
            const title = document.getElementById('note-title-input').value.trim();
            const content = document.getElementById('note-content-input').value.trim();
            const tags = document.getElementById('note-tags-input').value.trim();

            if (!title) { App.toast('请输入标题', 'error'); return; }
            if (!content) { App.toast('请输入内容', 'error'); return; }

            saving = true;
            const formData = new FormData();
            formData.append('title', title);
            formData.append('content', content);
            formData.append('kb_id', kbId);
            if (tags) formData.append('tags', tags);

            try {
              await App.fetchJSON('/knowledge/note', {
                method: 'POST',
                body: formData,
                headers: {},
              });
              App.toast('笔记创建成功', 'success');
              modal.close();
              loadKnowledgeBases();
              if (_currentKbId) loadDocuments(_currentKbId);
            } catch (err) {
              App.toast('创建失败: ' + err.message, 'error');
            } finally {
              saving = false;
            }
          },
        },
      ],
    });
    modal.show();
  }

  /* ── 创建知识库 ──────────────────────────────────────────────── */
  function openCreateKbModal() {
    const formEl = document.createElement('div');
    formEl.innerHTML = `
      <div class="form-group">
        <label class="form-label">知识库名称</label>
        <input type="text" class="form-input" id="kb-name-input" placeholder="如：编程知识、历史笔记">
      </div>
      <div class="form-group">
        <label class="form-label">描述（可选）</label>
        <textarea class="form-textarea" id="kb-desc-input" rows="3" placeholder="简短描述知识库的内容"></textarea>
      </div>
    `;

    let saving = false;
    const modal = App.createModal({
      title: '新建知识库',
      body: formEl,
      buttons: [
        { text: '取消', cls: 'btn-secondary', closeOnClick: true },
        {
          text: '创建',
          cls: 'btn-primary',
          closeOnClick: false,
          onClick: async () => {
            if (saving) return;
            const name = document.getElementById('kb-name-input').value.trim();
            const desc = document.getElementById('kb-desc-input').value.trim();

            if (!name) { App.toast('请输入知识库名称', 'error'); return; }

            saving = true;
            const formData = new FormData();
            formData.append('name', name);
            if (desc) formData.append('description', desc);

            try {
              const kb = await App.fetchJSON('/knowledge/kb', {
                method: 'POST',
                body: formData,
                headers: {},
              });
              App.toast('知识库创建成功', 'success');
              modal.close();
              await loadKnowledgeBases();
              selectKb(kb.id);
            } catch (err) {
              App.toast('创建失败: ' + err.message, 'error');
            } finally {
              saving = false;
            }
          },
        },
      ],
    });
    modal.show();
  }

  /* ── 删除知识库 ──────────────────────────────────────────────── */
  async function deleteKnowledgeBase(kbId) {
    const confirmed = await App.confirm('确定要删除此知识库及其所有文档吗？此操作不可恢复。');
    if (!confirmed) return;

    try {
      await App.del(`/knowledge/kb/${kbId}`);
      App.toast('知识库已删除', 'success');
      _currentKbId = null;
      await loadKnowledgeBases();
      if (_knowledgeBases.length > 0) {
        selectKb(_knowledgeBases[0].id);
      }
    } catch (err) {
      App.toast('删除失败: ' + err.message, 'error');
    }
  }

  /* ── 搜索 ────────────────────────────────────────────────────── */
  function bindSearch() {
    if (!searchInput) return;

    const debouncedSearch = App.debounce(async (query) => {
      if (!query.trim()) {
        if (searchResultsEl) searchResultsEl.classList.remove('visible');
        return;
      }

      try {
        const results = await App.fetchJSON(`/knowledge/search?q=${encodeURIComponent(query)}&top_k=8`);
        renderSearchResults(results);
      } catch (err) {
        // 搜索错误静默处理
        if (searchResultsEl) searchResultsEl.classList.remove('visible');
      }
    }, 400);

    searchInput.addEventListener('input', () => {
      debouncedSearch(searchInput.value);
    });

    // 点击外部关闭搜索结果
    document.addEventListener('click', (e) => {
      if (searchResultsEl && !searchResultsEl.contains(e.target) && e.target !== searchInput) {
        searchResultsEl.classList.remove('visible');
      }
    });
  }

  function renderSearchResults(results) {
    if (!searchResultsEl) return;

    if (results.length === 0) {
      searchResultsEl.innerHTML = '<div class="search-result-item text-muted text-sm">未找到匹配结果</div>';
    } else {
      searchResultsEl.innerHTML = results.map(r => `
        <div class="search-result-item" data-doc-id="${r.document_id}">
          <div class="search-result-title">${App.escapeHtml(r.document_title)}</div>
          <div class="search-result-snippet">${App.escapeHtml(r.content.substring(0, 150))}</div>
          <div class="search-result-score">相关度: ${(r.score * 100).toFixed(0)}%</div>
        </div>
      `).join('');

      // 点击结果查看文档
      searchResultsEl.querySelectorAll('.search-result-item').forEach(item => {
        item.addEventListener('click', () => {
          viewDocument(parseInt(item.dataset.docId));
          searchResultsEl.classList.remove('visible');
          if (searchInput) searchInput.value = '';
        });
      });
    }

    searchResultsEl.classList.add('visible');
  }

  /* ── 公开方法 ────────────────────────────────────────────────── */
  window.KnowledgePage = {
    viewDocument,
    deleteDocument,
    deleteKnowledgeBase,
  };

  // 启动
  init();
})();
