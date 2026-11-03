(() => {
  const dialog = document.querySelector("[data-photo-lightbox]");
  if (!(dialog instanceof HTMLDialogElement)) return;

  const triggers = Array.from(document.querySelectorAll("[data-lightbox-image]"));
  const preview = dialog.querySelector("[data-lightbox-preview]");
  const count = dialog.querySelector("[data-lightbox-count]");
  const previous = dialog.querySelector("[data-lightbox-previous]");
  const next = dialog.querySelector("[data-lightbox-next]");
  let activeIndex = 0;

  const showImage = (index) => {
    activeIndex = (index + triggers.length) % triggers.length;
    const trigger = triggers[activeIndex];
    preview.src = trigger.dataset.lightboxImage;
    preview.alt = trigger.dataset.lightboxAlt || "";
    count.textContent = `${activeIndex + 1} / ${triggers.length}`;
  };

  triggers.forEach((trigger, index) => {
    trigger.addEventListener("click", () => {
      showImage(index);
      dialog.showModal();
    });
  });

  previous.addEventListener("click", () => showImage(activeIndex - 1));
  next.addEventListener("click", () => showImage(activeIndex + 1));
  dialog.querySelector("[data-lightbox-close]").addEventListener("click", () => {
    dialog.close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" && triggers.length > 1) {
      event.preventDefault();
      showImage(activeIndex - 1);
    } else if (event.key === "ArrowRight" && triggers.length > 1) {
      event.preventDefault();
      showImage(activeIndex + 1);
    }
  });

  if (triggers.length < 2) {
    previous.hidden = true;
    next.hidden = true;
    count.hidden = true;
  }
})();
