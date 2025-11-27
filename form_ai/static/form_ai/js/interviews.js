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

class QuestionManager {
    constructor(listEl, countEl) {
        this.listEl = listEl;
        this.countEl = countEl;
        this.minQuestions = Number(window.MIN_QUESTIONS || 1);
        this.ensureMinimum();
    }

    ensureMinimum() {
        while (this.listEl.children.length < this.minQuestions) {
            this.addQuestion();
        }
        this.updateCount();
    }

    addQuestion(value = "") {
        const row = document.createElement("div");
        row.className = "question-row";

        const input = document.createElement("input");
        input.type = "text";
        input.placeholder = `Question ${this.listEl.children.length + 1}`;
        input.value = value;
        input.required = true;

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "remove-question";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", () => this.removeQuestion(row));

        row.append(input, removeBtn);
        this.listEl.appendChild(row);
        this.updateCount();
        builderLog("Question row added", { order: this.listEl.children.length, value });
    }

    removeQuestion(row) {
        if (this.listEl.children.length <= 1) {
            row.querySelector("input")?.focus();
            return;
        }
        row.remove();
        this.updateCount();
    }

    updateCount() {
        const count = this.listEl.children.length;
        if (this.countEl) {
            this.countEl.textContent = `${count} question${count === 1 ? "" : "s"}`;
        }
        Array.from(this.listEl.querySelectorAll("input")).forEach((input, idx) => {
            input.placeholder = `Question ${idx + 1}`;
        });
    }

    values() {
        return Array.from(this.listEl.querySelectorAll("input"))
            .map((input) => input.value.trim())
            .filter((value) => value.length);
    }
}

class InterviewBuilderApp {
    constructor() {
        this.form = document.getElementById("interview-form");
        this.addBtn = document.getElementById("add-question");
        this.questionList = document.getElementById("question-list");
        this.questionCount = document.getElementById("question-count");
        this.toast = new Toast(document.getElementById("toast"));
        this.submitBtn = this.form?.querySelector("button[type='submit']");
        this.questionManager = new QuestionManager(this.questionList, this.questionCount);
        this.bindEvents();
        builderLog("Builder initialized");
    }

    bindEvents() {
        this.addBtn?.addEventListener("click", () => this.questionManager.addQuestion());
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
            role: (formData.get("role") || "").toString().trim(),
            summary: (formData.get("summary") || "").toString().trim(),
            ai_prompt: (formData.get("ai_prompt") || "").toString().trim(),
            questions: this.questionManager.values(),
        };

        if (!payload.questions.length) {
            this.toast.show("Add at least one interview question");
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
            this.toast.show("Interview created. Redirecting...");
            setTimeout(() => {
                window.location.assign(data.redirect_url || "/");
            }, 1200);
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
        this.bindDeleteButtons();
    }

    bindDeleteButtons() {
        document.querySelectorAll(".delete-question-btn").forEach((btn) => {
            if (btn._wired) return;
            btn._wired = true;
            btn.addEventListener("click", () => this.handleDelete(btn));
        });
    }

    async handleDelete(button) {
        const questionId = button.dataset.questionId;
        if (!questionId) return;
        if (!window.confirm("Delete this question from the interview?")) return;

        const questionItem = button.closest(".question-item");
        const card = button.closest(".interview-card");

        button.disabled = true;
        const originalLabel = button.textContent;
        button.textContent = "…";

        try {
            const response = await fetch(
                `/api/interviews/questions/${questionId}/`,
                { method: "DELETE" }
            );
            const data = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(data.error || "Failed to delete question");
            }

            questionItem?.remove();
            this.resequenceQuestions(card);
            this.toast?.show?.("Question deleted");
        } catch (error) {
            console.error("Delete question failed", error);
            this.toast?.show?.(error.message || "Delete failed");
        } finally {
            button.disabled = false;
            button.textContent = originalLabel;
        }
    }

    resequenceQuestions(card) {
        if (!card) return;
        const items = card.querySelectorAll(".question-item");
        const countLabel = card.querySelector(".question-count");

        items.forEach((item, idx) => {
            const labelEl = item.querySelector(".question-label");
            if (labelEl) {
                labelEl.textContent = `${idx + 1}.`;
            }
        });

        if (countLabel) {
            countLabel.textContent = `${items.length} question${items.length === 1 ? "" : "s"}`;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const builder = new InterviewBuilderApp();
    new ExistingInterviewManager(builder.toast);
});
