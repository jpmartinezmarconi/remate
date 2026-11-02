(() => {
  const launcher = document.getElementById("help-bot-launcher");
  const panel = document.getElementById("help-bot-panel");
  const closeButton = document.getElementById("help-bot-close");
  const form = document.getElementById("help-bot-form");
  const input = document.getElementById("help-bot-input");
  const messages = document.getElementById("help-bot-messages");

  if (!launcher || !panel || !closeButton || !form || !input || !messages) {
    return;
  }

  const setOpen = (open) => {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    if (open) {
      input.focus();
    } else {
      launcher.focus();
    }
  };

  const addMessage = (text, sender, links = []) => {
    const message = document.createElement("div");
    message.className = `help-bot-message help-bot-message-${sender}`;
    message.textContent = text;
    messages.append(message);

    if (links.length) {
      const actions = document.createElement("div");
      actions.className = "help-bot-actions";
      for (const link of links) {
        const action = document.createElement("a");
        action.className = "help-bot-action";
        action.textContent = link.label;
        action.href = link.url;
        if (link.url.startsWith("https://")) {
          action.target = "_blank";
          action.rel = "noopener noreferrer";
        }
        actions.append(action);
      }
      messages.append(actions);
    }

    messages.scrollTop = messages.scrollHeight;
  };

  const ask = async (question) => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      return;
    }

    addMessage(trimmedQuestion, "user");
    input.value = "";
    input.disabled = true;
    form.querySelector("button[type='submit']").disabled = true;

    try {
      const response = await fetch(form.dataset.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmedQuestion }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.error || "No pudimos responder la consulta.");
      }
      addMessage(result.reply, "assistant", result.links);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No pudimos conectar con el asistente.";
      addMessage(
        `${message} Podés comunicarte al 096 430 909 o a info@rematemartinez.com.uy.`,
        "assistant",
        [
          { label: "WhatsApp", url: "https://wa.me/59896430909" },
          { label: "Enviar correo", url: "mailto:info@rematemartinez.com.uy" },
        ],
      );
    } finally {
      input.disabled = false;
      form.querySelector("button[type='submit']").disabled = false;
      input.focus();
    }
  };

  launcher.addEventListener("click", () => setOpen(panel.hidden));
  closeButton.addEventListener("click", () => setOpen(false));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(input.value);
  });
  panel.querySelectorAll("[data-help-question]").forEach((button) => {
    button.addEventListener("click", () => ask(button.dataset.helpQuestion));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      setOpen(false);
    }
  });
})();
