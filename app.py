import os
import threading
from typing import Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from ibm_watson import AssistantV2

# Carrega variaveis do arquivo .env para o ambiente da aplicacao.
# Esperado no .env:
# API_KEY=...
# SERVICE_URL=...
# ENVIRONMENT_ID=...
load_dotenv()

# Leitura das variaveis em memoria para uso no cliente Watson.
API_KEY = os.getenv("API_KEY")
SERVICE_URL = os.getenv("SERVICE_URL")
ENVIRONMENT_ID = os.getenv("ENVIRONMENT_ID")
ASSISTANT_ID = os.getenv("ASSISTANT_ID", ENVIRONMENT_ID)
WATSON_USER_ID = os.getenv("WATSON_USER_ID", "cardioia-web-user")

# Inicializa a aplicacao Flask.
app = Flask(__name__)

# Variaveis globais para manter o cliente Watson e o session_id ativo.
# Em ambiente academico (beta), manter em memoria e suficiente.
assistant_client: Optional[AssistantV2] = None
session_id: Optional[str] = None

# Lock para evitar corrida caso duas requisicoes tentem criar sessao ao mesmo tempo.
session_lock = threading.Lock()


def create_assistant_client() -> AssistantV2:
    """
    Cria e retorna um cliente do Watson Assistant v2.

    Etapas da autenticacao:
    1) Usa IAMAuthenticator com API_KEY
    2) Instancia AssistantV2 com versao da API
    3) Define a URL do servico
    """
    if not API_KEY or not SERVICE_URL or not ENVIRONMENT_ID:
        # Erro explicito para facilitar depuracao e documentacao do projeto.
        raise ValueError(
            "Variaveis obrigatorias ausentes no .env: API_KEY, SERVICE_URL ou ENVIRONMENT_ID."
        )

    authenticator = IAMAuthenticator(API_KEY)
    assistant = AssistantV2(
        version="2024-08-25",
        authenticator=authenticator,
    )
    assistant.set_service_url(SERVICE_URL)
    return assistant


def create_watson_session() -> str:
    """
    Cria uma nova sessao no Watson Assistant e retorna o session_id.

    O Watson v2 exige session_id para manter contexto conversacional.
    """
    global assistant_client

    if assistant_client is None:
        assistant_client = create_assistant_client()

    response = assistant_client.create_session(
        assistant_id=ASSISTANT_ID,
        environment_id=ENVIRONMENT_ID,
    ).get_result()
    return response["session_id"]


def ensure_session() -> str:
    """
    Garante que exista um session_id valido antes de enviar mensagem.

    Usa lock para garantir seguranca em ambiente com multiplas requisicoes.
    """
    global session_id

    if session_id:
        return session_id

    with session_lock:
        # Revalida dentro da secao critica para evitar criacao duplicada.
        if not session_id:
            session_id = create_watson_session()

    return session_id


def extract_text_response(watson_result: dict) -> str:
    """
    Extrai somente texto da resposta do Watson, conforme requisito da atividade.

    Estrutura esperada:
    output.generic[] com itens de response_type='text'.
    """
    output = watson_result.get("output", {})
    generic_items = output.get("generic", [])

    # Agrega multiplos blocos da resposta para nao perder informacoes relevantes
    # (ex.: texto + opcoes sugeridas no mesmo turno do Watson).
    texts = []

    # Alguns assistants retornam output.text como lista de strings.
    text_list = output.get("text", [])
    if isinstance(text_list, list):
        for value in text_list:
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())

    for item in generic_items:
        response_type = item.get("response_type")

        if response_type == "text" and item.get("text"):
            texts.append(item["text"].strip())

        elif response_type == "option":
            title = (item.get("title") or "").strip()
            options = item.get("options", [])
            option_labels = []

            for option in options:
                label = (option.get("label") or "").strip()
                if label:
                    option_labels.append(f"- {label}")

            if title:
                texts.append(title)
            if option_labels:
                texts.append("\n".join(option_labels))

    if texts:
        # Remove duplicidades preservando ordem para manter a resposta limpa.
        unique_texts = list(dict.fromkeys(texts))
        return "\n\n".join(unique_texts)

    # Fallback profissional para casos em que o assistente nao devolve texto simples.
    return "Desculpe, nao foi possivel obter uma resposta textual no momento."


@app.route("/", methods=["GET"])
def index():
    """
    Renderiza a interface web principal do CardioIA.
    """
    return render_template("index.html")


@app.route("/welcome", methods=["GET"])
def welcome():
    """
    Retorna a mensagem inicial do Watson Assistant.

    Essa rota permite que o front exiba exatamente o texto de boas-vindas
    configurado no Assistant, evitando divergencia com mensagens estaticas.
    """
    global session_id

    try:
        current_session_id = ensure_session()

        watson_result = assistant_client.message(
            assistant_id=ASSISTANT_ID,
            environment_id=ENVIRONMENT_ID,
            session_id=current_session_id,
            user_id=WATSON_USER_ID,
        ).get_result()

        reply_text = extract_text_response(watson_result)
        return jsonify({"response": reply_text}), 200

    except Exception:
        try:
            with session_lock:
                session_id = create_watson_session()

            watson_result = assistant_client.message(
                assistant_id=ASSISTANT_ID,
                environment_id=ENVIRONMENT_ID,
                session_id=session_id,
                user_id=WATSON_USER_ID,
            ).get_result()

            reply_text = extract_text_response(watson_result)
            return jsonify({"response": reply_text}), 200

        except Exception as retry_error:
            return (
                jsonify(
                    {
                        "error": "Falha ao carregar a mensagem inicial do Watson.",
                        "details": str(retry_error) if app.debug else "Tente novamente em instantes.",
                    }
                ),
                502,
            )


@app.route("/chat", methods=["POST"])
def chat():
    """
    Endpoint principal do backend.

    Entrada esperada (JSON):
    {
      "message": "texto do usuario"
    }

    Saida (JSON):
    {
      "response": "texto retornado pelo Watson"
    }
    """
    global session_id

    try:
        # Valida se o corpo da requisicao e JSON.
        if not request.is_json:
            return jsonify({"error": "Content-Type deve ser application/json."}), 400

        payload = request.get_json(silent=True) or {}
        user_message = (payload.get("message") or "").strip()

        if not user_message:
            return jsonify({"error": "Campo 'message' e obrigatorio."}), 400

        # Garante que existe sessao antes de chamar o Watson.
        current_session_id = ensure_session()

        # Envia a mensagem do usuario para o Watson Assistant v2.
        watson_result = assistant_client.message(
            assistant_id=ASSISTANT_ID,
            environment_id=ENVIRONMENT_ID,
            session_id=current_session_id,
            user_id=WATSON_USER_ID,
            input={
                "message_type": "text",
                "text": user_message,
            },
        ).get_result()

        # Retorna somente texto da resposta, conforme solicitado.
        reply_text = extract_text_response(watson_result)
        return jsonify({"response": reply_text}), 200

    except Exception as error:
        # Se a sessao estiver invalida/expirada, tenta recriar uma vez e reenviar.
        # Isso reduz impacto de falhas temporarias sem derrubar o servidor.
        try:
            with session_lock:
                session_id = create_watson_session()

            payload = request.get_json(silent=True) or {}
            user_message = (payload.get("message") or "").strip()

            watson_result = assistant_client.message(
                assistant_id=ASSISTANT_ID,
                environment_id=ENVIRONMENT_ID,
                session_id=session_id,
                user_id=WATSON_USER_ID,
                input={
                    "message_type": "text",
                    "text": user_message,
                },
            ).get_result()

            reply_text = extract_text_response(watson_result)
            return jsonify({"response": reply_text}), 200

        except Exception as retry_error:
            # Nao propaga stack trace ao cliente final.
            # Mantem resposta padrao e profissional para API beta.
            return (
                jsonify(
                    {
                        "error": "Falha ao comunicar com o Watson Assistant.",
                        "details": str(retry_error) if app.debug else "Tente novamente em instantes.",
                    }
                ),
                502,
            )


if __name__ == "__main__":
    # Tenta inicializar cliente/sessao no startup para reduzir latencia da 1a mensagem.
    # Se falhar, o sistema ainda tenta novamente na primeira chamada de /chat.
    try:
        assistant_client = create_assistant_client()
        session_id = create_watson_session()
    except Exception as startup_error:
        print(f"Aviso: nao foi possivel inicializar sessao no startup: {startup_error}")

    app.run(host="0.0.0.0", port=5000, debug=True)
