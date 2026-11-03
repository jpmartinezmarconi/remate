(() => {
  const slider = document.querySelector("[data-hero-slider]");
  if (!slider) return;

  const slides = Array.from(slider.querySelectorAll(".hero-slide"));
  const dots = Array.from(slider.querySelectorAll("[data-hero-dot]"));
  if (slides.length < 2) return;

  let activeIndex = 0;
  let timer;
  let pointerInside = false;
  let focusInside = false;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const showSlide = (index) => {
    activeIndex = (index + slides.length) % slides.length;
    slides.forEach((slide, slideIndex) => {
      const active = slideIndex === activeIndex;
      slide.hidden = false;
      slide.classList.toggle("is-active", active);
      slide.setAttribute("aria-hidden", String(!active));
      slide.tabIndex = active ? 0 : -1;
    });
    dots.forEach((dot, dotIndex) => {
      const active = dotIndex === activeIndex;
      dot.classList.toggle("is-active", active);
      dot.setAttribute("aria-pressed", String(active));
    });
  };

  const stopAutoplay = () => window.clearInterval(timer);
  const startAutoplay = () => {
    stopAutoplay();
    if (!pointerInside && !focusInside && !reducedMotion.matches && !document.hidden) {
      timer = window.setInterval(() => showSlide(activeIndex + 1), 5000);
    }
  };

  slider.querySelector("[data-hero-previous]")?.addEventListener("click", () => {
    showSlide(activeIndex - 1);
    startAutoplay();
  });
  slider.querySelector("[data-hero-next]")?.addEventListener("click", () => {
    showSlide(activeIndex + 1);
    startAutoplay();
  });
  dots.forEach((dot) => {
    dot.addEventListener("click", () => {
      showSlide(Number(dot.dataset.heroDot));
      startAutoplay();
    });
  });
  slider.addEventListener("mouseenter", () => {
    pointerInside = true;
    stopAutoplay();
  });
  slider.addEventListener("mouseleave", () => {
    pointerInside = false;
    startAutoplay();
  });
  slider.addEventListener("focusin", () => {
    focusInside = true;
    stopAutoplay();
  });
  slider.addEventListener("focusout", (event) => {
    if (!slider.contains(event.relatedTarget)) {
      focusInside = false;
      startAutoplay();
    }
  });
  document.addEventListener("visibilitychange", startAutoplay);
  reducedMotion.addEventListener("change", startAutoplay);

  slides.forEach((slide) => {
    slide.hidden = false;
  });
  showSlide(0);
  startAutoplay();
})();
