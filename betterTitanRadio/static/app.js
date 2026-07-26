// ---------------------------------------------------------
// app.js
// Loads partial HTML into #stage without reloading base.html,
// so the <audio> element and player bar are never destroyed.
// ---------------------------------------------------------

const stage = document.getElementById("stage");

const routes = {
  search: "partials/search.html",
  profile: "partials/profile.html",
};

let currentRoute = null;

async function loadRoute(routeName) {
  const url = routes[routeName];
  if (!url) return;

  // avoid re-fetching the same panel repeatedly
  if (currentRoute === routeName) return;

  stage.setAttribute("aria-busy", "true");

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to load ${url}: ${res.status}`);
    const html = await res.text();
    stage.innerHTML = html;
    currentRoute = routeName;

    // re-run any route-specific setup after injecting new markup
    if (routeName === "profile") initProfilePanel();
    if (routeName === "search") initSearchPanel();
  } catch (err) {
    stage.innerHTML = `<p class="stage__placeholder">Couldn't load this panel. ${err.message}</p>`;
    console.error(err);
  } finally {
    stage.removeAttribute("aria-busy");
  }
}

// ---- Navigation triggers ----
document.querySelectorAll("[data-route]").forEach((el) => {
  const routeName = el.dataset.route;
  const trigger = el.tagName === "INPUT" ? "focus" : "click";
  el.addEventListener(trigger, () => loadRoute(routeName));
});

// ---- Search panel behavior ----
function initSearchPanel() {
  const input = document.getElementById("searchInput");
  const resultList = document.getElementById("resultList");
  if (!input || !resultList) return;

  input.addEventListener("input", () => {
    const query = input.value.trim();
    resultList.innerHTML = query
      ? `<li class="result-list__empty">No results yet for "${escapeHtml(query)}" — hook this up to your data source.</li>`
      : "";
  });
}

// ---- Profile panel behavior ----
function initProfilePanel() {
  const form = document.getElementById("profileForm");
  const logoutBtn = document.getElementById("logoutBtn");

  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      // wire this up to your actual auth/profile-save logic
      console.log("Profile form submitted:", new FormData(form));
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      // wire this up to your actual logout logic
      console.log("Logout clicked");
    });
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------------
// Persistent audio player controls — lives in base.html,
// never re-rendered, so playback survives navigation.
// ---------------------------------------------------------

const audio = document.getElementById("audioPlayer");
const playBtn = document.getElementById("playBtn");
const playIcon = document.getElementById("playIcon");
const rewindBtn = document.getElementById("rewindBtn");
const forwardBtn = document.getElementById("forwardBtn");

const PLAY_ICON = `<path d="M8 6V18L17 12Z" fill="currentColor"/>`;
const PAUSE_ICON = `<rect x="7" y="6" width="3.5" height="12" rx="1" fill="currentColor"/><rect x="13.5" y="6" width="3.5" height="12" rx="1" fill="currentColor"/>`;

let isPlaying = false;

function setPlaybackState(playing) {
  isPlaying = playing;
  playBtn?.setAttribute("data-state", playing ? "playing" : "paused");
  playBtn?.setAttribute("aria-pressed", String(playing));
  playBtn?.setAttribute("aria-label", playing ? "Pause" : "Play");
  playIcon.innerHTML = playing ? PAUSE_ICON : PLAY_ICON;
}

playBtn?.addEventListener("click", () => {
  const nextState = !isPlaying;
  setPlaybackState(nextState);

  if (nextState) {
    audio?.play?.().catch(() => {
      setPlaybackState(false);
    });
  } else {
    audio?.pause?.();
  }
});

rewindBtn?.addEventListener("click", () => {
  console.log("Rewind clicked");
});

forwardBtn?.addEventListener("click", () => {
  console.log("Fast forward clicked");
});

setPlaybackState(false);

// ---------------------------------------------------------
// Library list — persistent, rendered once on load
// ---------------------------------------------------------

function renderLibrary(items) {
  const list = document.getElementById("libraryList");
  if (!list) return;
  list.innerHTML = items
    .map((item) => `<li data-track-id="${item.id}">${escapeHtml(item.name)}</li>`)
    .join("");
}

// Placeholder data — replace with your real library source
renderLibrary([
  { id: 1, name: "Playlist One" },
  { id: 2, name: "Playlist Two" },
  { id: 3, name: "Liked Songs" },
]);