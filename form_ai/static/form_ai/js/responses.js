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

    generateAssessment(convId) {
        return this.request(`/responses/${convId}/generate-assessment/`, {
            method: 'POST'
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
        const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
        
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
        this.assessmentUrls = new Map();
        this.init();
    }

    init() {
        this.on('.view-btn', 'click', (e) => this.handleView(e.currentTarget.dataset.convId));
        this.on('.edit-btn', 'click', (e) => this.handleEdit(e.currentTarget.dataset.convId));
        this.on('.delete-btn', 'click', (e) => this.handleDelete(e.currentTarget.dataset.convId));
        this.on('.generate-assessment-btn', 'click', (e) => this.handleGenerateAssessment(e.currentTarget.dataset.convId, e.currentTarget));
        this.on('.redirect-btn', 'click', (e) => this.handleRedirect(e.currentTarget.dataset.convId));
        this.on('.copy-btn', 'click', (e) => this.handleCopy(e.currentTarget));
        this.on('.view-assessments-btn', 'click', (e) => this.handleToggleAssessments(e.currentTarget.dataset.convId, e.currentTarget));

        this.onClick('saveEditBtn', () => this.handleSaveEdit());
        this.onClick('confirmDeleteBtn', () => this.handleConfirmDelete());
        this.onClick('confirmRedirectBtn', () => this.handleConfirmRedirect());
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
            this.modal.setContent('viewModal', 'viewModalBody', this.buildViewContent(data));
            this.modal.show('viewModal');
        } catch (error) {
            this.toast.show(`Failed to load: ${error.message}`, 'error');
        }
    }

    buildViewContent(data) {
        const userEntries = Object.entries(data.user_response || {});
        const messages = data.messages || [];

        return `
            <div class="view-section">
                <h3>📅 Metadata</h3>
                <div class="view-grid">
                    <div><strong>Response #:</strong> ${data.response_number || 'N/A'}</div>
                    <div><strong>Created:</strong> ${data.created_at || 'N/A'}</div>
                    <div><strong>Updated:</strong> ${data.updated_at || 'N/A'}</div>
                </div>
            </div>
            ${data.interview_form ? `
                <div class="view-section">
                    <h3>📝 Interview</h3>
                    <div class="view-grid">
                        <div><strong>Title:</strong> ${Utils.sanitizeHTML(data.interview_form.title || 'N/A')}</div>
                        ${data.interview_form.role ? `<div><strong>Role:</strong> ${Utils.sanitizeHTML(data.interview_form.role)}</div>` : ''}
                    </div>
                </div>
            ` : ''}
            <div class="view-section">
                <h3>👤 Candidate Information</h3>
                ${userEntries.length > 0 ? `
                    <div class="view-grid">
                        ${userEntries.map(([key, value]) => `
                            <div><strong>${Utils.sanitizeHTML(key)}:</strong> ${Utils.sanitizeHTML(value) || '<em class="value-empty">Not provided</em>'}</div>
                        `).join('')}
                    </div>
                ` : '<p class="muted-text">No candidate information available</p>'}
            </div>
            ${messages.length > 0 ? `
                <div class="view-section">
                    <h3>💬 Conversation (${messages.length} messages)</h3>
                    <div class="messages-preview">
                        ${messages.slice(0, 5).map(msg => `
                            <div class="message-item">
                                <strong>${Utils.sanitizeHTML(msg.role || 'unknown')}:</strong>
                                ${Utils.sanitizeHTML(Utils.truncate(msg.content || '', 150))}
                            </div>
                        `).join('')}
                        ${messages.length > 5 ? `<p class="muted-text">... and ${messages.length - 5} more</p>` : ''}
                    </div>
                </div>
            ` : ''}
        `;
    }

    // EDIT
    async handleEdit(convId) {
        try {
            const data = await this.api.viewResponse(convId);
            this.currentEditId = convId;
            document.getElementById('edit-conv-id').value = convId;
            document.getElementById('editFormFields').innerHTML = this.buildEditForm(data.user_response || {});
            this.modal.show('editModal');
        } catch (error) {
            this.toast.show(`Failed to load: ${error.message}`, 'error');
        }
    }

    buildEditForm(userResponse) {
        const entries = Object.entries(userResponse);
        if (entries.length === 0) return '<p class="muted-text">No fields to edit</p>';

        return entries.map(([key, value]) => `
            <div class="form-group">
                <label for="edit-${key}">${Utils.sanitizeHTML(key.charAt(0).toUpperCase() + key.slice(1))}:</label>
                <input type="text" id="edit-${key}" name="${key}" value="${Utils.sanitizeHTML(value || '')}" class="form-input" placeholder="Enter ${key}">
            </div>
        `).join('');
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
            saveBtn.disabled = false;
            saveBtn.textContent = originalText;
        }
    }

    updateResponseUI(convId, userData) {
        const container = document.querySelector(`[data-conv-id="${convId}"]`);
        if (!container) return;

        const fieldsContainer = container.querySelector('.response-fields');
        if (fieldsContainer) {
            fieldsContainer.innerHTML = Object.entries(userData).map(([key, value]) => `
                <div class="response-field">
                    <span class="response-key">${Utils.sanitizeHTML(key)}:</span>
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
            if (!document.querySelectorAll('.response-container').length) {
                this.showEmptyState();
            }
        }, 300);
    }

    showEmptyState() {
        const layout = document.querySelector('.layout');
        if (layout) {
            layout.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📭</div>
                    <h3>No Responses Yet</h3>
                    <p>Complete a voice interview to see responses here.</p>
                    <a href="/voice/" class="control-btn primary">Start Interview</a>
                </div>
            `;
        }
    }

    // ASSESSMENT
    async handleGenerateAssessment(convId, btn) {
        const originalText = btn.textContent;

        try {
            btn.disabled = true;
            btn.textContent = 'Generating...';

            const data = await this.api.generateAssessment(convId);
            this.assessmentUrls.set(convId, data.assessment_url);

            const urlDisplay = document.getElementById(`url-display-${convId}`);
            const urlInput = urlDisplay.querySelector('.url-input');
            const redirectBtn = document.querySelector(`.redirect-btn[data-conv-id="${convId}"]`);

            urlInput.value = data.assessment_url;
            urlDisplay.style.display = 'flex';
            btn.textContent = '✓ Generated';

            if (redirectBtn) {
                redirectBtn.style.display = 'inline-flex';
                redirectBtn.classList.add('pulse-animation');
                setTimeout(() => redirectBtn.classList.remove('pulse-animation'), 1000);
            }

            this.toast.show('Assessment URL generated', 'success');
        } catch (error) {
            this.toast.show(`Generation failed: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    handleRedirect(convId) {
        const url = this.assessmentUrls.get(convId);
        if (!url) {
            this.toast.show('Generate URL first', 'warning');
            return;
        }

        document.getElementById('redirect-url').value = url;
        this.modal.show('redirectModal');
    }

    handleConfirmRedirect() {
        const url = document.getElementById('redirect-url').value;
        if (!url) {
            this.toast.show('Invalid URL', 'error');
            return;
        }

        this.toast.show('Redirecting...', 'info', 1500);
        this.modal.hide('redirectModal');
        
        // Use window.open for new page or assign for same tab
        setTimeout(() => {
            // Encode URL properly to handle special characters
            window.location.assign(url);
        }, 500);
    }

    async handleCopy(btn) {
        const input = btn.previousElementSibling;
        const originalText = btn.textContent;

        try {
            if (navigator.clipboard) {
                await navigator.clipboard.writeText(input.value);
            } else {
                input.select();
                document.execCommand('copy');
            }

            btn.textContent = '✓ Copied!';
            btn.classList.add('success');
            this.toast.show('Copied to clipboard', 'success');

            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('success');
            }, 2000);
        } catch (error) {
            this.toast.show('Copy failed', 'error');
        }
    }

    handleToggleAssessments(convId, btn) {
        const list = document.getElementById(`assessments-${convId}`);
        const isHidden = list.style.display === 'none' || !list.style.display;

        list.style.display = isHidden ? 'block' : 'none';
        btn.textContent = btn.textContent.replace(isHidden ? 'View' : 'Hide', isHidden ? 'Hide' : 'View');
        btn.setAttribute('aria-expanded', isHidden);
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
        console.log('🚀 Responses Manager Ready');
        
        new ResponseManager(this.api, this.modal, this.toast);

        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled error:', event.reason);
            this.toast.show('An unexpected error occurred', 'error');
        });

        console.log('✅ Application Loaded');
    }
}

const app = new App();
app.init();
