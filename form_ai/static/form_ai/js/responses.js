/**
 * RESPONSES MANAGER - Optimized & Clean
 */

// ============================================================
// UTILITIES
// ============================================================

const Utils = {
    getCSRFToken() {
        const name = 'csrftoken=';
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name)) {
                return decodeURIComponent(cookie.substring(name.length));
            }
        }
        return null;
    },

    sanitizeHTML(str) {
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    },

    truncate(text, length = 100) {
        if (!text) return '';
        return text.length > length ? text.substring(0, length) + '...' : text;
    },

    formatLabel(key) {
        if (!key) return '';
        return key
            .toString()
            .replace(/[_\-]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/\b\w/g, (c) => c.toUpperCase());
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
        const config = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            },
            ...options
        };

        try {
            const response = await fetch(url, config);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    }

    viewResponse(convId) {
        return this.request(`/responses/${convId}/view/`);
    }

    editResponse(convId, userData) {
        return this.request(`/responses/${convId}/edit/`, {
            method: 'POST',
            body: JSON.stringify({ user_response: userData })
        });
    }

    deleteResponse(convId) {
        return this.request(`/responses/${convId}/delete/`, {
            method: 'DELETE'
        });
    }

    createInviteLink(interviewId) {
        return this.request(`/api/interviews/${interviewId}/links/`, {
            method: 'POST'
        });
    }

    deleteInterview(interviewId) {
        return this.request(`/api/interviews/${interviewId}/`, {
            method: 'DELETE'
        });
    }

    deleteInterviewQuestion(interviewId, questionId) {
        return this.request(`/api/interviews/${interviewId}/questions/${questionId}/`, {
            method: 'DELETE'
        });
    }

}

// ============================================================
// TOAST MANAGER
// ============================================================

class ToastManager {
    constructor() {
        this.container = this.createContainer();
    }

    createContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container';
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
        return container;
    }

    show(message, type = 'info', duration = 3000) {
        const icons = { success: 'OK', error: 'ERR', warning: '!', info: 'i' };
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type]}</span>
            <span class="toast-message">${Utils.sanitizeHTML(message)}</span>
            <button class="toast-close" aria-label="Close">&times;</button>
        `;

        toast.querySelector('.toast-close').addEventListener('click', () => this.dismiss(toast));
        this.container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('show'));
        setTimeout(() => this.dismiss(toast), duration);
    }

    dismiss(toast) {
        toast.classList.remove('show');
        toast.classList.add('hide');
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
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.activeModal) {
                this.hide(this.activeModal);
            }
        });

        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                if (modal) this.hide(modal.id);
            });
        });

        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) this.hide(modal.id);
            });
        });
    }

    show(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        modal.classList.add('active');
        this.activeModal = modalId;
        document.body.style.overflow = 'hidden';

        const focusable = modal.querySelector('button, input, textarea, select');
        if (focusable) setTimeout(() => focusable.focus(), 100);
    }

    hide(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        modal.classList.remove('active');
        this.activeModal = null;
        document.body.style.overflow = 'auto';
    }

    setContent(modalId, bodyId, content) {
        const body = document.getElementById(bodyId);
        if (body) body.innerHTML = content;
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
        this.on('.view-btn', 'click', (e) => this.handleView(e.currentTarget.dataset.convId));
        this.on('.edit-btn', 'click', (e) => this.handleEdit(e.currentTarget.dataset.convId));
        this.on('.delete-btn', 'click', (e) => this.handleDelete(e.currentTarget.dataset.convId));
        this.on('.start-interview-btn', 'click', (e) => this.handleStartInterview(e.currentTarget));
        this.on('.invite-link-btn', 'click', (e) => this.handleCopyInvite(e.currentTarget));
        this.on('.delete-interview-btn', 'click', (e) => this.handleDeleteInterview(e.currentTarget));
        this.on('.toggle-responses-btn', 'click', (e) => this.handleToggleResponses(e.currentTarget));

        this.onClick('saveEditBtn', () => this.handleSaveEdit());
        this.onClick('confirmDeleteBtn', () => this.handleConfirmDelete());
    }

    on(selector, event, handler) {
        document.querySelectorAll(selector).forEach(el => el.addEventListener(event, handler));
    }

    onClick(id, handler) {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', handler);
    }

    // VIEW
    async handleView(convId) {
        try {
            const data = await this.api.viewResponse(convId);
            this.fieldLabelCache.set(convId, data.field_labels || {});
            this.modal.setContent('viewModal', 'viewModalBody', this.buildViewContent(data));
            this.modal.show('viewModal');
        } catch (error) {
            this.toast.show(`Failed to load: ${error.message}`, 'error');
        }
    }

    buildViewContent(data) {
        const userEntries = Object.entries(data.user_response || {});
        const messages = data.messages || [];
        const fieldLabels = data.field_labels || {};

        return `
            <div class="view-section">
                <h3>Metadata</h3>
                <div class="view-grid">
                    <div><strong>Response #:</strong> ${data.response_number || 'N/A'}</div>
                    <div><strong>Created:</strong> ${data.created_at || 'N/A'}</div>
                    <div><strong>Updated:</strong> ${data.updated_at || 'N/A'}</div>
                </div>
            </div>
                ${data.interview_form ? `
                <div class="view-section">
                    <h3>Interview</h3>
                    <div class="view-grid">
                        <div><strong>Title:</strong> ${Utils.sanitizeHTML(data.interview_form.title || 'N/A')}</div>
                    </div>
                </div>
            ` : ''}
            <div class="view-section">
                <h3>Candidate Information</h3>
                ${userEntries.length > 0 ? `
                    <div class="view-grid">
                        ${userEntries.map(([key, value]) => `
                            <div><strong>${Utils.sanitizeHTML(fieldLabels[key] || Utils.formatLabel(key))}:</strong> ${Utils.sanitizeHTML(value) || '<em class="value-empty">Not provided</em>'}</div>
                        `).join('')}
                    </div>
                ` : '<p class="muted-text">No candidate information available</p>'}
            </div>
        `;
    }

    // EDIT
    async handleEdit(convId) {
        try {
            const data = await this.api.viewResponse(convId);
            this.fieldLabelCache.set(convId, data.field_labels || {});
            this.currentEditId = convId;
            document.getElementById('edit-conv-id').value = convId;
            document.getElementById('editFormFields').innerHTML = this.buildEditForm(
                data.user_response || {},
                data.field_labels || {}
            );
            this.modal.show('editModal');
        } catch (error) {
            this.toast.show(`Failed to load: ${error.message}`, 'error');
        }
    }

    buildEditForm(userResponse, fieldLabels = {}) {
        const entries = Object.entries(userResponse);
        if (entries.length === 0) return '<p class="muted-text">No fields to edit</p>';

        return entries.map(([key, value]) => {
            const label = Utils.sanitizeHTML(fieldLabels[key] || Utils.formatLabel(key));
            const safeValue = Utils.sanitizeHTML(value || "");
            return `
                <label class="form-field" for="edit-${key}">
                    <span>${label}</span>
                    <input type="text" id="edit-${key}" name="${key}" value="${safeValue}" placeholder="Enter ${label}">
                </label>
            `;
        }).join('');
    }

    async handleSaveEdit() {
        const saveBtn = document.getElementById('saveEditBtn');
        const originalText = saveBtn.textContent;

        try {
            saveBtn.disabled = true;
            saveBtn.textContent = 'Saving...';

            const formData = new FormData(document.getElementById('editForm'));
            const userData = {};
            formData.forEach((value, key) => {
                if (key !== 'csrfmiddlewaretoken' && key !== 'conv_id') {
                    userData[key] = value.trim();
                }
            });

            await this.api.editResponse(this.currentEditId, userData);
            this.toast.show('Updated successfully', 'success');
            this.modal.hide('editModal');
            this.updateResponseUI(this.currentEditId, userData);
        } catch (error) {
            this.toast.show(`Save failed: ${error.message}`, 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.textContent = originalText;
        }
    }

    updateResponseUI(convId, userData) {
        const container = document.querySelector(`[data-conv-id="${convId}"]`);
        if (!container) return;
        const labelMap = this.fieldLabelCache.get(convId) || {};

        const fieldsContainer = container.querySelector('.response-fields');
        if (fieldsContainer) {
            fieldsContainer.innerHTML = Object.entries(userData).map(([key, value]) => `
                <div class="response-field">
                    <span class="response-key">${Utils.sanitizeHTML(labelMap[key] || Utils.formatLabel(key))}</span>
                    <span class="response-value ${value ? 'value-provided' : 'value-empty'}">
                        ${Utils.sanitizeHTML(value) || 'Not provided'}
                    </span>
                </div>
            `).join('');

            container.classList.add('updated-flash');
            setTimeout(() => container.classList.remove('updated-flash'), 1000);
        }
    }

    // DELETE
    handleDelete(convId) {
        this.currentDeleteId = convId;
        document.getElementById('delete-conv-id').value = convId;
        this.modal.show('deleteModal');
    }

    async handleConfirmDelete() {
        const confirmBtn = document.getElementById('confirmDeleteBtn');
        const originalText = confirmBtn.textContent;

        try {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Deleting...';

            await this.api.deleteResponse(this.currentDeleteId);
            this.toast.show('Deleted successfully', 'success');
            this.modal.hide('deleteModal');
            this.removeResponseFromUI(this.currentDeleteId);
        } catch (error) {
            this.toast.show(`Delete failed: ${error.message}`, 'error');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = originalText;
        }
    }

    removeResponseFromUI(convId) {
        const container = document.querySelector(`[data-conv-id="${convId}"]`);
        if (!container) return;

        container.style.opacity = '0';
        container.style.transform = 'translateX(-20px)';
        container.style.transition = 'all 0.3s ease';

        setTimeout(() => {
            container.remove();
            window.location.reload();
        }, 300);
    }

    async handleStartInterview(button) {
        const interviewId = button.dataset.interviewId;
        if (!interviewId) return;
        const originalText = button.textContent;
        try {
            button.disabled = true;
            button.textContent = 'Preparing...';
            const data = await this.api.createInviteLink(interviewId);
            this.toast.show('Opening voice interview...', 'info', 1200);
            window.location.assign(data.invite_url);
        } catch (error) {
            this.toast.show(error.message || 'Failed to create link', 'error');
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    async handleCopyInvite(button) {
        const interviewId = button.dataset.interviewId;
        if (!interviewId) return;
        const originalText = button.textContent;
        try {
            button.disabled = true;
            button.textContent = 'Generating...';
            const data = await this.api.createInviteLink(interviewId);
            await navigator.clipboard.writeText(data.invite_url);
            this.toast.show('Invite link copied', 'success');
            button.textContent = 'Link copied';
        } catch (error) {
            this.toast.show(error.message || 'Failed to copy link', 'error');
            button.textContent = originalText;
        } finally {
            button.disabled = false;
            setTimeout(() => (button.textContent = 'Generate URL'), 1500);
        }
    }

    async handleDeleteInterview(button) {
        const interviewId = button.dataset.interviewId;
        const title = button.dataset.interviewTitle || 'this interview';
        if (!interviewId) return;
        if (!window.confirm(`Delete "${title}"? This removes the interview and its questions.`)) {
            return;
        }

        const originalText = button.textContent;
        try {
            button.disabled = true;
            button.textContent = 'Deleting...';
            await this.api.deleteInterview(interviewId);
            this.toast.show('Interview deleted', 'success');
            window.location.reload();
        } catch (error) {
            this.toast.show(error.message || 'Delete failed', 'error');
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    handleToggleResponses(button) {
        const targetId = button.dataset.target;
        const panel = document.getElementById(targetId);
        if (!panel) return;
        const isHidden = panel.hasAttribute('hidden');
        if (isHidden) {
            panel.removeAttribute('hidden');
            button.textContent = button.textContent.replace('View', 'Hide');
        } else {
            panel.setAttribute('hidden', '');
            button.textContent = button.textContent.replace('Hide', 'View');
        }
    }
}

// ============================================================
// APP INITIALIZATION
// ============================================================

class App {
    constructor() {
        this.api = new APIService();
        this.toast = new ToastManager();
        this.modal = new ModalManager();
    }

    init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.start());
        } else {
            this.start();
        }
    }

    start() {
        console.log('[Responses] Manager ready');
        
        new ResponseManager(this.api, this.modal, this.toast);

        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled error:', event.reason);
            this.toast.show('An unexpected error occurred', 'error');
        });

        console.log('[Responses] Application loaded');
    }
}

const app = new App();
app.init();
