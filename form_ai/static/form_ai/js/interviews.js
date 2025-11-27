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

        return payload;
    }

    async handleSubmit(event) {
        event.preventDefault();
        if (!this.form) return;

        const payload = this.collectPayload();
        if (!payload) return;

        try {
            this.setLoading(true);
            const response = await fetch("/api/interviews/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || "Failed to create interview");
            }

            this.toast.show("Interview created. Redirecting...");
            setTimeout(() => {
                window.location.assign(data.redirect_url || "/");
            }, 1200);
        } catch (error) {
            this.toast.show(error.message || "Something went wrong");
        } finally {
            this.setLoading(false);
        }
    }

    setLoading(state) {
        if (!this.submitBtn) return;
        this.submitBtn.disabled = state;
        this.submitBtn.textContent = state ? "Creating..." : "Create & start interview";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    new InterviewBuilderApp();
});
