from flask import Flask, render_template, request, jsonify
from gpt4all import GPT4All
import os

print("1) APP.PY A PORNIT", flush=True)


app = Flask(__name__)

# Pune modelul aici: ai-tutor-linux/models/mistral-7b-instruct-v0.1.Q4_0.gguf
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
        model_error = f"Eroare la încărcarea modelului: {e}"
        return None


def build_prompt(mode: str, text: str) -> str:
    text = text.strip()

    if mode == "translate":
        return (
            "Transformă cerința în limbaj natural într-o comandă Linux Bash.\n"
            "Răspunde DOAR cu comanda, fără explicații, fără ghilimele.\n"
            "Dacă sunt necesare mai multe comenzi, folosește operatori (&&, |, ;).\n\n"
            f"Cerință: {text}\n"
            "Comandă:"
        )

    if mode == "explain":
        return (
            "Explică pas cu pas ce face comanda Linux de mai jos.\n"
            "Folosește puncte scurte (1-6 pași). Fără text în plus.\n\n"
            f"Comandă: {text}\n"
            "Explicație:"
        )

    # exercise
    return (
        "Generează un exercițiu scurt pentru Linux Bash (nivel: începător-med).\n"
        "Apoi dă o soluție (comanda corectă).\n"
        "Format obligatoriu:\n"
        "Exercițiu: ...\n"
        "Soluție: ...\n\n"
        f"Temă/Preferință (opțional): {text}\n"
    )


@app.route("/")
def index():
    return render_template("index.html")


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
        # temperature mic pentru răspunsuri stabile
        output = m.generate(prompt, temp=0.2, max_tokens=256)
        return jsonify({"ok": True, "result": output.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Eroare la generare: {e}"}), 500

print("2) INAINTE DE MAIN CHECK", flush=True)


if __name__ == "__main__":
    print("3) IN MAIN - PORNESC FLASK", flush=True)
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)




