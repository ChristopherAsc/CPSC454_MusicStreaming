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
const progressBar = document.querySelector('#progress-bar');

function setNowPlaying(title, artist) {
    playerTitle.textContent = title;
    playerArtist.textContent = artist;
    playerCover.textContent = title.charAt(0);
    heroTitle.textContent = title;
    heroMeta.textContent = `${artist} · Streaming preview from the server library.`;
    playToggle.textContent = 'Pause';
    progressBar.style.width = '18%';
}

playButtons.forEach((button) => {
    button.addEventListener('click', () => {
        setNowPlaying(button.dataset.playTitle, button.dataset.playArtist);
    });
});

playToggle.addEventListener('click', () => {
    playToggle.textContent = playToggle.textContent === 'Play' ? 'Pause' : 'Play';
});

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
