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
const dropdown = document.querySelector("#search-dropdown")

const audioPlayer = document.querySelector("#audio-player") || new Audio();
audioPlayer.preload = "metadata";
window.btrAudioPlayer = audioPlayer;

const volumeStorageKey = "btr-player-volume";

let activeStreamUrl = "";
let activeTrackIndex = -1;
let isPlaying = false;
let isSeeking = false;
let pendingSeekPercent = 0;

const playlist = playButtons
    .filter((button) => button.dataset.streamUrl)
    .map((button) => ({
        title: button.dataset.playTitle,
        artist: button.dataset.playArtist,
        streamUrl: button.dataset.streamUrl,
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

function setPlaybackState(playing) {
    isPlaying = playing;

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

function findTrackIndex(streamUrl) {
    return playlist.findIndex((track) => track.streamUrl === streamUrl);
}

function beginPlayback() {
    const attemptPlay = () => {
        const playPromise = audioPlayer.play();

        if (playPromise && typeof playPromise.then === "function") {
            playPromise.then(() => {
                setPlaybackState(true);
            }).catch(() => {
                setPlaybackState(false);
            });
            return;
        }

        setPlaybackState(true);
    };

    if (!audioPlayer.src) {
        setPlaybackState(false);
        return;
    }

    if (audioPlayer.readyState >= 2) {
        attemptPlay();
        return;
    }

    const onReady = () => {
        audioPlayer.removeEventListener("loadedmetadata", onReady);
        audioPlayer.removeEventListener("canplay", onReady);
        attemptPlay();
    };

    audioPlayer.addEventListener("loadedmetadata", onReady, { once: true });
    audioPlayer.addEventListener("canplay", onReady, { once: true });
    audioPlayer.load();
}

function playTrack(index) {
    if (!playlist.length) {
        return;
    }

    const normalizedIndex = (index + playlist.length) % playlist.length;
    const track = playlist[normalizedIndex];
    activeTrackIndex = normalizedIndex;
    updateNowPlaying(track);

    if (activeStreamUrl !== track.streamUrl) {
        activeStreamUrl = track.streamUrl;
        audioPlayer.src = track.streamUrl;
        audioPlayer.load();
    }

    updateTimeDisplay();
    beginPlayback();
}

function setNowPlaying(title, artist, streamUrl) {
    const trackIndex = findTrackIndex(streamUrl);

    if (trackIndex >= 0) {
        playTrack(trackIndex);
        return;
    }

    const fallbackTrack = { title, artist, streamUrl };
    activeStreamUrl = streamUrl;
    updateNowPlaying(fallbackTrack);

    if (audioPlayer.src !== new URL(streamUrl, window.location.href).href) {
        audioPlayer.src = streamUrl;
    }

    updateTimeDisplay();
    beginPlayback();
}

playButtons.forEach((button) => {
    button.addEventListener("click", () => {
        setNowPlaying(
            button.dataset.playTitle,
            button.dataset.playArtist,
            button.dataset.streamUrl,
        );
    });
});

playToggle?.addEventListener("click", () => {
    if (!activeStreamUrl) {
        playTrack(0);
        return;
    }

    if (isPlaying) {
        audioPlayer.pause();
        setPlaybackState(false);
    } else {
        beginPlayback();
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
        item.dataset.streamUrl = track.stream_url;
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

searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        handleInput();
    }, 100);
});

dropdown.addEventListener("click", (event) => {
    const item = event.target.closest("li");
    if (!item) return;

    setNowPlaying(item.dataset.title, item.dataset.artist, item.dataset.streamUrl);
    dropdown.hidden = true;
    searchInput.value = "";
});

document.addEventListener("click", (event) => {
    if(!event.target.closest(".search-wrapper")) {
        dropdown.hidden = true;
    }
})

searchInput.addEventListener("keydown", (event)=> {
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

const storedVolume = Number(localStorage.getItem(volumeStorageKey));
if (Number.isFinite(storedVolume)) {
    applyVolume(storedVolume);
} else {
    applyVolume(audioPlayer.volume || 1);
}

setPlaybackState(false);
updateTimeDisplay();
