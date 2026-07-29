/**
 * Settings page -- clearing the song library.
 *
 * The destructive call is gated behind a modal rather than firing from the
 * button directly: there is no undo, so a mis-click must not be enough.
 *
 * Unlike the upload endpoints, /api/library/clear/ enforces CSRF, so the token
 * rendered into the page is sent with the request.
 */

const clearButton = document.querySelector("#clear-library");
const clearModal = document.querySelector("#clear-modal");
const clearStatus = document.querySelector("#clear-status");
const clearConfirm = document.querySelector("[data-clear-confirm]");

function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
}

function setClearStatus(type, message, detail = "") {
    if (!clearStatus) {
        return;
    }

    clearStatus.hidden = false;
    clearStatus.className = `upload-status ${type ? `is-${type}` : ""}`;

    const safe = document.createElement("span");
    safe.textContent = message;

    clearStatus.innerHTML = `<strong>${safe.innerHTML}</strong>${detail}`;
}

function closeClearModal() {
    if (clearModal) {
        clearModal.hidden = true;
    }
}

clearButton?.addEventListener("click", () => {
    if (clearModal) {
        clearModal.hidden = false;
    }
});

document.querySelectorAll("[data-clear-cancel]").forEach((trigger) => {
    trigger.addEventListener("click", closeClearModal);
});

// Clicking the backdrop, or pressing Escape, cancels -- the safe outcome.
clearModal?.addEventListener("click", (event) => {
    if (event.target === clearModal) {
        closeClearModal();
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && clearModal && !clearModal.hidden) {
        closeClearModal();
    }
});

clearConfirm?.addEventListener("click", async () => {
    closeClearModal();

    // Whatever is playing came from a track that is about to disappear.
    window.btrAudioPlayer?.stop?.();

    clearConfirm.disabled = true;

    if (clearButton) {
        clearButton.disabled = true;
    }

    setClearStatus("pending", "Clearing the library...");

    try {
        const response = await fetch("/api/library/clear/", {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const warnings = data.file_errors?.length
            ? `<span>${data.file_errors.length} file(s) could not be removed from storage; their rows are gone.</span>`
            : "";

        setClearStatus(
            "success",
            data.message,
            `${warnings}
            <div class="upload-status-actions">
                <button type="button" data-clear-refresh>Back to library</button>
            </div>`,
        );

        if (clearButton) {
            clearButton.textContent = "Library is already empty";
        }
    } catch (error) {
        setClearStatus("error", `Could not clear the library: ${error.message}`);

        if (clearButton) {
            clearButton.disabled = false;
        }
    } finally {
        clearConfirm.disabled = false;
    }
});

clearStatus?.addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-refresh]")) {
        window.location.href = "/";
    }
});
