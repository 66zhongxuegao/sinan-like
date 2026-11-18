const videos = [...document.querySelectorAll('video')];

const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    const video = entry.target;
    if (entry.isIntersecting) {
      video.play().catch(() => {});
    } else if (!video.paused) {
      video.pause();
    }
  });
}, { threshold: 0.1 });

videos.forEach((video) => observer.observe(video));
