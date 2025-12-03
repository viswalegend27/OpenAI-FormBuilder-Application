// ============================================================
// UTILITIES
// ============================================================

const Utils = {
    getCSRFToken() {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : null;
    },

    sanitizeHTML(str) {
        const div = document.createElement('div');
        div.textContent = str ?? '';
        return div.innerHTML;
    },

    formatLabel(key) {
        if (!key) return '';
        return key
        .toString()
        .replace(/[_-]+/g, ' ')
        .trim()
        .replace(/\b\w/g, c => c.toUpperCase());
    }
};

// ============================================================
// API SERVICE
// ============================================================

class APIService {
    constructor() {
        this.csrfToken = Utils.getCSRFToken();
    }

    async request(url, options = {}) {
        const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': this.csrfToken
        },
        ...options
        });

        if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.message || `HTTP ${response.status}`);
        }
        
        return response.json();
    }

    viewResponse(id) {
        return this.request(`/responses/${id}/view/`);
    }

    editResponse(id, data) {
        return this.request(`/responses/${id}/edit/`, {
        method: 'POST',
        body: JSON.stringify({ user_response: data })
        });
    }

    deleteResponse(id) {
        return this.request(`/responses/${id}/delete/`, { method: 'DELETE' });
    }

    createInviteLink(id) {
        return this.request(`/api/interviews/${id}/links/`, { method: 'POST' });
    }

    deleteInterview(id) {
        return this.request(`/api/interviews/${id}/`, { method: 'DELETE' });
    }
}

// ============================================================
// TOAST MANAGER
// ============================================================

class ToastManager {
    constructor() {
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        this.container.setAttribute('aria-live', 'polite');
        document.body.appendChild(this.container);
    }

    show(message, type = 'info', duration = 3000) {
        const icons = { success: '✓', error: '✕', warning: '!', info: 'i' };

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
        <span class="toast-icon">${icons[type]}</span>
        <span class="toast-message">${Utils.sanitizeHTML(message)}</span>
        <button class="toast-close" aria-label="Close">&times;</button>
        `;

        toast.querySelector('.toast-close').onclick = () => this.dismiss(toast);
        this.container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => this.dismiss(toast), duration);
    }

    dismiss(toast) {
        toast.classList.replace('show', 'hide');
        setTimeout(() => toast.remove(), 300);
    }
}

// ============================================================
// MODAL MANAGER
// ============================================================

class ModalManager {
    constructor() {
        this.activeModal = null;
        this.init();
    }

    init() {
        document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && this.activeModal) this.hide(this.activeModal);
        });

        document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', e => {
            if (e.target === modal) this.hide(modal.id);
        });
        });

        document.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', e => {
            const modal = e.target.closest('.modal');
            if (modal) this.hide(modal.id);
        });
        });
    }

    show(id) {
        const modal = document.getElementById(id);
        if (!modal) return;

        modal.classList.add('active');
        this.activeModal = id;
        document.body.style.overflow = 'hidden';

        const focusable = modal.querySelector('button, input, textarea');
        focusable?.focus();
    }

    hide(id) {
        const modal = document.getElementById(id);
        if (!modal) return;

        modal.classList.remove('active');
        this.activeModal = null;
        document.body.style.overflow = '';
    }
}

// ============================================================
// RESPONSE MANAGER
// ============================================================

class ResponseManager {
    constructor(api, modal, toast) {
        this.api = api;
        this.modal = modal;
        this.toast = toast;
        this.currentEditId = null;
        this.currentDeleteId = null;
        this.fieldLabelCache = new Map();
        this.init();
    }

    init() {
        this.bindAll('.view-btn', 'click', e => this.handleView(e.target.dataset.convId));
        this.bindAll('.edit-btn', 'click', e => this.handleEdit(e.target.dataset.convId));
        this.bindAll('.delete-btn', 'click', e => this.handleDelete(e.target.dataset.convId));
        this.bindAll('.start-interview-btn', 'click', e => this.handleStartInterview(e.target));
        this.bindAll('.invite-link-btn', 'click', e => this.handleCopyInvite(e.target));
        this.bindAll('.delete-interview-btn', 'click', e => this.handleDeleteInterview(e.target));
        this.bindAll('.toggle-responses-btn', 'click', e => this.handleToggle(e.target));

        this.bindId('saveEditBtn', 'click', () => this.handleSaveEdit());
        this.bindId('confirmDeleteBtn', 'click', () => this.handleConfirmDelete());
    }

    bindAll(selector, event, handler) {
        document.querySelectorAll(selector).forEach(el => 
        el.addEventListener(event, e => handler(e))
        );
    }

    bindId(id, event, handler) {
        document.getElementById(id)?.addEventListener(event, handler);
    }

    // VIEW
    async handleView(id) {
        try {
        const data = await this.api.viewResponse(id);
        this.fieldLabelCache.set(id, data.field_labels || {});
        
        document.getElementById('viewModalBody').innerHTML = this.buildViewContent(data);
        this.modal.show('viewModal');
        } catch (err) {
        this.toast.show(`Failed to load: ${err.message}`, 'error');
        }
    }

    buildViewContent(data) {
        const { user_response = {}, messages = [], field_labels = {}, interview_form } = data;
        const entries = Object.entries(user_response);

        return `
        <div class="view-section">
            <h3>Metadata</h3>
            <div class="view-grid">
            <div><strong>Response #:</strong> ${data.response_number || 'N/A'}</div>
            <div><strong>Created:</strong> ${data.created_at || 'N/A'}</div>
            <div><strong>Updated:</strong> ${data.updated_at || 'N/A'}</div>
            </div>
        </div>
        ${interview_form ? `
            <div class="view-section">
            <h3>Interview</h3>
            <div class="view-grid">
                <div><strong>Title:</strong> ${Utils.sanitizeHTML(interview_form.title || 'N/A')}</div>
            </div>
            </div>
        ` : ''}
        <div class="view-section">
            <h3>Candidate Information</h3>
            ${entries.length ? `
            <div class="view-grid">
                ${entries.map(([key, val]) => `
                <div>
                    <strong>${Utils.sanitizeHTML(field_labels[key] || Utils.formatLabel(key))}:</strong>
                    ${val ? Utils.sanitizeHTML(val) : '<em class="value-empty">Not provided</em>'}
                </div>
                `).join('')}
            </div>
            ` : '<p class="muted-text">No candidate information available</p>'}
        </div>
        `;
    }

  // EDIT
    async handleEdit(id) {
    try {
        const data = await this.api.viewResponse(id);
        this.fieldLabelCache.set(id, data.field_labels || {});
        this.currentEditId = id;
        
        document.getElementById('edit-conv-id').value = id;
        document.getElementById('editFormFields').innerHTML = this.buildEditForm(
        data.user_response || {},
        data.field_labels || {}
        );
        
        this.modal.show('editModal');
    } catch (err) {
        this.toast.show(`Failed to load: ${err.message}`, 'error');
    }
    }

    buildEditForm(response, labels) {
    const entries = Object.entries(response);
    if (!entries.length) return '<p class="muted-text">No fields to edit</p>';

    return entries.map(([key, val]) => {
        const label = Utils.sanitizeHTML(labels[key] || Utils.formatLabel(key));
        return `
        <label class="form-field" for="edit-${key}">
            <span>${label}</span>
            <input type="text" id="edit-${key}" name="${key}" 
                    value="${Utils.sanitizeHTML(val || '')}" placeholder="Enter ${label}">
        </label>
        `;
    }).join('');
    }

    async handleSaveEdit() {
        const btn = document.getElementById('saveEditBtn');
        const original = btn.textContent;

        try {
        btn.disabled = true;
        btn.textContent = 'Saving...';

        const formData = new FormData(document.getElementById('editForm'));
        const userData = {};
        
        formData.forEach((val, key) => {
            if (key !== 'csrfmiddlewaretoken' && key !== 'conv_id') {
            userData[key] = val.trim();
            }
        });

        await this.api.editResponse(this.currentEditId, userData);
        
        this.toast.show('Updated successfully', 'success');
        this.modal.hide('editModal');
        this.updateResponseUI(this.currentEditId, userData);
        } catch (err) {
        this.toast.show(`Save failed: ${err.message}`, 'error');
        } finally {
        btn.disabled = false;
        btn.textContent = original;
        }
    }

    updateResponseUI(id, userData) {
    const container = document.querySelector(`[data-conv-id="${id}"]`);
    const fieldsEl = container?.querySelector('.response-fields');
    if (!fieldsEl) return;

    const labels = this.fieldLabelCache.get(id) || {};

    fieldsEl.innerHTML = Object.entries(userData).map(([key, val]) => `
        <div class="response-field">
        <span class="response-key">${Utils.sanitizeHTML(labels[key] || Utils.formatLabel(key))}</span>
        <span class="response-value ${val ? 'value-provided' : 'value-empty'}">
            ${Utils.sanitizeHTML(val) || 'Not provided'}
        </span>
        </div>
    `).join('');

    container.classList.add('updated-flash');
    setTimeout(() => container.classList.remove('updated-flash'), 1000);
    }

  // DELETE
    handleDelete(id) {
    this.currentDeleteId = id;
    document.getElementById('delete-conv-id').value = id;
    this.modal.show('deleteModal');
    }

    async handleConfirmDelete() {
    const btn = document.getElementById('confirmDeleteBtn');
    const original = btn.textContent;

    try {
        btn.disabled = true;
        btn.textContent = 'Deleting...';

        await this.api.deleteResponse(this.currentDeleteId);
        
        this.toast.show('Deleted successfully', 'success');
        this.modal.hide('deleteModal');
        
        const container = document.querySelector(`[data-conv-id="${this.currentDeleteId}"]`);
        if (container) {
        container.style.cssText = 'opacity:0;transform:translateX(-20px);transition:all .3s';
        setTimeout(() => {
            container.remove();
            location.reload();
        }, 300);
        }
    } catch (err) {
        this.toast.show(`Delete failed: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
    }

  // INTERVIEW ACTIONS
    async handleStartInterview(btn) {
        const id = btn.dataset.interviewId;
        if (!id) return;

        const original = btn.textContent;

    try {
        btn.disabled = true;
        btn.textContent = 'Preparing...';
        
        const data = await this.api.createInviteLink(id);
        this.toast.show('Opening voice interview...', 'info', 1200);
        window.location.assign(data.invite_url);
    } catch (err) {
        this.toast.show(err.message || 'Failed to create link', 'error');
        btn.disabled = false;
        btn.textContent = original;
    }
    }

    async handleCopyInvite(btn) {
        const id = btn.dataset.interviewId;
        if (!id) return;

        const original = btn.textContent;
        try {
            btn.disabled = true;
            btn.textContent = 'Generating...';
            const data = await this.api.createInviteLink(id);
            const copied = await this.copyToClipboard(data.invite_url);
            if (!copied) {
                throw new Error('Clipboard unavailable');
            }
            this.toast.show('Invite link copied', 'success');
            btn.textContent = 'Link copied';
        } catch (err) {
            this.toast.show(err.message || 'Failed to copy link', 'error');
            btn.textContent = original;
        } finally {
            btn.disabled = false;
            setTimeout(() => (btn.textContent = 'Generate URL'), 1500);
        }
    }

    async copyToClipboard(text) {
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (_) {
                /* fallthrough */
            }
        }

        const temp = document.createElement('textarea');
        temp.value = text;
        temp.style.position = 'fixed';
        temp.style.opacity = '0';
        document.body.appendChild(temp);
        temp.focus();
        temp.select();
        temp.setSelectionRange(0, text.length);
        let success = false;
        try {
            success = document.execCommand('copy');
        } catch (_) {
            success = false;
        } finally {
            temp.remove();
        }
        return success;
    }

    async handleDeleteInterview(btn) {
    const id = btn.dataset.interviewId;
    const title = btn.dataset.interviewTitle || 'this interview';

    if (!id || !confirm(`Delete "${title}"? This removes the interview and its questions.`)) {
        return;
    }

    const original = btn.textContent;

    try {
        btn.disabled = true;
        btn.textContent = 'Deleting...';
        
        await this.api.deleteInterview(id);
        this.toast.show('Interview deleted', 'success');
        location.reload();
    } catch (err) {
        this.toast.show(err.message || 'Delete failed', 'error');
        btn.disabled = false;
        btn.textContent = original;
    }
    }

    handleToggle(btn) {
    const panel = document.getElementById(btn.dataset.target);
    if (!panel) return;

    const isHidden = panel.hasAttribute('hidden');
    panel.toggleAttribute('hidden', !isHidden);
    btn.textContent = btn.textContent.replace(isHidden ? 'View' : 'Hide', isHidden ? 'Hide' : 'View');
    }
}

// ============================================================
// INITIALIZATION
// ============================================================

    document.addEventListener('DOMContentLoaded', () => {
    const api = new APIService();
    const toast = new ToastManager();
    const modal = new ModalManager();

    new ResponseManager(api, modal, toast);

    window.addEventListener('unhandledrejection', event => {
    console.error('Unhandled error:', event.reason);
    toast.show('An unexpected error occurred', 'error');
    });

    console.log('[Responses] Manager ready');
    });
