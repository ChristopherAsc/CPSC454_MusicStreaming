const playButtons = document.querySelectorAll('[data-play-title]');
const searchInput = document.querySelector('#song-search');
const rows = document.querySelectorAll('[data-track-row]');
const emptyState = document.querySelector('#empty-state');
const playerTitle = document.querySelector('#player-title');
const playerArtist = document.querySelector('#player-artist');
const playerCover = document.querySelector('#player-cover');
const heroTitle = document.querySelector('#hero-title');
const heroMeta = document.querySelector('#hero-meta');
const playToggle = document.querySelector('#play-toggle');
let playIcon = document.querySelector('#play-icon');
let pauseIcon = document.querySelector('#pause-icon');
const progressBar = document.querySelector('#progress-bar');

function setNowPlaying(title, artist) {
    playerTitle.textContent = title;
    playerArtist.textContent = artist;
    playerCover.textContent = title.charAt(0);
    heroTitle.textContent = title;
    heroMeta.textContent = `${artist} · Streaming preview from the server library.`;
    progressBar.style.width = '18%';
}

function setPlaybackState(isPlaying) {
    if (!playToggle) {
        return;
    }

    if (!playIcon || !pauseIcon) {
        playToggle.innerHTML = `
            <img id="play-icon" src="/static/music/images/play.svg" alt="Play" class="image-button">
            <img id="pause-icon" src="/static/music/images/pause.svg" alt="Pause" style="display: none;" class="image-button">
        `;
        playIcon = playToggle.querySelector('#play-icon');
        pauseIcon = playToggle.querySelector('#pause-icon');
    }

    if (!playIcon || !pauseIcon) {
        return;
    }

    playIcon.style.display = isPlaying ? 'none' : 'block';
    pauseIcon.style.display = isPlaying ? 'block' : 'none';
    playIcon.hidden = isPlaying;
    pauseIcon.hidden = !isPlaying;
}

playButtons.forEach((button) => {
    button.addEventListener('click', () => {
        setNowPlaying(button.dataset.playTitle, button.dataset.playArtist);
    });
});

playToggle.addEventListener('click', () => {
    const isPlaying = playIcon.hidden;
    setPlaybackState(!isPlaying);
});

setPlaybackState(false);

searchInput.addEventListener('input', () => {
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

    emptyState.hidden = visibleCount !== 0;
});
