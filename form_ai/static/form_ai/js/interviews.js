const builderLog = (...args) => console.log('[InterviewBuilder]', ...args);

// ============================================================
// TOAST
// ============================================================

    class Toast {
    constructor(el) {
        this.el = el;
        this.timer = null;
    }

    show(message, duration = 2500) {
        if (!this.el) return;
        this.el.textContent = message;
        this.el.classList.add('show');
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.el.classList.remove('show'), duration);
    }
    }

    // ============================================================
    // SECTION MANAGER
    // ============================================================

    class SectionManager {
    constructor(listEl, countEl) {
        this.listEl = listEl;
        this.countEl = countEl;
        this.sectionIndex = 0;
    }

    addSection(initial = {}) {
        if (!this.listEl) return null;

        const sectionId = `section-${++this.sectionIndex}`;
        const sectionEl = document.createElement('div');
        sectionEl.className = 'section-card';
        sectionEl.dataset.sectionId = sectionId;

        sectionEl.innerHTML = `
        <div class="section-card-header">
            <input type="text" class="section-title-input" 
                placeholder="Section title (e.g., Projects)" 
                value="${initial.title || ''}">
            <button type="button" class="remove-section-btn">Remove section</button>
        </div>
        <div class="section-questions"></div>
        <button type="button" class="add-question-btn">+ Add question</button>
        `;

        sectionEl.querySelector('.remove-section-btn')
        .addEventListener('click', () => this.removeSection(sectionEl));
        
        sectionEl.querySelector('.add-question-btn')
        .addEventListener('click', () => this.addQuestion(sectionEl));

        this.listEl.appendChild(sectionEl);

        const questions = initial.questions?.length ? initial.questions : [''];
        questions.forEach(q => this.addQuestion(sectionEl, q));

        this.updateCount();
        return sectionEl;
    }

    addQuestion(sectionEl, value = '') {
        const wrap = sectionEl.querySelector('.section-questions');
        if (!wrap) return;

        const row = document.createElement('div');
        row.className = 'question-row';
        row.innerHTML = `
        <input type="text" placeholder="Question" value="${value}">
        <button type="button" class="remove-question">Remove</button>
        `;

        row.querySelector('.remove-question')
        .addEventListener('click', () => this.removeQuestion(row, sectionEl));

        wrap.appendChild(row);
        this.refreshPlaceholders(sectionEl);
    }

    removeQuestion(row, sectionEl) {
        const wrap = sectionEl.querySelector('.section-questions');
        if (wrap.children.length <= 1) {
        row.querySelector('input')?.focus();
        return;
        }
        row.remove();
        this.refreshPlaceholders(sectionEl);
    }

    removeSection(sectionEl) {
        sectionEl.remove();
        this.updateCount();
        
        if (!this.listEl.querySelector('.section-card')) {
        this.addSection();
        }
    }

    refreshPlaceholders(sectionEl) {
        sectionEl.querySelectorAll('.section-questions input').forEach((input, i) => {
        input.placeholder = `Question ${i + 1}`;
        });
    }

    updateCount() {
        if (!this.countEl) return;
        const count = this.listEl?.querySelectorAll('.section-card').length || 0;
        this.countEl.textContent = `${count} section${count === 1 ? '' : 's'}`;
    }

    values() {
        const sections = [];
        
        this.listEl?.querySelectorAll('.section-card').forEach(el => {
        const title = el.querySelector('.section-title-input')?.value.trim() || 'Untitled section';
        const questions = Array.from(el.querySelectorAll('.section-questions input'))
            .map(input => input.value.trim())
            .filter(Boolean);
        
        if (questions.length) {
            sections.push({ title, questions });
        }
        });
        
        return sections;
    }
    }

    // ============================================================
    // INTERVIEW BUILDER APP
    // ============================================================

    class InterviewBuilderApp {
    constructor() {
        this.form = document.getElementById('interview-form');
        this.addSectionBtn = document.getElementById('add-section');
        this.sectionList = document.getElementById('section-list');
        this.sectionCount = document.getElementById('section-count');
        this.submitBtn = this.form?.querySelector("button[type='submit']");
        this.toast = new Toast(document.getElementById('toast'));
        
        this.sectionManager = new SectionManager(this.sectionList, this.sectionCount);
        this.sectionManager.addSection();
        
        this.bindEvents();
        builderLog('Builder initialized');
    }

    bindEvents() {
        this.addSectionBtn?.addEventListener('click', () => this.sectionManager.addSection());
        this.form?.addEventListener('submit', e => this.handleSubmit(e));
    }

    async handleSubmit(event) {
        event.preventDefault();
        
        const title = new FormData(this.form).get('title')?.toString().trim();
        
        if (!title) {
        this.toast.show('Enter an interview title');
        return;
        }

        const sections = this.sectionManager.values();
        
        if (!sections.length) {
        this.toast.show('Add at least one question to your sections');
        return;
        }

        const payload = { title, sections };
        builderLog('Collected payload', payload);

        try {
        this.setLoading(true);
        
        const response = await fetch('/api/interviews/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json().catch(() => ({}));
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to create interview');
        }

        builderLog('Interview created', data);
        this.toast.show('Interview saved');
        setTimeout(() => location.reload(), 800);
        
        } catch (err) {
        builderLog('Creation error', err);
        this.toast.show(err.message || 'Something went wrong');
        } finally {
        this.setLoading(false);
        }
    }

    setLoading(loading) {
        if (!this.submitBtn) return;
        this.submitBtn.disabled = loading;
        this.submitBtn.textContent = loading ? 'Saving...' : 'Save interview';
    }
    }

    // ============================================================
    // EXISTING INTERVIEW MANAGER
    // ============================================================

    class ExistingInterviewManager {
    constructor(toast) {
        this.toast = toast;
        this.csrfToken = this.getCSRFToken();
        this.init();
    }

    getCSRFToken() {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    init() {
        this.bindAll('.delete-question-btn', e => this.handleDeleteQuestion(e.target));
        this.bindAll('.delete-interview-btn', e => this.handleDeleteInterview(e.target));
        this.bindAll('.start-interview-btn', e => this.handleStartInterview(e.target));
        this.bindAll('.invite-link-btn', e => this.handleCopyInvite(e.target));
    }

    bindAll(selector, handler) {
        document.querySelectorAll(selector).forEach(btn => {
        if (btn._bound) return;
        btn._bound = true;
        btn.addEventListener('click', handler);
        });
    }

    async apiCall(url, method = 'GET') {
        const response = await fetch(url, {
        method,
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': this.csrfToken
        }
        });
        
        const data = await response.json().catch(() => ({}));
        
        if (!response.ok) {
        throw new Error(data.error || `Request failed`);
        }
        
        return data;
    }

    async handleDeleteQuestion(btn) {
        const questionId = btn.dataset.questionId;
        const card = btn.closest('.interview-card');
        const interviewId = card?.dataset?.interviewId;
        
        if (!questionId || !interviewId) return;
        if (!confirm('Delete this question from the interview?')) return;

        const original = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...';

        try {
        await this.apiCall(`/api/interviews/${interviewId}/questions/${questionId}/`, 'DELETE');
        btn.closest('.question-item')?.remove();
        this.toast?.show?.('Question deleted');
        setTimeout(() => location.reload(), 600);
        } catch (err) {
        this.toast?.show?.(err.message || 'Delete failed');
        btn.disabled = false;
        btn.textContent = original;
        }
    }

    async handleDeleteInterview(btn) {
        const interviewId = btn.dataset.interviewId;
        const title = btn.dataset.interviewTitle || 'this interview';
        
        if (!interviewId) return;
        if (!confirm(`Delete "${title}"? This removes the interview and its questions.`)) return;

        const original = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Deleting...';

        try {
        const data = await this.apiCall(`/api/interviews/${interviewId}/`, 'DELETE');
        btn.closest('.interview-card')?.remove();
        this.updateCount(data.remaining_interviews);
        this.toast?.show?.('Interview deleted');
        } catch (err) {
        this.toast?.show?.(err.message || 'Delete failed');
        btn.disabled = false;
        btn.textContent = original;
        }
    }

    async handleStartInterview(btn) {
    const interviewId = btn.dataset.interviewId;
    if (!interviewId) return;

    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Preparing...';

    try {
        const data = await this.apiCall(`/api/interviews/${interviewId}/links/`, 'POST');
        this.toast?.show?.('Opening interview...');
        window.location.assign(data.invite_url);
        } catch (err) {
        this.toast?.show?.(err.message || 'Could not create link');
        btn.disabled = false;
        btn.textContent = original;
        }
    }

    async handleCopyInvite(btn) {
        const interviewId = btn.dataset.interviewId;
        if (!interviewId) return;

        const original = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Generating...';

        try {
        const data = await this.apiCall(`/api/interviews/${interviewId}/links/`, 'POST');
        await navigator.clipboard.writeText(data.invite_url);
        btn.textContent = 'Link copied';
        this.toast?.show?.('Invite link copied to clipboard');
        setTimeout(() => { btn.textContent = 'Generate URL'; }, 1500);
        } catch (err) {
        this.toast?.show?.(err.message || 'Could not create link');
        btn.textContent = original;
        } finally {
        btn.disabled = false;
        }
    }

    updateCount(serverCount) {
        const count = serverCount ?? document.querySelectorAll('.interview-card').length;
        const label = document.getElementById('existing-count-label');
        
        if (label && count >= 0) {
        label.textContent = `${count} configured · reuse an interview to keep your AI prompts consistent.`;
        }

        if (count === 0) {
        const list = document.querySelector('.interview-list');
        if (list) {
            list.innerHTML = `
            <div class="empty-state">
                <p>No interviews yet.</p>
                <p class="muted-text">Use the form to create your first question set.</p>
            </div>
            `;
        }
        this.toast?.show?.('Creating a starter interview...');
        setTimeout(() => location.reload(), 800);
        }
    }
}

// ============================================================
// INITIALIZATION
// ============================================================

    document.addEventListener('DOMContentLoaded', () => {
  const builder = new InterviewBuilderApp();
  new ExistingInterviewManager(builder.toast);
});