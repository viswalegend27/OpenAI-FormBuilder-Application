const builderLog = (...args) => console.log("[InterviewBuilder]", ...args);

class Toast {
    constructor(el) {
        this.el = el;
        this.timer = null;
    }

    show(message, duration = 2500) {
        if (!this.el) return;
        this.el.textContent = message;
        this.el.classList.add("show");
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.hide(), duration);
    }

    hide() {
        if (!this.el) return;
        this.el.classList.remove("show");
    }
}

class SectionManager {
    constructor(listEl, countEl) {
        this.listEl = listEl;
        this.countEl = countEl;
        this.sectionIndex = 0;
    }

    addSection(initial = {}) {
        if (!this.listEl) return null;
        const sectionId = `section-${++this.sectionIndex}`;
        const sectionEl = document.createElement("div");
        sectionEl.className = "section-card";
        sectionEl.dataset.sectionId = sectionId;

        const header = document.createElement("div");
        header.className = "section-card-header";

        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.className = "section-title-input";
        titleInput.placeholder = "Section title (e.g., Projects)";
        titleInput.value = initial.title || "";

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-section-btn";
        removeBtn.textContent = "Remove section";
        removeBtn.addEventListener("click", () => this.removeSection(sectionEl));

        header.append(titleInput, removeBtn);

        const questionsWrap = document.createElement("div");
        questionsWrap.className = "section-questions";

        const addQuestionBtn = document.createElement("button");
        addQuestionBtn.type = "button";
        addQuestionBtn.className = "add-question-btn";
        addQuestionBtn.textContent = "+ Add question";
        addQuestionBtn.addEventListener("click", () => this.addQuestion(sectionEl));

        sectionEl.append(header, questionsWrap, addQuestionBtn);
        this.listEl.appendChild(sectionEl);

        const questions = initial.questions && initial.questions.length ? initial.questions : [""];
        questions.forEach((value) => this.addQuestion(sectionEl, value));

        this.updateCount();
        return sectionEl;
    }

    addQuestion(sectionEl, value = "") {
        const questionsWrap = sectionEl.querySelector(".section-questions");
        if (!questionsWrap) return;

        const row = document.createElement("div");
        row.className = "question-row";

        const input = document.createElement("input");
        input.type = "text";
        input.placeholder = "Question";
        input.value = value || "";

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-question";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", () => this.removeQuestion(row, sectionEl));

        row.append(input, removeBtn);
        questionsWrap.appendChild(row);
        this.refreshQuestionPlaceholders(sectionEl);
    }

    removeQuestion(row, sectionEl) {
        const questionsWrap = sectionEl.querySelector(".section-questions");
        if (!questionsWrap) return;
        if (questionsWrap.children.length <= 1) {
            row.querySelector("input")?.focus();
            return;
        }
        row.remove();
        this.refreshQuestionPlaceholders(sectionEl);
    }

    removeSection(sectionEl) {
        sectionEl.remove();
        this.updateCount();
        if (!this.listEl?.querySelector(".section-card")) {
            this.addSection();
        }
    }

    refreshQuestionPlaceholders(sectionEl) {
        const inputs = sectionEl.querySelectorAll(".section-questions input");
        inputs.forEach((input, idx) => {
            input.placeholder = `Question ${idx + 1}`;
        });
    }

    updateCount() {
        if (!this.countEl) return;
        const sections = this.listEl?.querySelectorAll(".section-card") || [];
        this.countEl.textContent = `${sections.length} section${sections.length === 1 ? "" : "s"}`;
    }

    values() {
        const sections = [];
        this.listEl?.querySelectorAll(".section-card").forEach((sectionEl) => {
            const titleInput = sectionEl.querySelector(".section-title-input");
            const questions = Array.from(sectionEl.querySelectorAll(".section-questions input"))
                .map((input) => input.value.trim())
                .filter(Boolean);
            if (questions.length === 0) {
                return;
            }
            sections.push({
                title: titleInput?.value.trim() || "Untitled section",
                questions,
            });
        });
        return sections;
    }
}

class InterviewBuilderApp {
    constructor() {
        this.form = document.getElementById("interview-form");
        this.addSectionBtn = document.getElementById("add-section");
        this.sectionList = document.getElementById("section-list");
        this.sectionCount = document.getElementById("section-count");
        this.toast = new Toast(document.getElementById("toast"));
        this.submitBtn = this.form?.querySelector("button[type='submit']");
        this.sectionManager = new SectionManager(this.sectionList, this.sectionCount);
        this.sectionManager.addSection();
        this.bindEvents();
        builderLog("Builder initialized");
    }

    bindEvents() {
        this.addSectionBtn?.addEventListener("click", () => this.sectionManager.addSection());
        this.form?.addEventListener("submit", (event) => this.handleSubmit(event));
    }

    collectPayload() {
        const formData = new FormData(this.form);
        const title = (formData.get("title") || "").toString().trim();

        if (!title) {
            this.toast.show("Enter an interview title");
            return null;
        }

        const payload = {
            title,
            sections: this.sectionManager.values(),
        };

        if (!payload.sections.length) {
            this.toast.show("Add at least one question to your sections");
            return null;
        }

        builderLog("Collected payload", payload);
        return payload;
    }

    async handleSubmit(event) {
        event.preventDefault();
        if (!this.form) return;

        const payload = this.collectPayload();
        if (!payload) return;

        try {
            this.setLoading(true);
            builderLog("Submitting interview creation");
            const response = await fetch("/api/interviews/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                builderLog("Interview creation failed", data);
                throw new Error(data.error || "Failed to create interview");
            }

            builderLog("Interview created", data);
            this.toast.show("Interview saved");
            setTimeout(() => window.location.reload(), 800);
        } catch (error) {
            builderLog("Creation error", error);
            this.toast.show(error.message || "Something went wrong");
        } finally {
            this.setLoading(false);
        }
    }

    setLoading(state) {
        if (!this.submitBtn) return;
        this.submitBtn.disabled = state;
        this.submitBtn.textContent = state ? "Saving..." : "Save & start interview";
    }
}

class ExistingInterviewManager {
    constructor(toast) {
        this.toast = toast;
        this.bindQuestionDeletes();
        this.bindInterviewDeletes();
        this.bindStartButtons();
    }

    bindQuestionDeletes() {
        document.querySelectorAll(".delete-question-btn").forEach((btn) => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener("click", () => this.handleDeleteQuestion(btn));
        });
    }

    bindInterviewDeletes() {
        document.querySelectorAll(".delete-interview-btn").forEach((btn) => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener("click", () => this.handleDeleteInterview(btn));
        });
    }

    async handleDeleteQuestion(button) {
        const questionId = button.dataset.questionId;
        const card = button.closest(".interview-card");
        const interviewId = card?.dataset?.interviewId;
        if (!questionId || !interviewId) return;
        if (!window.confirm("Delete this question from the interview?")) return;

        const questionItem = button.closest(".question-item");

        button.disabled = true;
        const originalLabel = button.textContent;
        button.textContent = "...";

        try {
            const response = await fetch(
                `/api/interviews/${interviewId}/questions/${questionId}/`,
                { method: "DELETE" }
            );
            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(data.error || "Failed to delete question");
            }

            questionItem?.remove();
            this.toast?.show?.("Question deleted");
            setTimeout(() => window.location.reload(), 600);
        } catch (error) {
            console.error("Delete question failed", error);
            this.toast?.show?.(error.message || "Delete failed");
        } finally {
            button.disabled = false;
            button.textContent = originalLabel;
        }
    }


    async handleDeleteInterview(button) {
        const interviewId = button.dataset.interviewId;
        if (!interviewId) return;

        const title = button.dataset.interviewTitle || "this interview";
        if (
            !window.confirm(
                `Delete "${title}"? This removes the interview and its questions (responses stay saved).`
            )
        ) {
            return;
        }

        const card = button.closest(".interview-card");
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = "Deleting...";

        try {
            const response = await fetch(`/api/interviews/${interviewId}/`, {
                method: "DELETE",
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || "Failed to delete interview");
            }

            card?.remove();
            this.updateExistingCount(data.remaining_interviews);
            this.toast?.show?.("Interview deleted");
        } catch (error) {
            console.error("Delete interview failed", error);
            this.toast?.show?.(error.message || "Delete failed");
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    bindStartButtons() {
        document.querySelectorAll(".start-interview-btn").forEach((btn) => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener("click", () => this.handleStartInterview(btn));
        });
    }

    getCsrfToken() {
        const name = "csrftoken=";
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name)) {
                return decodeURIComponent(cookie.substring(name.length));
            }
        }
        return "";
    }

    async handleStartInterview(button) {
        const interviewId = button.dataset.interviewId;
        if (!interviewId) return;
        const originalText = button.textContent;
        try {
            button.disabled = true;
            button.textContent = "Preparing...";
            const response = await fetch(`/api/interviews/${interviewId}/links/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.getCsrfToken(),
                },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || "Failed to generate link");
            }
            this.toast?.show?.("Opening interview...");
            window.location.assign(data.invite_url);
        } catch (error) {
            console.error("Invite link failed", error);
            this.toast?.show?.(error.message || "Could not create link");
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    updateExistingCount(serverCount) {
        const currentCount =
            typeof serverCount === "number"
                ? serverCount
                : document.querySelectorAll(".interview-card").length;
        const label = document.getElementById("existing-count-label");
        if (label && currentCount >= 0) {
            label.textContent = `${currentCount} configured \u00b7 reuse an interview to keep your AI prompts consistent.`;
        }

        const list = document.querySelector(".interview-list");
        if (currentCount === 0) {
            if (list) {
                list.innerHTML = `
                    <div class="empty-state">
                        <p>No interviews yet.</p>
                        <p class="muted-text">Use the form to create your first question set.</p>
                    </div>
                `;
            }
            this.toast?.show?.("Creating a starter interview...");
            setTimeout(() => window.location.reload(), 800);
            return;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const builder = new InterviewBuilderApp();
    new ExistingInterviewManager(builder.toast);
});
