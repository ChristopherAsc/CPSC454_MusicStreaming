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
const timeCode = document.querySelector("#time-code");
const uploadModal = document.querySelector("#upload-modal");

const audioPlayer = document.querySelector("#audio-player") || new Audio();
audioPlayer.preload = "metadata";
window.btrAudioPlayer = audioPlayer;

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

function setPlaybackState(playing) {
    isPlaying = playing;

    if (playToggle) {
        playToggle.setAttribute("aria-label", playing ? "Pause" : "Play");
    }

    const playIcon = document.querySelector("#play-icon");
    const pauseIcon = document.querySelector("#pause-icon");

    if (playIcon && pauseIcon) {
        playIcon.hidden = playing;
        pauseIcon.hidden = !playing;
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
    }

    updateTimeDisplay();

    audioPlayer.play().then(() => {
        setPlaybackState(true);
    }).catch(() => {
        setPlaybackState(false);
    });
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

    audioPlayer.play().then(() => {
        setPlaybackState(true);
    }).catch(() => {
        setPlaybackState(false);
    });
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
        audioPlayer.play().then(() => {
            setPlaybackState(true);
        }).catch(() => {
            setPlaybackState(false);
        });
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

searchInput?.addEventListener("input", () => {
    const query = searchInput.value.trim().toLowerCase();
    let visibleCount = 0;

    rows.forEach((row) => {
        const text = `${row.dataset.title} ${row.dataset.artist}`.toLowerCase();
        const isVisible = text.includes(query);
        row.hidden = !isVisible;

        if (isVisible) {
            visibleCount += 1;
        }
    });

    if (emptyState) {
        emptyState.hidden = visibleCount !== 0;
    }
});

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

setPlaybackState(false);
updateTimeDisplay();
