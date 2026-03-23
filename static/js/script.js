const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const messagesContainer = document.getElementById("chat-messages");
const sendButton = document.getElementById("send-button");

function addMessage(text, sender, options = {}) {
    const bubble = document.createElement("article");
    bubble.classList.add("message");

    if (sender === "user") {
        bubble.classList.add("user-message");
    } else {
        bubble.classList.add("bot-message");
    }

    if (options.typing) {
        bubble.classList.add("typing");
    }

    bubble.textContent = text;
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return bubble;
}

async function sendMessage() {
    const userText = input.value.trim();
    if (!userText) {
        return;
    }

    addMessage(userText, "user");
    input.value = "";
    input.focus();

    // Enquanto a API responde, exibimos um indicador visual para o usuario.
    const typingIndicator = addMessage("CardioIA esta digitando...", "bot", { typing: true });

    sendButton.disabled = true;
    input.disabled = true;

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ message: userText }),
        });

        const payload = await response.json();

        typingIndicator.remove();

        if (!response.ok) {
            const errorMessage = payload.error || "Nao foi possivel processar sua mensagem agora.";
            addMessage(errorMessage, "bot");
            return;
        }

        addMessage(payload.response || "Sem resposta textual no momento.", "bot");
    } catch (error) {
        typingIndicator.remove();
        addMessage("Erro de conexao com o servidor. Tente novamente.", "bot");
    } finally {
        sendButton.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function loadWelcomeMessage() {
    const typingIndicator = addMessage("CardioIA esta digitando...", "bot", { typing: true });

    try {
        const response = await fetch("/welcome", {
            method: "GET",
        });

        const payload = await response.json();
        typingIndicator.remove();

        if (!response.ok) {
            addMessage("Ola! Eu sou o CardioIA. Como posso ajudar hoje?", "bot");
            return;
        }

        addMessage(payload.response || "Ola! Eu sou o CardioIA. Como posso ajudar hoje?", "bot");
    } catch (error) {
        typingIndicator.remove();
        addMessage("Ola! Eu sou o CardioIA. Como posso ajudar hoje?", "bot");
    }
}

// O evento submit cobre clique no botao e Enter no campo de texto.
form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await sendMessage();
});

window.addEventListener("DOMContentLoaded", async () => {
    await loadWelcomeMessage();
});
