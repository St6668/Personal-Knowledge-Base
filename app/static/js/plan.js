/* ═══════════════════════════════════════════════════════════════════
   plan.js — 学习计划页交互逻辑
   ═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  let _plans = [];
  let _knowledgeBases = [];
  let _tags = [];

  /* ── DOM 引用 ────────────────────────────────────────────────── */
  const planListEl = document.getElementById('plan-list');
  const genBtn = document.getElementById('btn-generate');
  const kbSelect = document.getElementById('gen-kb-select');
  const tagSelect = document.getElementById('gen-tag-select');

  /* ── 初始化 ──────────────────────────────────────────────────── */
  function init() {
    loadPlans();
    loadGeneratorOptions();
    if (genBtn) genBtn.addEventListener('click', generatePlan);
  }

  /* ── 加载计划列表 ────────────────────────────────────────────── */
  async function loadPlans() {
    if (!planListEl) return;

    planListEl.innerHTML = '<div class="loading-state"><div class="spinner"></div><span>加载中...</span></div>';

    try {
      const data = await App.fetchJSON('/plan/plans');
      _plans = data;
      renderPlans();
    } catch (err) {
      planListEl.innerHTML = `<div class="empty-state"><div class="empty-state-desc">加载失败: ${App.escapeHtml(err.message)}</div></div>`;
    }
  }

  function renderPlans() {
    if (!planListEl) return;

    if (_plans.length === 0) {
      planListEl.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📋</div>
          <div class="empty-state-title">暂无学习计划</div>
          <div class="empty-state-desc">选择一个知识库，让 AI 帮你生成学习计划</div>
        </div>`;
      return;
    }

    planListEl.innerHTML = _plans.map(plan => `
      <div class="plan-card" data-plan-id="${plan.id}">
        <div class="plan-card-header" data-toggle-plan="${plan.id}">
          <div class="plan-card-title-section">
            <span class="plan-card-title">${App.escapeHtml(plan.title)}</span>
            <span class="tag ${plan.status === 'completed' ? 'tag-success' : 'tag-warning'}">${getStatusLabel(plan.status)}</span>
          </div>
          <div class="plan-card-actions">
            <span class="text-xs text-muted">${plan.total_modules || 0} 个模块</span>
            <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation(); PlanPage.deletePlan(${plan.id})" title="删除">🗑</button>
            <span class="plan-card-expand">▼</span>
          </div>
        </div>
        <div class="plan-modules" id="plan-modules-${plan.id}">
          <div class="loading-state"><div class="spinner spinner-sm"></div></div>
        </div>
      </div>
    `).join('');

    // 绑定展开/折叠
    planListEl.querySelectorAll('[data-toggle-plan]').forEach(header => {
      header.addEventListener('click', () => {
        const planId = parseInt(header.dataset.togglePlan);
        togglePlan(planId);
      });
    });
  }

  function getStatusLabel(status) {
    const labels = { pending: '待开始', in_progress: '进行中', completed: '已完成' };
    return labels[status] || status;
  }

  async function togglePlan(planId) {
    const card = planListEl.querySelector(`[data-plan-id="${planId}"]`);
    const modulesEl = document.getElementById(`plan-modules-${planId}`);

    if (!card || !modulesEl) return;

    if (card.classList.contains('expanded')) {
      card.classList.remove('expanded');
      return;
    }

    card.classList.add('expanded');

    // 加载模块详情
    try {
      const plan = await App.fetchJSON(`/plan/plans/${planId}`);
      renderModules(modulesEl, plan.modules || []);
    } catch (err) {
      modulesEl.innerHTML = `<div class="plan-module-item text-muted text-sm">加载失败: ${App.escapeHtml(err.message)}</div>`;
    }
  }

  function renderModules(container, modules) {
    if (modules.length === 0) {
      container.innerHTML = '<div class="plan-module-item text-muted text-sm">暂无模块</div>';
      return;
    }

    container.innerHTML = modules.map((m, idx) => {
      // 解析知识点引用
      let knowledgePoints = [];
      if (m.knowledge_refs) {
        try {
          knowledgePoints = typeof m.knowledge_refs === 'string'
            ? JSON.parse(m.knowledge_refs)
            : m.knowledge_refs;
        } catch (e) {
          knowledgePoints = [];
        }
      }

      const hasKP = knowledgePoints.length > 0;
      const kpSectionId = `module-kp-${m.id}`;

      return `
      <div class="plan-module-wrapper" data-module-id="${m.id}">
        <div class="plan-module-item">
          <div class="plan-module-index status-${m.status}">${idx + 1}</div>
          <div class="plan-module-info">
            <div class="plan-module-title">${App.escapeHtml(m.title)}</div>
            ${m.description ? `<div class="plan-module-desc">${App.escapeHtml(m.description)}</div>` : ''}
            ${hasKP ? `
              <div class="plan-module-kp-toggle" data-toggle-kp="${m.id}">
                📚 查看知识点 (${knowledgePoints.length})
                <span class="plan-module-kp-arrow">▶</span>
              </div>
            ` : ''}
          </div>
          <div class="plan-module-hours">${m.suggested_hours || 0}h</div>
          <div class="plan-module-actions">
            ${m.status !== 'completed' ? `
              <button class="btn btn-sm btn-success" onclick="PlanPage.updateModuleStatus(${m.id}, 'completed')" title="标记完成">✅</button>
            ` : ''}
            ${m.status === 'pending' ? `
              <button class="btn btn-sm btn-secondary" onclick="PlanPage.updateModuleStatus(${m.id}, 'in_progress')" title="开始学习">▶</button>
            ` : ''}
            <a href="/exam?plan_module_id=${m.id}" class="btn btn-sm btn-primary">开始考察</a>
          </div>
        </div>
        ${hasKP ? `
          <div class="plan-module-kp" id="${kpSectionId}">
            ${knowledgePoints.map((kp, kpIdx) => `
              <div class="plan-module-kp-item">
                <span class="plan-module-kp-index">知识点 ${kpIdx + 1}</span>
                <div class="plan-module-kp-text">${App.escapeHtml(kp)}</div>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
    `}).join('');

    // 绑定知识点展开/折叠
    container.querySelectorAll('[data-toggle-kp]').forEach(toggle => {
      toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const moduleId = parseInt(toggle.dataset.toggleKp);
        toggleKnowledgePoints(moduleId);
      });
    });
  }

  function toggleKnowledgePoints(moduleId) {
    const kpSection = document.getElementById(`module-kp-${moduleId}`);
    const toggle = document.querySelector(`[data-toggle-kp="${moduleId}"]`);
    if (!kpSection || !toggle) return;

    const isOpen = kpSection.classList.contains('open');
    if (isOpen) {
      kpSection.classList.remove('open');
      toggle.classList.remove('open');
    } else {
      kpSection.classList.add('open');
      toggle.classList.add('open');
    }
  }

  /* ── 更新模块状态 ────────────────────────────────────────────── */
  async function updateModuleStatus(moduleId, status) {
    try {
      await App.putJSON(`/plan/modules/${moduleId}`, { status });
      App.toast('状态已更新', 'success');
      // 重新加载对应计划
      const container = document.querySelector(`[data-module-id="${moduleId}"]`);
      if (container) {
        const planCard = container.closest('.plan-card');
        if (planCard) {
          const planId = parseInt(planCard.dataset.planId);
          const plan = await App.fetchJSON(`/plan/plans/${planId}`);
          const modulesEl = document.getElementById(`plan-modules-${planId}`);
          if (modulesEl) renderModules(modulesEl, plan.modules || []);
        }
      }
      loadPlans();
    } catch (err) {
      App.toast('更新失败: ' + err.message, 'error');
    }
  }

  /* ── 加载生成器选项（知识库 + 标签） ─────────────────────────── */
  async function loadGeneratorOptions() {
    try {
      const [kbs, tags] = await Promise.all([
        App.fetchJSON('/knowledge/kb'),
        App.fetchJSON('/knowledge/tags'),
      ]);
      _knowledgeBases = kbs;
      _tags = tags;

      if (kbSelect) {
        kbSelect.innerHTML = '<option value="">选择知识库...</option>' +
          kbs.map(kb => `<option value="${kb.id}">${App.escapeHtml(kb.name)}</option>`).join('');
      }

      if (tagSelect) {
        tagSelect.innerHTML = '<option value="">全部标签（可选）</option>' +
          tags.map(t => `<option value="${t.id}">${App.escapeHtml(t.name)}</option>`).join('');
      }
    } catch (err) {
      App.toast('加载选项失败: ' + err.message, 'error');
    }
  }

  /* ── 生成计划 ────────────────────────────────────────────────── */
  async function generatePlan() {
    if (!kbSelect) return;

    const kbId = kbSelect.value;
    if (!kbId) {
      App.toast('请先选择知识库', 'info');
      return;
    }

    const body = { kb_id: parseInt(kbId) };

    // 收集选中的标签
    if (tagSelect && tagSelect.selectedOptions) {
      const tagIds = Array.from(tagSelect.selectedOptions)
        .filter(o => o.value)
        .map(o => parseInt(o.value));
      if (tagIds.length > 0) body.tag_ids = tagIds;
    }

    genBtn.disabled = true;
    genBtn.textContent = '生成中...';

    try {
      const plan = await App.postJSON('/plan/generate', body);
      App.toast('计划生成成功！', 'success');
      await loadPlans();
      // 自动展开新计划
      setTimeout(() => {
        const card = planListEl.querySelector(`[data-plan-id="${plan.id}"]`);
        if (card) {
          card.querySelector('.plan-card-header').click();
        }
      }, 300);
    } catch (err) {
      App.toast('生成失败: ' + err.message, 'error');
    } finally {
      genBtn.disabled = false;
      genBtn.textContent = '生成计划';
    }
  }

  /* ── 删除计划 ────────────────────────────────────────────────── */
  async function deletePlan(planId) {
    const confirmed = await App.confirm('确定要删除此学习计划吗？');
    if (!confirmed) return;

    try {
      await App.del(`/plan/plans/${planId}`);
      App.toast('计划已删除', 'success');
      loadPlans();
    } catch (err) {
      App.toast('删除失败: ' + err.message, 'error');
    }
  }

  /* ── 公开方法 ────────────────────────────────────────────────── */
  window.PlanPage = {
    deletePlan,
    updateModuleStatus,
  };

  init();
})();
