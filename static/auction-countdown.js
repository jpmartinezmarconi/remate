(() => {
  const timers = Array.from(
    document.querySelectorAll("[data-auction-countdown]")
  ).map((element) => {
    const output = element.querySelector("[data-countdown-value]");
    const deadline = Number(element.dataset.deadline);
    if (!output || !Number.isFinite(deadline)) return null;

    return () => {
      const remaining = Math.max(0, deadline - Math.floor(Date.now() / 1000));
      const hours = Math.floor(remaining / 3600);
      const minutes = Math.floor((remaining % 3600) / 60);
      const seconds = remaining % 60;
      output.textContent = [hours, minutes, seconds]
        .map((part) => String(part).padStart(2, "0"))
        .join(":");
      element.classList.toggle("is-urgent", remaining > 0 && remaining <= 60);

      if (remaining === 0) {
        const wasSold = element.dataset.hasBids === "true";
        output.textContent = "FINALIZADA";
        element.classList.remove("is-urgent");
        element.classList.add("is-finished");
        const status = document.querySelector("[data-auction-status]");
        if (status) {
          status.textContent = wasSold ? "SUBASTADO" : "SUBASTA FINALIZADA";
        }
        const card = element.closest(".auction-card");
        if (card) {
          const badge = card.querySelector(".live-tag");
          if (badge) {
            badge.textContent = wasSold ? "SUBASTADO" : "FINALIZADO";
            badge.classList.toggle("sold-tag", wasSold);
          }
          const action = card.querySelector(".btn-auction");
          if (action) {
            action.classList.remove("btn-auction");
            action.classList.add("btn-outline-secondary");
            action.textContent = "Ver resultado";
          }
        }
        document
          .querySelectorAll('[data-bid-form] input, [data-bid-form] button')
          .forEach((control) => {
            control.disabled = true;
          });
        return false;
      }
      return true;
    };
  }).filter(Boolean);

  if (!timers.length) return;

  const render = () => {
    let running = false;
    timers.forEach((timer) => {
      if (timer()) running = true;
    });
    return running;
  };
  if (render()) {
    const interval = window.setInterval(() => {
      if (!render()) window.clearInterval(interval);
    }, 1000);
  }
})();
