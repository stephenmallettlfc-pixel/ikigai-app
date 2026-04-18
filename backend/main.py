from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import anthropic
import json
import os
import uuid
import stripe
from pathlib import Path
from dotenv import load_dotenv
import html as html_lib

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__, static_folder=str(Path(__file__).parent.parent / "frontend"))
CORS(app)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
PRICE_PENCE = 499  # £4.99

# Temporary in-memory store for completed diagrams
results_store = {}

SYSTEM_PROMPT = """You are a warm, thoughtful ikigai guide. Ikigai (生き甲斐) is a Japanese concept meaning "reason for being" — the place where what you love, what you're good at, what the world needs, and what you can be paid for all overlap.

Your job is to guide the user through a gentle, conversational discovery of their ikigai. Here is how the conversation should flow:

1. OPENING: Introduce yourself warmly and briefly explain what ikigai is (2-3 sentences). Ask for their name. Keep it light and welcoming.

2. FOUR AREAS — work through these one at a time, asking 2-3 natural questions per area. Don't interrogate — be genuinely curious. Summarise what you've heard before moving on.

   WHAT YOU LOVE: Activities that make them lose track of time, topics they could talk about for hours, when they feel most alive.
   WHAT YOU'RE GOOD AT: What people come to them for help with, skills that feel natural but aren't obvious to others.
   WHAT THE WORLD NEEDS: Problems that genuinely bother them, communities they want to serve.
   WHAT YOU CAN BE PAID FOR: What they've been paid for, skills others would pay for.

3. SYNTHESIS: Reflect back what you heard. Walk through Passion (Love+Good At), Mission (Love+World Needs), Vocation (World Needs+Paid For), Profession (Good At+Paid For), and IKIGAI (all four). Ask if this feels right.

4. WHEN COMPLETE: Output this on its own line:
IKIGAI_DATA:{"name":"...","love":[...],"good_at":[...],"world_needs":[...],"paid_for":[...],"passion":"...","mission":"...","vocation":"...","profession":"...","ikigai":"...","next_steps":[{"title":"...","description":"...","url":"..."},{"title":"...","description":"...","url":"..."},{"title":"...","description":"...","url":"..."},{"title":"...","description":"...","url":"..."},{"title":"...","description":"...","url":"..."}]}

Give 5 specific next steps with real websites tailored to this person's ikigai (Climatebase, 80000hours.org, Idealist, Wellfound, Substack, Maven, Teachable, Coursera, Toptal, Gumroad, Patreon, Doximity, etc).

TONE: Warm, curious, encouraging. Never rush. Celebrate what people share."""


def items_html(items, label, max_items=5):
    if not items:
        return ""
    shown = items[:max_items]
    pills = "".join(f'<span class="pill">{html_lib.escape(str(item))}</span>' for item in shown)
    if len(items) > max_items:
        pills += f'<span class="pill pill-more">+{len(items)-max_items} more</span>'
    return f'<div class="card-label">{label}</div>{pills}'


def generate_diagram_html(data):
    name = html_lib.escape(data.get("name","Your"))
    love_html  = items_html(data.get("love",[]),       "What You Love")
    good_html  = items_html(data.get("good_at",[]),    "What You're Good At")
    needs_html = items_html(data.get("world_needs",[]),"What the World Needs")
    paid_html  = items_html(data.get("paid_for",[]),   "What You Can Be Paid For")
    passion    = html_lib.escape(data.get("passion",""))
    mission    = html_lib.escape(data.get("mission",""))
    vocation   = html_lib.escape(data.get("vocation",""))
    profession = html_lib.escape(data.get("profession",""))
    ikigai_stmt= html_lib.escape(data.get("ikigai",""))
    steps_html = ""
    for step in data.get("next_steps",[]):
        t = html_lib.escape(step.get("title",""))
        d = html_lib.escape(step.get("description",""))
        u = html_lib.escape(step.get("url","#"))
        steps_html += f'<div class="step-card"><div class="step-title"><a href="{u}" target="_blank">{t} &#8599;</a></div><p class="step-desc">{d}</p></div>'

    return f"""<\!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"/>
<title>{name} Ikigai</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Noto+Serif+JP:wght@400;700&display=swap');
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;background:#faf9f7;color:#1a1a2e;display:flex;flex-direction:column;align-items:center;padding:40px 20px 80px}}
.header{{text-align:center;margin-bottom:40px}}.kanji{{font-family:'Noto Serif JP',serif;font-size:2rem;color:#c0392b;letter-spacing:.15em}}
h1{{font-size:1.8rem;font-weight:700;margin-top:4px}}.subtitle{{font-size:.9rem;color:#888;margin-top:4px}}
.diagram-wrap{{position:relative;width:680px;height:680px;max-width:100%}}
.diagram-svg{{position:absolute;inset:0;width:100%;height:100%}}
.corner-card{{position:absolute;width:150px;padding:11px;border-radius:13px;background:white;box-shadow:0 2px 10px rgba(0,0,0,.08);display:flex;flex-direction:column;gap:4px;z-index:10}}
.card-label{{font-size:.56rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:2px;color:#888}}
.card-love{{top:8px;left:8px}}.card-good{{top:8px;right:8px}}.card-needs{{bottom:8px;left:8px}}.card-paid{{bottom:8px;right:8px}}
.pill{{display:inline-block;font-size:.63rem;font-weight:500;padding:2px 6px;border-radius:100px;margin:2px 2px 0 0;line-height:1.4}}
.card-love .pill{{background:#fdecea;color:#c0392b}}.card-good .pill{{background:#eaf4fb;color:#2471a3}}
.card-needs .pill{{background:#eafaf1;color:#1e8449}}.card-paid .pill{{background:#fdf2e9;color:#a04000}}.pill-more{{background:#f0f0f0;color:#888}}
.ikigai-callout{{margin-top:36px;max-width:580px;background:linear-gradient(135deg,#fff5f5,#fff8f0);border:1.5px solid #f5cba7;border-radius:18px;padding:24px 28px;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,.06)}}
.ikigai-callout .label{{font-size:.65rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#c0392b;margin-bottom:8px}}
.ikigai-callout p{{font-size:1rem;line-height:1.7;color:#2c2c2c}}
.intersections{{margin-top:28px;display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:680px;width:100%}}
.int-card{{background:white;border-radius:13px;padding:16px 18px;box-shadow:0 2px 8px rgba(0,0,0,.07);border-left:4px solid}}
.int-card.passion{{border-color:#8e44ad}}.int-card.mission{{border-color:#16a085}}.int-card.vocation{{border-color:#f39c12}}.int-card.profession{{border-color:#2980b9}}
.int-label{{font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#aaa;margin-bottom:4px}}
.int-title{{font-size:.9rem;font-weight:600;margin-bottom:4px}}
.int-card.passion .int-title{{color:#8e44ad}}.int-card.mission .int-title{{color:#16a085}}.int-card.vocation .int-title{{color:#f39c12}}.int-card.profession .int-title{{color:#2980b9}}
.int-card p{{font-size:.82rem;color:#555;line-height:1.55}}
.next-steps{{margin-top:36px;max-width:680px;width:100%}}.next-steps h2{{font-size:1.1rem;font-weight:700;margin-bottom:16px}}
.step-card{{background:white;border-radius:13px;padding:16px 18px;margin-bottom:10px;box-shadow:0 2px 8px rgba(0,0,0,.06);border-left:4px solid #c0392b}}
.step-title{{font-size:.9rem;font-weight:600;margin-bottom:5px}}.step-title a{{color:#c0392b;text-decoration:none}}.step-title a:hover{{text-decoration:underline}}
.step-desc{{font-size:.82rem;color:#555;line-height:1.55}}
.footer{{margin-top:40px;font-size:.72rem;color:#bbb;text-align:center}}
</style></head><body>
<div class="header"><div class="kanji">生き甲斐</div><h1>{name}'s Ikigai</h1><p class="subtitle">Your reason for being</p></div>
<div class="diagram-wrap">
<svg class="diagram-svg" viewBox="0 0 680 680" xmlns="http://www.w3.org/2000/svg">
<defs>
<radialGradient id="gL" cx="40%" cy="40%"><stop offset="0%" stop-color="#ff8a80"/><stop offset="100%" stop-color="#e53935" stop-opacity=".75"/></radialGradient>
<radialGradient id="gG" cx="60%" cy="40%"><stop offset="0%" stop-color="#82b1ff"/><stop offset="100%" stop-color="#1565c0" stop-opacity=".75"/></radialGradient>
<radialGradient id="gN" cx="40%" cy="60%"><stop offset="0%" stop-color="#69f0ae"/><stop offset="100%" stop-color="#2e7d32" stop-opacity=".75"/></radialGradient>
<radialGradient id="gP" cx="60%" cy="60%"><stop offset="0%" stop-color="#ffd180"/><stop offset="100%" stop-color="#e65100" stop-opacity=".75"/></radialGradient>
</defs>
<circle cx="262" cy="262" r="184" fill="url(#gL)" fill-opacity=".38"/>
<circle cx="418" cy="262" r="184" fill="url(#gG)" fill-opacity=".38"/>
<circle cx="262" cy="418" r="184" fill="url(#gN)" fill-opacity=".38"/>
<circle cx="418" cy="418" r="184" fill="url(#gP)" fill-opacity=".38"/>
<text x="340" y="182" text-anchor="middle" font-family="Inter,sans-serif" font-size="11" font-weight="700" fill="#6c3483" letter-spacing=".08em">PASSION</text>
<text x="172" y="346" text-anchor="middle" font-family="Inter,sans-serif" font-size="11" font-weight="700" fill="#0e6655" transform="rotate(-90,172,346)" letter-spacing=".08em">MISSION</text>
<text x="508" y="346" text-anchor="middle" font-family="Inter,sans-serif" font-size="11" font-weight="700" fill="#1a5276" transform="rotate(90,508,346)" letter-spacing=".08em">PROFESSION</text>
<text x="340" y="508" text-anchor="middle" font-family="Inter,sans-serif" font-size="11" font-weight="700" fill="#7d6608" letter-spacing=".08em">VOCATION</text>
<circle cx="340" cy="340" r="54" fill="white" fill-opacity=".85"/>
<text x="340" y="335" text-anchor="middle" font-family="'Noto Serif JP',serif" font-size="12" font-weight="700" fill="#c0392b">生き甲斐</text>
<text x="340" y="353" text-anchor="middle" font-family="Inter,sans-serif" font-size="10" font-weight="700" fill="#c0392b" letter-spacing=".1em">IKIGAI</text>
</svg>
<div class="corner-card card-love">{love_html}</div>
<div class="corner-card card-good">{good_html}</div>
<div class="corner-card card-needs">{needs_html}</div>
<div class="corner-card card-paid">{paid_html}</div>
</div>
<div class="ikigai-callout"><div class="label">Your Ikigai</div><p>{ikigai_stmt}</p></div>
<div class="intersections">
<div class="int-card passion"><div class="int-label">Love + Good At</div><div class="int-title">Passion</div><p>{passion}</p></div>
<div class="int-card mission"><div class="int-label">Love + World Needs</div><div class="int-title">Mission</div><p>{mission}</p></div>
<div class="int-card profession"><div class="int-label">Good At + Paid For</div><div class="int-title">Profession</div><p>{profession}</p></div>
<div class="int-card vocation"><div class="int-label">World Needs + Paid For</div><div class="int-title">Vocation</div><p>{vocation}</p></div>
</div>
<div class="next-steps"><h2>Your Next Steps</h2>{steps_html}</div>
<div class="footer">Generated with Claude · Ikigai App</div>
</body></html>"""


@app.route("/")
def serve_landing():
    return send_from_directory(app.static_folder, "landing.html")


@app.route("/app")
def serve_app():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/store-result", methods=["POST"])
def store_result():
    data = request.get_json()
    html = data.get("html", "")
    result_id = str(uuid.uuid4())
    results_store[result_id] = html
    return jsonify({"result_id": result_id})


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data = request.get_json()
    result_id = data.get("result_id", "")
    base_url = request.host_url.rstrip("/")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "gbp",
                    "product_data": {
                        "name": "Ikigai Discovery — Your Personal Results",
                        "description": "Your personalised Ikigai diagram and 5 tailored next steps"
                    },
                    "unit_amount": PRICE_PENCE,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base_url}/result?session_id={{CHECKOUT_SESSION_ID}}&result_id={result_id}",
            cancel_url=f"{base_url}/app",
        )
        return jsonify({"checkout_url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/result")
def show_result():
    session_id = request.args.get("session_id", "")
    result_id = request.args.get("result_id", "")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != "paid":
            return "Payment not completed. Please try again.", 402
    except Exception:
        return "Invalid payment session.", 400
    diagram_html = results_store.get(result_id, "")
    if not diagram_html:
        return "Your result has expired. Please complete the conversation again.", 404
    return diagram_html


@app.route("/chat", methods=["POST"])
def chat():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or "paste-your" in api_key:
        return jsonify({"error": "API key not set in .env file"}), 500

    data = request.get_json()
    messages = data.get("messages", [])
    client = anthropic.Anthropic(api_key=api_key)

    def stream():
        buffer = ""
        diagram_sent = False
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as s:
            for text in s.text_stream:
                buffer += text
                if "IKIGAI_DATA:" in buffer and not diagram_sent:
                    idx = buffer.find("IKIGAI_DATA:")
                    before = buffer[:idx].strip()
                    if before:
                        yield f"data: {json.dumps({'type':'text','content':before})}\n\n"
                    json_str = buffer[idx+12:].split("\n")[0].strip()
                    try:
                        d = json.loads(json_str)
                        diagram_html = generate_diagram_html(d)
                        yield f"data: {json.dumps({'type':'diagram','html':diagram_html})}\n\n"
                        diagram_sent = True
                        buffer = ""
                    except:
                        pass
                elif "IKIGAI_DATA:" not in buffer and len(buffer) > 40:
                    yield f"data: {json.dumps({'type':'text','content':buffer})}\n\n"
                    buffer = ""
        if buffer and "IKIGAI_DATA:" not in buffer:
            yield f"data: {json.dumps({'type':'text','content':buffer})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


if __name__ == "__main__":
    print("\n  Ikigai App is starting...")
    print("  Open your browser and go to: http://localhost:5000\n")
    app.run(debug=True, port=5000)
