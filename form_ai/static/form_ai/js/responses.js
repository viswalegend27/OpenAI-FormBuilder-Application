/**
 * ============================================================
 * RESPONSES MANAGER
 * Handles all interactive features for interview responses
 * ============================================================
 */

// ============================================================
// UTILITIES
// ============================================================

const Utils = {
    /**
     * Get CSRF token from cookie
     * @returns {string|null} CSRF token
     */
    getCSRFToken() {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, 10) === 'csrftoken=') {
                    cookieValue = decodeURIComponent(cookie.substring(10));
                    break;
                }
            }
        }
        return cookieValue;
    },

    /**
     * Debounce function to limit execution rate
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in milliseconds
     * @returns {Function} Debounced function
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * Format date to readable string
     * @param {string} dateString - ISO date string
     * @returns {string} Formatted date
     */
    formatDate(dateString) {
        const date = new Date(dateString);
        const options = { 
            year: 'numeric', 
            month: 'short', 
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        };
        return date.toLocaleDateString('en-US', options);
    },

    /**
     * Sanitize HTML to prevent XSS
     * @param {string} str - String to sanitize
     * @returns {string} Sanitized string
     */
    sanitizeHTML(str) {
        const temp = document.createElement('div');
        temp.textContent = str;
        return temp.innerHTML;
    },

    /**
     * Truncate text to specified length
     * @param {string} text - Text to truncate
     * @param {number} length - Maximum length
     * @returns {string} Truncated text
     */
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
        this.baseURL = window.location.origin;
    }

    /**
     * Make HTTP request
     * @param {string} url - API endpoint
     * @param {object} options - Fetch options
     * @returns {Promise<object>} Response data
     */
    async request(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken
            }
        };

        const config = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...options.headers
            }
        };

        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error('API Request failed:', error);
            throw error;
        }
    }

    /**
     * View response details
     * @param {number} convId - Conversation ID
     * @returns {Promise<object>} Response data
     */
    async viewResponse(convId) {
        return await this.request(`/responses/${convId}/view/`);
    }

    /**
     * Update response data
     * @param {number} convId - Conversation ID
     * @param {object} userData - User response data
     * @returns {Promise<object>} Updated data
     */
    async editResponse(convId, userData) {
        return await this.request(`/responses/${convId}/edit/`, {
            method: 'POST',
            body: JSON.stringify({ user_response: userData })
        });
    }

    /**
     * Delete response
     * @param {number} convId - Conversation ID
     * @returns {Promise<object>} Deletion confirmation
     */
    async deleteResponse(convId) {
        return await this.request(`/responses/${convId}/delete/`, {
            method: 'DELETE'
        });
    }

    /**
     * Generate assessment URL
     * @param {number} convId - Conversation ID
     * @returns {Promise<object>} Assessment data
     */
    async generateAssessment(convId) {
        return await this.request(`/responses/${convId}/generate-assessment/`, {
            method: 'POST'
        });
    }
}


// ============================================================
// TOAST NOTIFICATION MANAGER
// ============================================================

class ToastManager {
    constructor() {
        this.container = this.createContainer();
        this.queue = [];
        this.isShowing = false;
    }

    /**
     * Create toast container
     * @returns {HTMLElement} Toast container
     */
    createContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container';
        container.setAttribute('aria-live', 'polite');
        container.setAttribute('aria-atomic', 'true');
        document.body.appendChild(container);
        return container;
    }

    /**
     * Show toast notification
     * @param {string} message - Toast message
     * @param {string} type - Toast type (success, error, warning, info)
     * @param {number} duration - Display duration in ms
     */
    show(message, type = 'info', duration = 3000) {
        const toast = this.createToast(message, type);
        this.container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // Auto dismiss
        setTimeout(() => {
            this.dismiss(toast);
        }, duration);
    }

    /**
     * Create toast element
     * @param {string} message - Toast message
     * @param {string} type - Toast type
     * @returns {HTMLElement} Toast element
     */
    createToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${Utils.sanitizeHTML(message)}</span>
            <button class="toast-close" aria-label="Close">&times;</button>
        `;

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => {
            this.dismiss(toast);
        });

        return toast;
    }

    /**
     * Dismiss toast
     * @param {HTMLElement} toast - Toast element
     */
    dismiss(toast) {
        toast.classList.remove('show');
        toast.classList.add('hide');
        
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }

    /**
     * Clear all toasts
     */
    clearAll() {
        const toasts = this.container.querySelectorAll('.toast');
        toasts.forEach(toast => this.dismiss(toast));
    }
}


// ============================================================
// MODAL MANAGER
// ============================================================

class ModalManager {
    constructor() {
        this.activeModal = null;
        this.previousFocus = null;
        this.initializeEventListeners();
    }

    /**
     * Initialize global modal event listeners
     */
    initializeEventListeners() {
        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.activeModal) {
                this.hide(this.activeModal);
            }
        });

        // Close buttons
        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const modal = e.target.closest('.modal');
                if (modal) this.hide(modal.id);
            });
        });

        // Click outside to close
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.hide(modal.id);
                }
            });
        });
    }

    /**
     * Show modal
     * @param {string} modalId - Modal element ID
     */
    show(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) {
            console.error(`Modal ${modalId} not found`);
            return;
        }

        // Store current focus
        this.previousFocus = document.activeElement;

        // Show modal
        modal.classList.add('active');
        this.activeModal = modalId;
        document.body.style.overflow = 'hidden';

        // Focus first focusable element
        const focusable = modal.querySelector('button, input, textarea, select');
        if (focusable) {
            setTimeout(() => focusable.focus(), 100);
        }

        // Trap focus within modal
        this.trapFocus(modal);
    }

    /**
     * Hide modal
     * @param {string} modalId - Modal element ID
     */
    hide(modalId) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        modal.classList.remove('active');
        this.activeModal = null;
        document.body.style.overflow = 'auto';

        // Restore focus
        if (this.previousFocus) {
            this.previousFocus.focus();
        }
    }

    /**
     * Trap focus within modal
     * @param {HTMLElement} modal - Modal element
     */
    trapFocus(modal) {
        const focusableElements = modal.querySelectorAll(
            'button, input, textarea, select, a[href], [tabindex]:not([tabindex="-1"])'
        );
        
        if (focusableElements.length === 0) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        modal.addEventListener('keydown', function(e) {
            if (e.key !== 'Tab') return;

            if (e.shiftKey) {
                if (document.activeElement === firstElement) {
                    e.preventDefault();
                    lastElement.focus();
                }
            } else {
                if (document.activeElement === lastElement) {
                    e.preventDefault();
                    firstElement.focus();
                }
            }
        });
    }

    /**
     * Set modal content
     * @param {string} modalId - Modal element ID
     * @param {string} bodyId - Modal body element ID
     * @param {string} content - HTML content
     */
    setContent(modalId, bodyId, content) {
        const body = document.getElementById(bodyId);
        if (body) {
            body.innerHTML = content;
        }
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
        
        this.initializeEventListeners();
    }

    /**
     * Initialize all event listeners
     */
    initializeEventListeners() {
        this.initializeViewButtons();
        this.initializeEditButtons();
        this.initializeDeleteButtons();
        this.initializeAssessmentButtons();
        this.initializeCopyButtons();
        this.initializeToggleButtons();
        this.initializeSaveEdit();
        this.initializeConfirmDelete();
    }

    /**
     * Initialize view buttons
     */
    initializeViewButtons() {
        document.querySelectorAll('.view-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const convId = e.currentTarget.dataset.convId;
                await this.handleView(convId);
            });
        });
    }

    /**
     * Initialize edit buttons
     */
    initializeEditButtons() {
        document.querySelectorAll('.edit-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const convId = e.currentTarget.dataset.convId;
                await this.handleEdit(convId);
            });
        });
    }

    /**
     * Initialize delete buttons
     */
    initializeDeleteButtons() {
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const convId = e.currentTarget.dataset.convId;
                this.handleDelete(convId);
            });
        });
    }

    /**
     * Initialize assessment generation buttons
     */
    initializeAssessmentButtons() {
        document.querySelectorAll('.generate-assessment-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const convId = e.currentTarget.dataset.convId;
                await this.handleGenerateAssessment(convId, btn);
            });
        });
    }

    /**
     * Initialize copy buttons
     */
    initializeCopyButtons() {
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                await this.handleCopy(e.currentTarget);
            });
        });
    }

    /**
     * Initialize toggle buttons
     */
    initializeToggleButtons() {
        document.querySelectorAll('.view-assessments-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const convId = e.currentTarget.dataset.convId;
                this.handleToggleAssessments(convId, btn);
            });
        });
    }

    /**
     * Initialize save edit button
     */
    initializeSaveEdit() {
        const saveBtn = document.getElementById('saveEditBtn');
        if (saveBtn) {
            saveBtn.addEventListener('click', async () => {
                await this.handleSaveEdit();
            });
        }
    }

    /**
     * Initialize confirm delete button
     */
    initializeConfirmDelete() {
        const confirmBtn = document.getElementById('confirmDeleteBtn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', async () => {
                await this.handleConfirmDelete();
            });
        }
    }

    // ========================================================
    // VIEW HANDLER
    // ========================================================

    /**
     * Handle view response
     * @param {number} convId - Conversation ID
     */
    async handleView(convId) {
        try {
            const data = await this.api.viewResponse(convId);
            const content = this.buildViewContent(data);
            this.modal.setContent('viewModal', 'viewModalBody', content);
            this.modal.show('viewModal');
        } catch (error) {
            this.toast.show(`Failed to load details: ${error.message}`, 'error');
        }
    }

    /**
     * Build view modal content
     * @param {object} data - Response data
     * @returns {string} HTML content
     */
    buildViewContent(data) {
        const userResponseEntries = Object.entries(data.user_response || {});
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

            <div class="view-section">
                <h3>👤 Candidate Information</h3>
                ${userResponseEntries.length > 0 ? `
                    <div class="view-grid">
                        ${userResponseEntries.map(([key, value]) => `
                            <div>
                                <strong>${Utils.sanitizeHTML(key)}:</strong> 
                                ${Utils.sanitizeHTML(value) || '<em class="value-empty">Not provided</em>'}
                            </div>
                        `).join('')}
                    </div>
                ` : '<p class="muted-text">No candidate information available</p>'}
            </div>

            ${messages.length > 0 ? `
                <div class="view-section">
                    <h3>💬 Conversation History</h3>
                    <p class="muted-text">${messages.length} messages</p>
                    <div class="messages-preview">
                        ${messages.slice(0, 5).map(msg => `
                            <div class="message-item">
                                <strong>${Utils.sanitizeHTML(msg.role || 'unknown')}:</strong> 
                                ${Utils.sanitizeHTML(Utils.truncate(msg.content || '', 150))}
                            </div>
                        `).join('')}
                        ${messages.length > 5 ? 
                            `<p class="muted-text">... and ${messages.length - 5} more messages</p>` 
                            : ''
                        }
                    </div>
                </div>
            ` : ''}
        `;
    }

    // ========================================================
    // EDIT HANDLER
    // ========================================================

    /**
     * Handle edit response
     * @param {number} convId - Conversation ID
     */
    async handleEdit(convId) {
        try {
            const data = await this.api.viewResponse(convId);
            this.currentEditId = convId;
            
            document.getElementById('edit-conv-id').value = convId;
            const formFields = document.getElementById('editFormFields');
            formFields.innerHTML = this.buildEditForm(data.user_response || {});
            
            this.modal.show('editModal');
        } catch (error) {
            this.toast.show(`Failed to load edit form: ${error.message}`, 'error');
        }
    }

    /**
     * Build edit form fields
     * @param {object} userResponse - User response data
     * @returns {string} HTML content
     */
    buildEditForm(userResponse) {
        const entries = Object.entries(userResponse);
        
        if (entries.length === 0) {
            return '<p class="muted-text">No fields available to edit</p>';
        }

        return entries.map(([key, value]) => `
            <div class="form-group">
                <label for="edit-${key}">
                    ${Utils.sanitizeHTML(key.charAt(0).toUpperCase() + key.slice(1))}:
                </label>
                <input 
                    type="text" 
                    id="edit-${key}" 
                    name="${key}" 
                    value="${Utils.sanitizeHTML(value || '')}"
                    class="form-input"
                    placeholder="Enter ${key}"
                >
            </div>
        `).join('');
    }

    /**
     * Handle save edit
     */
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
            
            this.toast.show('Response updated successfully', 'success');
            this.modal.hide('editModal');
            
            // Update UI without full reload
            this.updateResponseUI(this.currentEditId, userData);
            
        } catch (error) {
            this.toast.show(`Failed to save: ${error.message}`, 'error');
            saveBtn.disabled = false;
            saveBtn.textContent = originalText;
        }
    }

    /**
     * Update response UI after edit
     * @param {number} convId - Conversation ID
     * @param {object} userData - Updated user data
     */
    updateResponseUI(convId, userData) {
        const container = document.querySelector(`[data-conv-id="${convId}"]`);
        if (!container) return;

        const fieldsContainer = container.querySelector('.response-fields');
        if (!fieldsContainer) return;

        fieldsContainer.innerHTML = Object.entries(userData).map(([key, value]) => `
            <div class="response-field">
                <span class="response-key">${Utils.sanitizeHTML(key)}:</span>
                <span class="response-value ${value ? 'value-provided' : 'value-empty'}">
                    ${Utils.sanitizeHTML(value) || 'Not provided'}
                </span>
            </div>
        `).join('');

        // Add updated animation
        container.classList.add('updated-flash');
        setTimeout(() => container.classList.remove('updated-flash'), 1000);
    }

    // ========================================================
    // DELETE HANDLER
    // ========================================================

    /**
     * Handle delete response
     * @param {number} convId - Conversation ID
     */
    handleDelete(convId) {
        this.currentDeleteId = convId;
        document.getElementById('delete-conv-id').value = convId;
        this.modal.show('deleteModal');
    }

    /**
     * Handle confirm delete
     */
    async handleConfirmDelete() {
        const confirmBtn = document.getElementById('confirmDeleteBtn');
        const originalText = confirmBtn.textContent;
        
        try {
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Deleting...';

            await this.api.deleteResponse(this.currentDeleteId);
            
            this.toast.show('Response deleted successfully', 'success');
            this.modal.hide('deleteModal');
            
            // Remove from DOM with animation
            this.removeResponseFromUI(this.currentDeleteId);
            
        } catch (error) {
            this.toast.show(`Failed to delete: ${error.message}`, 'error');
            confirmBtn.disabled = false;
            confirmBtn.textContent = originalText;
        }
    }

    /**
     * Remove response from UI
     * @param {number} convId - Conversation ID
     */
    removeResponseFromUI(convId) {
        const container = document.querySelector(`[data-conv-id="${convId}"]`);
        if (!container) return;

        // Animate out
        container.style.opacity = '0';
        container.style.transform = 'translateX(-20px)';
        container.style.transition = 'all 0.3s ease';

        setTimeout(() => {
            container.remove();
            
            // Check if list is empty
            const remainingResponses = document.querySelectorAll('.response-container');
            if (remainingResponses.length === 0) {
                this.showEmptyState();
            }
        }, 300);
    }

    /**
     * Show empty state
     */
    showEmptyState() {
        const layout = document.querySelector('.layout');
        if (!layout) return;

        layout.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <h3>No Responses Yet</h3>
                <p>Complete a voice interview to see responses here.</p>
                <a href="/voice/" class="control-btn primary">Start Interview</a>
            </div>
        `;
    }

    // ========================================================
    // ASSESSMENT HANDLERS
    // ========================================================

    /**
     * Handle generate assessment
     * @param {number} convId - Conversation ID
     * @param {HTMLElement} btn - Button element
     */
    async handleGenerateAssessment(convId, btn) {
        const originalText = btn.textContent;
        
        try {
            btn.disabled = true;
            btn.textContent = 'Generating...';

            const data = await this.api.generateAssessment(convId);
            
            const urlDisplay = document.getElementById(`url-display-${convId}`);
            const urlInput = urlDisplay.querySelector('.url-input');
            
            urlInput.value = data.assessment_url;
            urlDisplay.style.display = 'flex';
            btn.textContent = '✓ Generated';
            
            this.toast.show('Assessment URL generated successfully', 'success');
            
        } catch (error) {
            this.toast.show(`Failed to generate assessment: ${error.message}`, 'error');
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }

    /**
     * Handle copy URL
     * @param {HTMLElement} btn - Copy button
     */
    async handleCopy(btn) {
        const input = btn.previousElementSibling;
        const originalText = btn.textContent;
        
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(input.value);
            } else {
                // Fallback for older browsers
                input.select();
                input.setSelectionRange(0, 99999); // Mobile
                document.execCommand('copy');
            }
            
            btn.textContent = '✓ Copied!';
            btn.classList.add('success');
            this.toast.show('URL copied to clipboard', 'success');
            
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.remove('success');
            }, 2000);
            
        } catch (error) {
            this.toast.show('Failed to copy URL', 'error');
        }
    }

    /**
     * Handle toggle assessments
     * @param {number} convId - Conversation ID
     * @param {HTMLElement} btn - Toggle button
     */
    handleToggleAssessments(convId, btn) {
        const assessmentsList = document.getElementById(`assessments-${convId}`);
        const isHidden = assessmentsList.style.display === 'none' || !assessmentsList.style.display;
        
        if (isHidden) {
            assessmentsList.style.display = 'block';
            btn.textContent = btn.textContent.replace('View', 'Hide');
            btn.setAttribute('aria-expanded', 'true');
        } else {
            assessmentsList.style.display = 'none';
            btn.textContent = btn.textContent.replace('Hide', 'View');
            btn.setAttribute('aria-expanded', 'false');
        }
    }
}


// ============================================================
// INITIALIZATION
// ============================================================

class App {
    constructor() {
        this.api = new APIService();
        this.toast = new ToastManager();
        this.modal = new ModalManager();
        this.responseManager = null;
    }

    /**
     * Initialize application
     */
    init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.start());
        } else {
            this.start();
        }
    }

    /**
     * Start application
     */
    start() {
        console.log('🚀 Responses Manager initialized');
        
        // Initialize response manager
        this.responseManager = new ResponseManager(
            this.api,
            this.modal,
            this.toast
        );

        // Add global error handler
        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled promise rejection:', event.reason);
            this.toast.show('An unexpected error occurred', 'error');
        });

        // Add visibility change handler
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                console.log('Page hidden');
            } else {
                console.log('Page visible');
            }
        });

        // Log app ready
        console.log('✅ Application ready');
    }
}

// ============================================================
// START APPLICATION
// ============================================================

const app = new App();
app.init();

// Export for external use if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { App, APIService, ModalManager, ToastManager, ResponseManager, Utils };
}