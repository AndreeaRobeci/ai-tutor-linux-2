from flask import Flask, render_template, request, jsonify
from gpt4all import GPT4All
from pdf_loader import load_pdf_text
import os
import json


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
pdf_path = os.path.join(BASE_DIR, "data", "AI-tutor-linux resurse.pdf")
json_path = os.path.join(BASE_DIR, "data", "exercices.json")


PDF_CONTENT = load_pdf_text(pdf_path)

print("1) APP.PY A PORNIT", flush=True)


app = Flask(__name__)


MODEL_PATH = os.path.join("models", "mistral-7b-instruct-v0.1.Q4_0.gguf")

model = None
model_error = None

def get_model():
    global model, model_error

    if model is not None:
        return model
    if model_error is not None:
        return None

    full_path = os.path.abspath(MODEL_PATH)

    if not os.path.exists(full_path):
        model_error = f"Modelul nu există la: {full_path}"
        return None

    try:
        model = GPT4All(
            model_name=full_path,
            model_path=os.path.dirname(full_path),
            allow_download=False,
            device="cpu"
        )
        return model
    except Exception as e:
        model_error = f"Eroare la incarcarea modelului: {e}"
        return None


def build_prompt(mode: str, text: str) -> str:
    context = f"""
    Foloseste urmatoarea documentatie pentru raspunsuri:

    {PDF_CONTENT[:4000]}
    """

    if mode == "translate":
        return (
            context +
            "\nTransforma cerinta in limbaj natural intr-o comanda Linux Bash.\n"
            "Raspunde DOAR cu comanda.\n\n"
            f"Cerinta: {text}\nComanda:"
        )

    if mode == "explain":
        return (
            context +
            "\nExplica pas cu pas comanda Linux.\n\n"
            f"Comanda: {text}\nExplicatie:"
        )

@app.route("/")


def index():
    return render_template("index.html")

# -------------------------------

#pagina exercitii
@app.route("/exercitii")
def exercitii_page():
    return render_template("exercices.html")


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json(force=True)
    mode = (data.get("mode") or "translate").strip()
    text = (data.get("text") or "").strip()

    if mode not in {"translate", "explain", "exercise"}:
        return jsonify({"ok": False, "error": "Mode invalid."}), 400

    if not text and mode != "exercise":
        return jsonify({"ok": False, "error": "Scrie ceva în input."}), 400

    m = get_model()
    if m is None:
        return jsonify({"ok": False, "error": model_error or "Modelul nu e încă încărcat."}), 500

    prompt = build_prompt(mode, text)

    try:
        # temperature mic pentru raspunsuri stabile
        output = m.generate(prompt, temp=0.2, max_tokens=256)
        return jsonify({"ok": True, "result": output.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Eroare la generare: {e}"}), 500

print("2) INAINTE DE MAIN CHECK", flush=True)


@app.route("/api/exercises", methods=["GET"])
def get_exercises():
    try:
        # Deschidem fisierul JSON și îl citim
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Îl trimitem ca răspuns valid către frontend
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Nu am putut citi JSON-ul: {e}"}), 500






if __name__ == "__main__":
    print("3) IN MAIN - PORNESC FLASK", flush=True)
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)





