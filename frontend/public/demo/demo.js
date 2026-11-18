const railItems = [...document.querySelectorAll('.rail-item')];
const chapters = [...document.querySelectorAll('.chapter')];
const railTrack = document.querySelector('.rail-track');
const railProgress = document.querySelector('.rail-progress');

let activeId = chapters[0]?.id ?? '';

function setActive(id) {
  if (!id || id === activeId) return;
  activeId = id;
  railItems.forEach((item) => {
    const active = item.dataset.target === id;
    item.classList.toggle('is-active', active);
    if (active) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
  updateProgress();
}

function updateProgress() {
  if (!railTrack || !railProgress) return;
  const active = document.querySelector(`.rail-item[data-target="${activeId}"]`);
  if (!active) return;
  const trackRect = railTrack.getBoundingClientRect();
  const itemRect = active.getBoundingClientRect();
  const height = Math.max(0, itemRect.top - trackRect.top + itemRect.height / 2);
  railProgress.style.height = `${height}px`;
}

function updateActiveChapter() {
  const marker = window.innerHeight * 0.36;
  let current = chapters[0];
  for (const chapter of chapters) {
    if (chapter.getBoundingClientRect().top <= marker) current = chapter;
  }
  if (current) setActive(current.id);
  updateProgress();
}

let ticking = false;
window.addEventListener('scroll', () => {
  if (ticking) return;
  ticking = true;
  window.requestAnimationFrame(() => {
    updateActiveChapter();
    ticking = false;
  });
}, { passive: true });

window.addEventListener('resize', updateProgress, { passive: true });

railItems.forEach((item) => {
  item.addEventListener('click', () => {
    setActive(item.dataset.target);
  });
});

const videos = [...document.querySelectorAll('.video-frame video')];
videos.forEach((video) => {
  video.addEventListener('play', () => {
    videos.forEach((other) => {
      if (other !== video && !other.paused) other.pause();
    });
  });
});

updateActiveChapter();
