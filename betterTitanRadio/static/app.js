const playButtons = Array.from(document.querySelectorAll("[data-play-title]"));
const searchInput = document.querySelector("#song-search");
const rows = Array.from(document.querySelectorAll("[data-track-row]"));
const emptyState = document.querySelector("#empty-state");
const playerTitle = document.querySelector("#player-title");
const playerArtist = document.querySelector("#player-artist");
const playerCover = document.querySelector("#player-cover");
const heroTitle = document.querySelector("#hero-title");
const heroMeta = document.querySelector("#hero-meta");
const playToggle = document.querySelector("#play-toggle");
const previousTrackButton = document.querySelector("#previous-track");
const nextTrackButton = document.querySelector("#next-track");
const progressBar = document.querySelector("#progress-bar");
const progressRange = document.querySelector("#progress-range");
const volumeRange = document.querySelector("#volume-range");
const timeCode = document.querySelector("#time-code");
const uploadModal = document.querySelector("#upload-modal");
const uploadForm = document.querySelector("[data-upload-form]");
const uploadStatus = document.querySelector("#upload-status");
const dropdown = document.querySelector("#search-dropdown")

// Playback goes through the raw-PCM stream server rather than an <audio>
// element: tracks are requested by sha256 over the WebSocket bridge. The player
// exposes the same play/pause/currentTime/duration/volume surface and the same
// events, so the transport controls below are unchanged.
const bridgeUrl = document.querySelector('meta[name="stream-bridge-url"]')?.content
    || `ws://${window.location.hostname}:8765`;
const audioPlayer = new PcmStreamPlayer(bridgeUrl);
window.btrAudioPlayer = audioPlayer;

const volumeStorageKey = "btr-player-volume";

let activeSha256 = "";
let activeTrackIndex = -1;
let isPlaying = false;
let isSeeking = false;
let pendingSeekPercent = 0;

const playlist = playButtons
    .filter((button) => button.dataset.sha256)
    .map((button) => ({
        title: button.dataset.playTitle,
        artist: button.dataset.playArtist,
        sha256: button.dataset.sha256,
    }));

function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) {
        return "0:00";
    }

    const roundedSeconds = Math.floor(seconds);
    const minutes = Math.floor(roundedSeconds / 60);
    const remainder = roundedSeconds % 60;

    return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function updateTimeDisplay() {
    const currentTime = audioPlayer.currentTime || 0;
    const duration = audioPlayer.duration || 0;

    if (timeCode) {
        timeCode.textContent = `${formatTime(currentTime)} / ${formatTime(duration)}`;
    }

    if (!isSeeking && progressRange && progressBar) {
        const percent = duration ? (currentTime / duration) * 100 : 0;
        progressRange.value = String(percent);
        progressBar.style.width = `${percent}%`;
        progressRange.style.setProperty("--progress-percent", `${percent}%`);
    }
}

function paintProgress(percent) {
    const boundedPercent = Math.min(Math.max(percent, 0), 100);

    if (progressRange) {
        progressRange.value = String(boundedPercent);
        progressRange.style.setProperty("--progress-percent", `${boundedPercent}%`);
    }

    if (progressBar) {
        progressBar.style.width = `${boundedPercent}%`;
    }
}

function getProgressPercentFromEvent(event) {
    const progressElement = progressRange?.closest(".progress");

    if (!progressElement) {
        return Number(progressRange?.value || 0);
    }

    const rect = progressElement.getBoundingClientRect();
    const clientX = event.clientX ?? event.changedTouches?.[0]?.clientX ?? rect.left;

    return ((clientX - rect.left) / rect.width) * 100;
}

function seekToPercent(percent) {
    const duration = audioPlayer.duration || 0;

    if (!duration) {
        paintProgress(percent);
        return;
    }

    const boundedPercent = Math.min(Math.max(percent, 0), 100);
    audioPlayer.currentTime = (boundedPercent / 100) * duration;
    paintProgress(boundedPercent);
    updateTimeDisplay();
}

function syncVolumeControl() {
    if (!volumeRange) {
        return;
    }

    const currentVolume = Math.max(0, Math.min(1, audioPlayer.volume || 0));
    volumeRange.value = String(Math.round(currentVolume * 100));
}

function applyVolume(level) {
    const clampedVolume = Math.max(0, Math.min(1, Number(level) || 0));
    audioPlayer.volume = clampedVolume;
    localStorage.setItem(volumeStorageKey, String(clampedVolume));
    syncVolumeControl();
}

// Mark the row of the track being played so it shows the visualizer instead of
// its initial. Driven by activeSha256 rather than by the clicked button, so a
// track started from the search dropdown lights up its row in the list too.
function updatePlayingRow() {
    rows.forEach((row) => {
        const isActive = Boolean(activeSha256)
            && row.dataset.sha256 === activeSha256;

        row.classList.toggle("is-playing", isActive);
        row.classList.toggle("is-paused", isActive && !isPlaying);
    });
}

function setPlaybackState(playing) {
    isPlaying = playing;
    updatePlayingRow();

    if (playToggle) {
        playToggle.setAttribute("aria-label", playing ? "Pause" : "Play");
        playToggle.setAttribute("aria-pressed", String(playing));
        playToggle.setAttribute("data-state", playing ? "playing" : "paused");
        playToggle.classList.toggle("is-playing", playing);
    }

    const playIcon = document.querySelector("#play-icon");
    const pauseIcon = document.querySelector("#pause-icon");

    if (playIcon && pauseIcon) {
        playIcon.hidden = playing;
        pauseIcon.hidden = !playing;
        playIcon.style.display = playing ? "none" : "block";
        pauseIcon.style.display = playing ? "block" : "none";
    }
}

function updateNowPlaying(track) {
    if (playerTitle) {
        playerTitle.textContent = track.title;
    }

    if (playerArtist) {
        playerArtist.textContent = track.artist;
    }

    if (playerCover) {
        playerCover.textContent = track.title.charAt(0);
    }

    if (heroTitle) {
        heroTitle.textContent = track.title;
    }

    if (heroMeta) {
        heroMeta.textContent = `${track.artist} · Streaming from the server library.`;
    }
}

function findTrackIndex(sha256) {
    return playlist.findIndex((track) => track.sha256 === sha256);
}

// Requesting a track starts playback on its own: the player begins as soon as
// the stream header arrives, so there is no readyState to wait on. Re-selecting
// the track already loaded just resumes it instead of reconnecting.
function beginPlayback(sha256) {
    if (!sha256) {
        setPlaybackState(false);
        return;
    }

    if (activeSha256 === sha256 && audioPlayer.readyState >= 2) {
        audioPlayer.play();
        return;
    }

    activeSha256 = sha256;
    updatePlayingRow();
    audioPlayer.loadTrack(sha256);
}

function playTrack(index) {
    if (!playlist.length) {
        return;
    }

    const normalizedIndex = (index + playlist.length) % playlist.length;
    const track = playlist[normalizedIndex];
    activeTrackIndex = normalizedIndex;
    updateNowPlaying(track);
    updateTimeDisplay();
    beginPlayback(track.sha256);
}

function setNowPlaying(title, artist, sha256) {
    const trackIndex = findTrackIndex(sha256);

    if (trackIndex >= 0) {
        playTrack(trackIndex);
        return;
    }

    // A search hit for a track that is not on this page has no playlist entry;
    // play it directly and leave next/previous pointing at the visible list.
    activeTrackIndex = -1;
    updateNowPlaying({ title, artist });
    updateTimeDisplay();
    beginPlayback(sha256);
}

playButtons.forEach((button) => {
    button.addEventListener("click", () => {
        setNowPlaying(
            button.dataset.playTitle,
            button.dataset.playArtist,
            button.dataset.sha256,
        );
    });
});

playToggle?.addEventListener("click", () => {
    if (!activeSha256) {
        playTrack(0);
        return;
    }

    if (isPlaying) {
        audioPlayer.pause();
        setPlaybackState(false);
    } else {
        beginPlayback(activeSha256);
    }
});

previousTrackButton?.addEventListener("click", () => {
    playTrack(activeTrackIndex > -1 ? activeTrackIndex - 1 : playlist.length - 1);
});

nextTrackButton?.addEventListener("click", () => {
    playTrack(activeTrackIndex + 1);
});

audioPlayer.addEventListener("loadedmetadata", updateTimeDisplay);
audioPlayer.addEventListener("timeupdate", updateTimeDisplay);
audioPlayer.addEventListener("volumechange", syncVolumeControl);
audioPlayer.addEventListener("pause", () => setPlaybackState(false));
audioPlayer.addEventListener("play", () => setPlaybackState(true));
audioPlayer.addEventListener("ended", () => {
    if (playlist.length > 1) {
        playTrack(activeTrackIndex + 1);
    } else {
        setPlaybackState(false);
    }
});

// A refused or unreachable stream is invisible otherwise -- the transport would
// just sit at 0:00 -- so surface it where the track name goes.
audioPlayer.addEventListener("error", (event) => {
    activeSha256 = "";
    setPlaybackState(false);
    updateTimeDisplay();

    const reason = event.detail || "stream unavailable";
    if (playerArtist) {
        playerArtist.textContent = `Playback failed: ${reason}`;
    }
    console.error("PCM stream error:", reason);
});

progressRange?.addEventListener("input", () => {
    isSeeking = true;
    pendingSeekPercent = Number(progressRange.value);
    paintProgress(pendingSeekPercent);
});

volumeRange?.addEventListener("input", () => {
    applyVolume(Number(volumeRange.value) / 100);
});

progressRange?.addEventListener("change", () => {
    pendingSeekPercent = Number(progressRange.value);
    seekToPercent(pendingSeekPercent);
    isSeeking = false;
});

progressRange?.addEventListener("pointerdown", (event) => {
    isSeeking = true;
    pendingSeekPercent = getProgressPercentFromEvent(event);
    paintProgress(pendingSeekPercent);
});

progressRange?.addEventListener("pointerup", (event) => {
    pendingSeekPercent = getProgressPercentFromEvent(event);
    seekToPercent(pendingSeekPercent);
    isSeeking = false;
});


// logic for searching
async function runSearch(query){
    const response = await fetch(`/api/search/?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    return data.results;
}

function renderResults(results){
    dropdown.innerHTML = "";

    console.log("this is the state of the dropdown bool: ", dropdown.hidden)
    if (results.length=== 0){
        // if nothing, display that nothing was found and to upload a song or something
        const item = document.createElement("li");
        item.textContent = `No songs found! Upload a song`
        dropdown.appendChild(item)
        dropdown.hidden = false
        return;
    }
    results.forEach((track) => {
        const item = document.createElement("li");
        item.textContent = `${track.title} — ${track.artist}`;
        item.dataset.sha256 = track.sha256;
        item.dataset.title = track.title;
        item.dataset.artist = track.artist;
        dropdown.appendChild(item)
    });

    dropdown.hidden =false;
}
let latestQuery = "";

async function handleInput(){
    const query = searchInput.value.trim();
    latestQuery = query;

    if (!query){
        dropdown.hidden = true;
        return;
    }

    const results = await runSearch(query);

    if (query !== latestQuery) return;

    renderResults(results);
}

let debounceTimer;

searchInput?.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        handleInput();
    }, 100);
});

dropdown?.addEventListener("click", (event) => {
    const item = event.target.closest("li");
    if (!item) return;

    setNowPlaying(item.dataset.title, item.dataset.artist, item.dataset.sha256);
    dropdown.hidden = true;
    searchInput.value = "";
});

document.addEventListener("click", (event) => {
    if(!event.target.closest(".search-wrapper")) {
        dropdown.hidden = true;
    }
})

searchInput?.addEventListener("keydown", (event)=> {
    if(event.key === "Escape") {
        dropdown.hidden = true;
        searchInput.blur();
    }
})

document.querySelectorAll("[data-upload-open]").forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
        event.preventDefault();
        uploadModal.hidden = false;
    });
});

document.querySelectorAll("[data-upload-close]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
        uploadModal.hidden = true;
    });
});

uploadModal?.addEventListener("click", (event) => {
    if (event.target === uploadModal) {
        uploadModal.hidden = true;
    }
});

function setUploadStatus(type, message, actions = "") {
    if (!uploadStatus) {
        return;
    }

    uploadStatus.hidden = false;
    uploadStatus.className = `upload-status ${type ? `is-${type}` : ""}`;
    uploadStatus.innerHTML = `
        <strong>${escapeHtml(message)}</strong>
        ${actions}
    `;
}

function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = value;

    return element.innerHTML;
}

function resetUploadStatus() {
    if (!uploadStatus) {
        return;
    }

    uploadStatus.hidden = true;
    uploadStatus.className = "upload-status";
    uploadStatus.innerHTML = "";
}

uploadForm?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const submitButton = uploadForm.querySelector("[type='submit']");
    const formData = new FormData(uploadForm);

    if (!formData.get("file")) {
        setUploadStatus("error", "Choose an audio file before uploading.");
        return;
    }

    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = "Uploading...";
    }

    setUploadStatus("pending", "Uploading music to the library...");

    try {
        const response = await fetch(uploadForm.action, {
            method: "POST",
            body: formData,
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Upload failed.");
        }

        const track = data.track || {};
        const title = escapeHtml(track.title || "Track");
        const artist = escapeHtml(track.artist || "Unknown artist");
        const message = data.created
            ? "Music uploaded successfully."
            : "That exact file was already uploaded.";

        setUploadStatus(
            "success",
            message,
            `
                <span>${title} - ${artist}</span>
                <div class="upload-status-actions">
                    <button type="button" data-upload-refresh>View updated library</button>
                    <button type="button" data-upload-again>Upload another</button>
                </div>
            `,
        );
    } catch (error) {
        setUploadStatus("error", error.message || "Upload failed.");
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = "Upload selected file";
        }
    }
});

uploadStatus?.addEventListener("click", (event) => {
    if (event.target.closest("[data-upload-refresh]")) {
        window.location.reload();
    }

    if (event.target.closest("[data-upload-again]")) {
        uploadForm?.reset();
        resetUploadStatus();
    }
});


// --- Folder upload -------------------------------------------------------
// The picker hands us every file in the chosen folder, including artwork and
// stray dotfiles. Those are filtered out here so the count shown to the user is
// the number of tracks, and the server is never asked to reject them one by one.
//
// Files go up one request at a time rather than as a single giant POST: a music
// folder can be gigabytes, and sequential uploads keep memory bounded, let the
// progress readout be truthful, and make cancelling possible.

const folderForm = document.querySelector("[data-folder-form]");
const folderInput = document.querySelector("#modal-folder-upload");
const folderStatus = document.querySelector("#folder-status");
const folderSubmit = document.querySelector("[data-folder-submit]");

// Must match ALLOWED_AUDIO_EXTENSIONS in views.py.
const audioExtensions = ["mp3", "flac", "wav", "m4a", "aac", "ogg", "opus"];

let folderUploadRunning = false;
let folderUploadCancelled = false;

function isAudioFile(file) {
    const name = file.name.toLowerCase();
    const dot = name.lastIndexOf(".");

    return dot > 0 && audioExtensions.includes(name.slice(dot + 1));
}

function setFolderStatus(type, message, detail = "") {
    if (!folderStatus) {
        return;
    }

    folderStatus.hidden = false;
    folderStatus.className = `upload-status ${type ? `is-${type}` : ""}`;
    folderStatus.innerHTML = `<strong>${escapeHtml(message)}</strong>${detail}`;
}

function pluralize(count, word) {
    return `${count} ${word}${count === 1 ? "" : "s"}`;
}

folderInput?.addEventListener("change", () => {
    const chosen = Array.from(folderInput.files || []);

    if (!chosen.length) {
        folderStatus.hidden = true;
        return;
    }

    const audioFiles = chosen.filter(isAudioFile);
    const others = chosen.length - audioFiles.length;

    if (!audioFiles.length) {
        setFolderStatus(
            "error",
            "No audio files in that folder.",
            `<span>${pluralize(chosen.length, "file")} found, none playable.</span>`,
        );
        return;
    }

    setFolderStatus(
        "",
        `${pluralize(audioFiles.length, "track")} ready to upload.`,
        others
            ? `<span>${pluralize(others, "other file")} will be skipped.</span>`
            : "",
    );
});

async function uploadOneFile(file, action, token) {
    const body = new FormData();
    body.append("files", file, file.name);

    if (token) {
        body.append("csrfmiddlewaretoken", token);
    }

    const response = await fetch(action, {
        method: "POST",
        body,
        headers: { "X-Requested-With": "XMLHttpRequest" },
    });

    if (!response.ok) {
        let message = `HTTP ${response.status}`;

        try {
            message = (await response.json()).error || message;
        } catch (error) {
            // A proxy or crash can return HTML; keep the status code.
        }

        throw new Error(message);
    }

    return response.json();
}

folderForm?.addEventListener("submit", async (event) => {
    event.preventDefault();

    // A second click while running means cancel, not upload again.
    if (folderUploadRunning) {
        folderUploadCancelled = true;
        return;
    }

    const audioFiles = Array.from(folderInput?.files || []).filter(isAudioFile);

    if (!audioFiles.length) {
        setFolderStatus("error", "Choose a folder containing audio files first.");
        return;
    }

    const token = folderForm.querySelector("[name=csrfmiddlewaretoken]")?.value;
    const totals = { created: 0, duplicate: 0, skipped: 0, failed: 0 };
    const failures = [];

    folderUploadRunning = true;
    folderUploadCancelled = false;

    if (folderSubmit) {
        folderSubmit.textContent = "Cancel upload";
    }

    for (let index = 0; index < audioFiles.length; index += 1) {
        if (folderUploadCancelled) {
            break;
        }

        const file = audioFiles[index];
        // webkitRelativePath shows where in the folder this file came from;
        // multipart only carries the basename, so this is the client's to show.
        const label = file.webkitRelativePath || file.name;

        setFolderStatus(
            "pending",
            `Uploading ${index + 1} of ${audioFiles.length}...`,
            `<span>${escapeHtml(label)}</span>`,
        );

        try {
            const data = await uploadOneFile(file, folderForm.action, token);

            for (const key of Object.keys(totals)) {
                totals[key] += data.counts?.[key] || 0;
            }
        } catch (error) {
            totals.failed += 1;
            failures.push(`${label}: ${error.message}`);
        }
    }

    folderUploadRunning = false;

    if (folderSubmit) {
        folderSubmit.textContent = "Upload folder";
    }

    const summary = [
        `${pluralize(totals.created, "track")} added`,
        totals.duplicate ? `${totals.duplicate} already in the library` : "",
        totals.skipped ? `${totals.skipped} skipped` : "",
        totals.failed ? `${totals.failed} failed` : "",
    ].filter(Boolean).join(", ");

    const failureList = failures.length
        ? `<span>${failures.slice(0, 5).map(escapeHtml).join("<br>")}${
            failures.length > 5 ? `<br>and ${failures.length - 5} more...` : ""
        }</span>`
        : "";

    setFolderStatus(
        totals.failed ? "error" : "success",
        folderUploadCancelled ? `Cancelled — ${summary}` : `Folder upload complete — ${summary}`,
        `${failureList}
        <div class="upload-status-actions">
            <button type="button" data-upload-refresh>View updated library</button>
        </div>`,
    );
});

folderStatus?.addEventListener("click", (event) => {
    if (event.target.closest("[data-upload-refresh]")) {
        window.location.reload();
    }
});

const storedVolume = Number(localStorage.getItem(volumeStorageKey));
if (Number.isFinite(storedVolume)) {
    applyVolume(storedVolume);
} else {
    applyVolume(audioPlayer.volume || 1);
}

setPlaybackState(false);
updateTimeDisplay();
