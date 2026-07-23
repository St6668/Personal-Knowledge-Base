/* ═══════════════════════════════════════════════════════════════════
   exam.js — 考察页交互逻辑（进度追踪、答题、AI 评判）
   ═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  let _session = null;
  let _questions = [];
  let _currentQuestionIndex = 0;
  let _isSubmitting = false;

  /* ── DOM 引用 ────────────────────────────────────────────────── */
  const examContainer = document.getElementById('exam-container');
  const progressFill = document.getElementById('progress-fill');
  const progressLabel = document.getElementById('progress-label');
  const questionArea = document.getElementById('question-area');
  const answerTextarea = document.getElementById('answer-textarea');
  const submitBtn = document.getElementById('submit-btn');
  const finishBtn = document.getElementById('finish-btn');
  const evaluationArea = document.getElementById('evaluation-area');
  const reportArea = document.getElementById('report-area');

  /* ── 初始化 ──────────────────────────────────────────────────── */
  function init() {
    // 检查 URL 参数：是否从计划模块跳转过来
    const params = new URLSearchParams(window.location.search);
    const planModuleId = params.get('plan_module_id');

    if (planModuleId) {
      startExamWithModule(parseInt(planModuleId));
    } else {
      showStartForm();
    }

    if (submitBtn) submitBtn.addEventListener('click', submitAnswer);
    if (finishBtn) finishBtn.addEventListener('click', finishExam);

    if (answerTextarea) {
      answerTextarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
          e.preventDefault();
          submitAnswer();
        }
      });
    }
  }

  /* ── 开始考察表单 ────────────────────────────────────────────── */
  function showStartForm() {
    if (!examContainer) return;

    examContainer.innerHTML = `
      <div class="card" style="max-width:560px;margin:0 auto;">
        <h3 style="font-family:var(--font-display);margin-bottom:var(--space-md);">开始新考察</h3>
        <div class="form-group">
          <label class="form-label">计划模块 ID（可选）</label>
          <input type="number" class="form-input" id="start-module-id" placeholder="留空为自由考察">
        </div>
        <div class="form-group">
          <label class="form-label">考察范围描述（可选）</label>
          <input type="text" class="form-input" id="start-scope-desc" placeholder="如：Python 基础语法">
        </div>
        <div class="form-group">
          <label class="form-label">题目数量</label>
          <input type="number" class="form-input" id="start-q-count" value="5" min="1" max="20" style="width:120px;">
        </div>
        <button class="btn btn-primary btn-lg w-full" id="start-exam-btn">开始考察</button>
      </div>
    `;

    document.getElementById('start-exam-btn').addEventListener('click', async () => {
      const moduleId = document.getElementById('start-module-id').value;
      const scopeDesc = document.getElementById('start-scope-desc').value.trim();
      const qCount = parseInt(document.getElementById('start-q-count').value) || 5;

      const body = { question_count: qCount };
      if (moduleId) body.plan_module_id = parseInt(moduleId);
      if (scopeDesc) body.scope_description = scopeDesc;

      try {
        const session = await App.postJSON('/exam/start', body);
        await loadSession(session.id);
      } catch (err) {
        App.toast('创建考察失败: ' + err.message, 'error');
      }
    });
  }

  async function startExamWithModule(planModuleId) {
    if (!examContainer) return;

    examContainer.innerHTML = '<div class="loading-state"><div class="spinner spinner-lg"></div><span>正在准备考察...</span></div>';

    try {
      const session = await App.postJSON('/exam/start', {
        plan_module_id: planModuleId,
        question_count: 5,
      });
      await loadSession(session.id);
    } catch (err) {
      examContainer.innerHTML = `<div class="empty-state">
        <div class="empty-state-desc">创建考察失败: ${App.escapeHtml(err.message)}</div>
        <button class="btn btn-secondary mt-md" onclick="location.reload()">重试</button>
      </div>`;
    }
  }

  /* ── 加载考察会话 ────────────────────────────────────────────── */
  async function loadSession(sessionId) {
    try {
      _session = await App.fetchJSON(`/exam/sessions/${sessionId}`);
      _questions = _session.questions || [];
      _currentQuestionIndex = 0;

      if (_session.status === 'completed') {
        renderReport();
        return;
      }

      renderExamUI();

      // 如果还没有题目，自动获取第一题
      if (_questions.length === 0) {
        await fetchNextQuestion();
      }
    } catch (err) {
      if (examContainer) {
        examContainer.innerHTML = `<div class="empty-state">
          <div class="empty-state-desc">加载失败: ${App.escapeHtml(err.message)}</div>
        </div>`;
      }
    }
  }

  /* ── 获取下一题（SSE 流式） ───────────────────────────────────── */
  async function fetchNextQuestion() {
    try {
      const response = await fetch(`/exam/sessions/${_session.id}/next-question`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'chunk') {
              fullText += data.content;
              // 实时更新题目显示
              updateQuestionPreview(fullText);
            } else if (data.type === 'done') {
              fullText = data.content;
              // 题目生成完成，刷新会话数据
              await refreshSession();
            } else if (data.type === 'error') {
              App.toast('出题失败: ' + data.content, 'error');
            }
          } catch (_) { /* 忽略解析失败的行 */ }
        }
      }
    } catch (err) {
      App.toast('获取题目失败: ' + err.message, 'error');
    }
  }

  /* ── 实时更新题目预览 ──────────────────────────────────────────── */
  function updateQuestionPreview(text) {
    const questionArea = document.getElementById('question-area');
    if (!questionArea) return;

    // 首次收到文本时，切换 loading → 题目显示
    if (questionArea.querySelector('.loading-state')) {
      questionArea.innerHTML = `
        <div class="exam-question-role">
          <span>🤖</span> 面试官提问
        </div>
        <div class="exam-question-text" id="question-text-stream">${App.escapeHtml(text)}</div>
      `;
    } else {
      const textEl = document.getElementById('question-text-stream');
      if (textEl) {
        textEl.textContent = text;
      }
    }
  }

  /* ── 刷新会话数据 ─────────────────────────────────────────────── */
  async function refreshSession() {
    try {
      _session = await App.fetchJSON(`/exam/sessions/${_session.id}`);
      _questions = _session.questions || [];
      _currentQuestionIndex = _questions.length > 0 ? _questions.length - 1 : 0;
      renderExamUI();
    } catch (err) {
      App.toast('刷新失败: ' + err.message, 'error');
    }
  }

  /* ── 渲染考察界面 ────────────────────────────────────────────── */
  function renderExamUI() {
    if (!examContainer) return;

    const currentQ = _questions[_currentQuestionIndex];
    const totalQuestions = _session.question_count || _questions.length;
    // 进度基于已答题数 —— 提交最后一道题答案后即时同步到 100%
    const answeredCount = _questions.filter(q => q.user_answer).length;
    const progress = totalQuestions > 0 ? Math.round((answeredCount / totalQuestions) * 100) : 0;

    examContainer.innerHTML = `
      <div class="exam-layout">
        <!-- 进度条 -->
        <div class="card exam-progress-card">
          <div class="progress-info">
            <span class="progress-label">已答 ${answeredCount}/${totalQuestions} 题 · 当前第 ${_currentQuestionIndex + 1} 题</span>
            <span class="progress-value">${progress}%</span>
          </div>
          <div class="progress-bar-container">
            <div class="progress-bar-fill" style="width:${progress}%"></div>
          </div>
          ${_session.scope_description ? `<div class="text-xs text-muted mt-sm">考察范围：${App.escapeHtml(_session.scope_description)}</div>` : ''}
        </div>

        <!-- 题目区 -->
        <div id="question-area" class="exam-question-card">
          ${currentQ ? `
            <div class="exam-question-role">
              <span>🤖</span> 面试官提问
            </div>
            <div class="exam-question-text">${App.escapeHtml(currentQ.question_text)}</div>
          ` : `
            <div class="loading-state">
              <div class="spinner"></div>
              <span>正在获取下一题...</span>
            </div>
          `}
        </div>

        <!-- 回答区 -->
        ${currentQ && !currentQ.user_answer ? `
          <div class="exam-answer-card">
            <div class="form-label mb-sm">你的回答</div>
            <textarea class="form-textarea" id="answer-textarea" rows="6" placeholder="请输入你的回答...（Ctrl + Enter 提交）"></textarea>
            <div class="flex justify-between items-center mt-md">
              <span class="text-xs text-muted">支持 Markdown 格式，Ctrl+Enter 提交</span>
              <button class="btn btn-primary" id="submit-btn">提交回答</button>
            </div>
          </div>
        ` : ''}

        <!-- 评判区 -->
        <div id="evaluation-area">
          ${currentQ && currentQ.ai_evaluation ? renderEvaluationHTML(currentQ) : ''}
        </div>

        <!-- 操作按钮 -->
        <div class="flex justify-between mt-lg">
          ${currentQ && currentQ.user_answer && _currentQuestionIndex < totalQuestions - 1 ? `
            <button class="btn btn-secondary" id="next-question-btn">下一题 →</button>
          ` : ''}
          <button class="btn btn-danger" id="finish-btn">结束考察</button>
        </div>
      </div>
    `;

    // 重新绑定事件
    const newSubmitBtn = document.getElementById('submit-btn');
    const newFinishBtn = document.getElementById('finish-btn');
    const newTextarea = document.getElementById('answer-textarea');
    const nextBtn = document.getElementById('next-question-btn');

    if (newSubmitBtn) newSubmitBtn.addEventListener('click', submitAnswer);
    if (newFinishBtn) newFinishBtn.addEventListener('click', finishExam);
    if (newTextarea) {
      newTextarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.ctrlKey) {
          e.preventDefault();
          submitAnswer();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', async () => {
        _currentQuestionIndex++;
        renderExamUI();
        // 自动获取下一题
        await fetchNextQuestion();
      });
    }
  }

  function renderEvaluationHTML(question) {
    let scoreClass = 'mid';
    if (question.score >= 80) scoreClass = '';
    else if (question.score < 60) scoreClass = 'low';

    let evaluationText = '';
    let followupText = '';

    if (question.ai_evaluation) {
      try {
        const evalData = typeof question.ai_evaluation === 'string'
          ? JSON.parse(question.ai_evaluation)
          : question.ai_evaluation;
        evaluationText = evalData.evaluation || evalData.comment || question.ai_evaluation;
        followupText = evalData.follow_up || evalData.next_action || '';
      } catch (_) {
        evaluationText = question.ai_evaluation;
      }
    }

    return `
      <div class="exam-evaluation-card">
        <div style="display:flex;align-items:center;gap:var(--space-sm);margin-bottom:var(--space-sm);">
          <span style="font-size:0.85rem;font-weight:600;color:var(--text-heading);">📊 AI 评判</span>
        </div>
        ${question.score != null ? `
          <div class="exam-evaluation-score ${scoreClass}">${question.score}/100</div>
        ` : ''}
        <div class="exam-evaluation-text">${App.renderMarkdown(evaluationText)}</div>
        ${followupText ? `
          <div class="exam-evaluation-followup">
            <strong>🔍 追问：</strong>${App.escapeHtml(followupText)}
          </div>
        ` : ''}
      </div>
    `;
  }

  /* ── 提交回答 ────────────────────────────────────────────────── */
  async function submitAnswer() {
    if (_isSubmitting) return;

    const textarea = document.getElementById('answer-textarea');
    if (!textarea) return;

    const answer = textarea.value.trim();
    if (!answer) {
      App.toast('请输入你的回答', 'info');
      return;
    }

    _isSubmitting = true;
    const submitBtnEl = document.getElementById('submit-btn');
    if (submitBtnEl) {
      submitBtnEl.disabled = true;
      submitBtnEl.textContent = '评判中...';
    }

    try {
      const result = await App.postJSON(`/exam/sessions/${_session.id}/answer`, {
        question_index: _currentQuestionIndex,
        answer: answer,
      });

      // 更新本地数据
      if (_questions[_currentQuestionIndex]) {
        _questions[_currentQuestionIndex].user_answer = answer;
        _questions[_currentQuestionIndex].ai_evaluation = JSON.stringify(result);
        _questions[_currentQuestionIndex].score = result.score;
      }

      // 刷新界面
      renderExamUI();
    } catch (err) {
      App.toast('提交失败: ' + err.message, 'error');
    } finally {
      _isSubmitting = false;
    }
  }

  /* ── 结束考察 ────────────────────────────────────────────────── */
  async function finishExam() {
    const confirmed = await App.confirm('确定要结束考察吗？未回答的题目将不计分。');
    if (!confirmed) return;

    // 显示加载提示 —— AI 生成报告需要较长时间，避免用户误以为卡死
    if (examContainer) {
      examContainer.innerHTML = `
        <div class="loading-state" style="padding:var(--space-3xl);min-height:400px;">
          <div class="spinner spinner-lg"></div>
          <span style="font-size:1.05rem;font-weight:600;color:var(--text-heading);margin-top:var(--space-lg);">
            考察报告生成中...
          </span>
          <span class="text-sm text-muted" style="margin-top:var(--space-sm);max-width:360px;text-align:center;">
            AI 正在综合分析你的答题表现，生成综合评价、标准答案和知识延伸，请稍候
          </span>
        </div>
      `;
    }

    try {
      await App.postJSON(`/exam/sessions/${_session.id}/finish`, {});
      // 重新加载会话以获取标准答案和延伸知识
      _session = await App.fetchJSON(`/exam/sessions/${_session.id}`);
      renderReport();
    } catch (err) {
      App.toast('结束失败: ' + err.message, 'error');
      // 恢复考察界面
      renderExamUI();
    }
  }

  /* ── 渲染考察报告 ────────────────────────────────────────────── */
  function renderReport() {
    if (!examContainer) return;

    const score = _session.score;
    let scoreClass = 'mid';
    let scoreLabel = '良好';
    if (score >= 85) { scoreClass = ''; scoreLabel = '优秀'; }
    else if (score < 60) { scoreClass = 'low'; scoreLabel = '需要加强'; }

    const questions = _session.questions || _questions || [];
    const answeredCount = questions.filter(q => q.user_answer).length;
    const totalQuestions = questions.length || _session.question_count || 0;

    let reportHTML = `
      <div class="exam-layout">
        <h2 style="font-family:var(--font-display);font-size:1.5rem;margin-bottom:var(--space-lg);">📊 考察报告</h2>

        <div class="exam-report-summary">
          <div class="exam-report-stat">
            <div class="exam-report-stat-value">${answeredCount}/${totalQuestions}</div>
            <div class="exam-report-stat-label">答题数</div>
          </div>
          <div class="exam-report-stat">
            <div class="exam-report-stat-value exam-evaluation-score ${scoreClass}">${score != null ? score : '-'}</div>
            <div class="exam-report-stat-label">总分</div>
          </div>
          <div class="exam-report-stat">
            <div class="exam-report-stat-value">${scoreLabel}</div>
            <div class="exam-report-stat-label">等级</div>
          </div>
        </div>
    `;

    if (_session.feedback) {
      let feedbackHTML = '';
      try {
        const fb = typeof _session.feedback === 'string'
          ? JSON.parse(_session.feedback)
          : _session.feedback;
        if (fb.summary || fb.overall) {
          feedbackHTML += `<div class="card mb-lg">
            <h4 style="font-family:var(--font-display);margin-bottom:var(--space-sm);">总体评价</h4>
            <div class="card-body">${App.renderMarkdown(fb.summary || fb.overall || '')}</div>
          </div>`;
        }
        if (fb.weaknesses || fb.weak_points) {
          const weaknesses = Array.isArray(fb.weaknesses || fb.weak_points)
            ? (fb.weaknesses || fb.weak_points)
            : [];
          if (weaknesses.length > 0) {
            feedbackHTML += `<div class="card mb-lg">
              <h4 style="font-family:var(--font-display);margin-bottom:var(--space-sm);">薄弱环节</h4>
              <ul style="padding-left:20px;color:var(--text-body);line-height:1.8;">
                ${weaknesses.map(w => `<li>${App.escapeHtml(typeof w === 'string' ? w : w.title || JSON.stringify(w))}</li>`).join('')}
              </ul>
            </div>`;
          }
        }
      } catch (_) {
        feedbackHTML += `<div class="card mb-lg">
          <h4 style="font-family:var(--font-display);margin-bottom:var(--space-sm);">总体评价</h4>
          <div class="card-body">${App.renderMarkdown(String(_session.feedback))}</div>
        </div>`;
      }
      reportHTML += feedbackHTML;
    }

    // 逐题详情
    if (questions.length > 0) {
      reportHTML += `<h3 style="font-family:var(--font-display);font-size:1.15rem;margin-bottom:var(--space-md);">逐题详情</h3>`;
      questions.forEach((q, idx) => {
        let evalDisplay = '';
        if (q.ai_evaluation) {
          try {
            const ev = typeof q.ai_evaluation === 'string' ? JSON.parse(q.ai_evaluation) : q.ai_evaluation;
            evalDisplay = ev.evaluation || ev.comment || '';
          } catch (_) {
            evalDisplay = String(q.ai_evaluation).substring(0, 200);
          }
        }

        let qScoreClass = 'mid';
        if (q.score >= 80) qScoreClass = '';
        else if (q.score < 60) qScoreClass = 'low';

        reportHTML += `
          <div class="card mb-md">
            <div class="card-header">
              <span class="card-title">第 ${idx + 1} 题</span>
              ${q.score != null ? `<span class="exam-evaluation-score ${qScoreClass}" style="font-size:1.1rem;">${q.score}</span>` : '<span class="tag">未答</span>'}
            </div>
            <div class="card-body">
              <p style="color:var(--text-heading);font-weight:500;margin-bottom:8px;">🤖 ${App.escapeHtml(q.question_text)}</p>
              ${q.user_answer ? `<p style="color:var(--text-secondary);margin-bottom:8px;"><strong>你的回答：</strong>${App.escapeHtml(q.user_answer)}</p>` : '<p class="text-muted">未回答</p>'}
              ${evalDisplay ? `<p style="color:var(--text-secondary);"><strong>评判：</strong>${App.renderMarkdown(evalDisplay)}</p>` : ''}
            </div>
          </div>
        `;

        // 标准答案
        if (q.model_answer) {
          reportHTML += `
            <div class="card mb-md" style="border-left:3px solid var(--jade);margin-left:var(--space-md);">
              <div class="card-body">
                <p style="color:var(--jade);font-weight:600;margin-bottom:4px;">✅ 标准答案</p>
                <div style="color:var(--text-body);line-height:1.7;">${App.renderMarkdown(q.model_answer)}</div>
              </div>
            </div>
          `;
        }

        // 知识延伸
        if (q.extensions) {
          reportHTML += `
            <div class="card mb-md" style="border-left:3px solid var(--amber);margin-left:var(--space-md);">
              <div class="card-body">
                <p style="color:var(--amber-dark);font-weight:600;margin-bottom:4px;">🔍 知识延伸</p>
                <div style="color:var(--text-body);line-height:1.7;">${App.renderMarkdown(q.extensions)}</div>
              </div>
            </div>
          `;
        }
      });
    }

    reportHTML += `
        <div class="flex gap-sm mt-lg">
          <button class="btn btn-primary" onclick="location.href='/exam'">开始新考察</button>
          <button class="btn btn-secondary" onclick="location.href='/plan'">查看学习计划</button>
          <a class="btn btn-secondary" href="/exam/sessions/${_session.id}/export" target="_blank">📥 导出报告</a>
        </div>
      </div>
    `;

    examContainer.innerHTML = reportHTML;
  }

  init();
})();
