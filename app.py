"""
Nucleus AI - B2B AI SaaS Platform
"When Your Business Thinks for Itself"
"""
import os
import re
import secrets
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import openai

db_url = os.environ.get("DATABASE_URL", "sqlite:///nucleus.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or "sqlite:///nucleus.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

db = SQLAlchemy(app)


class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    industry = db.Column(db.String(50), nullable=False)
    context_data = db.Column(db.Text, nullable=True)
    system_prompt = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_status = db.Column(db.String(20), default='free')
    agent_limit = db.Column(db.Integer, default=1)
    lead_limit = db.Column(db.Integer, default=10)
    leads = db.relationship('Lead', backref='business', lazy=True, cascade='all, delete-orphan')

    def can_access_bot(self):
        return self.subscription_status in ['free', 'starter', 'pro', 'agency']
    
    def update_subscription_limits(self):
        limits = {'free': (1, 10), 'starter': (1, 500), 'pro': (3, -1), 'agency': (10, -1)}
        self.agent_limit, self.lead_limit = limits.get(self.subscription_status, (1, 10))


class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    customer_contact = db.Column(db.String(100), nullable=True)
    intent = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def generate_system_prompt(business_name, industry, context_data):
    """The SECRET: Identity, not instructions"""
    
    return f"""أنت {business_name}.

هذه متجرك. أنت المالك.

=== معلومات متجرك ===
{context_data}
====================

الآن عميل دخل عليك.

كيف تتصرف؟
- ترحب فيه طبيعي جداً
- تسأله "إزيك؟ عامل إيه؟"
- تسأله "محتاج إيه النهاردة؟"
- لو سألك على حاجة من اللي عندك، تقوله
- لو عجبه، تسأله "هتاخد؟"
- لو هياخد، تطلب منه رقمه
- لو مش عارف حاجة، قول "دعني أتأكد"

طريقة كلامك:
- مصرية طبيعية: "يا باشا"، "يا فندم"، "إن شاء الله"
- او إنجليزية لو هو بيتكلم إنجليزي
- إيموجي شوية
- مهتم بيه فعلاً

مهم: أنت مش "AI"، أنت صاحب المحل."""


def detect_language(text):
    if not text:
        return 'ar'
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return 'ar' if arabic > len(text) * 0.2 else 'en'


def get_ai_response(messages, business_id):
    api_key = os.environ.get('GROK_API_KEY') or os.environ.get('GROQ_API_KEY')
    business = Business.query.get(business_id)
    
    if not business:
        return "خطأ - حاول مرة أخرى"
    
    if not api_key:
        return fallback_response(messages, business)
    
    conversation = [{"role": "system", "content": business.system_prompt}]
    conversation.extend(messages[-8:])
    
    try:
        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-2-latest",
            messages=conversation,
            temperature=0.9,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Grok error: {e}")
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=conversation,
                temperature=0.9,
                max_tokens=500
            )
            return response.choices[0].message.content
        except:
            return fallback_response(messages, business)


def fallback_response(messages, business):
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last = m.get("content", "").lower()
            break
    
    name = business.name
    ctx = business.context_data or ""
    lang = detect_language(last)
    
    phone = re.search(r'(01[0-25][0-9]{8})', last)
    if phone:
        nm = re.search(r'(?:اسمي|أنا|name is)\s+(\w+)', last, re.I)
        n = nm.group(1) if nm else "صديقي"
        if not Lead.query.filter_by(business_id=business.id, customer_contact=phone.group()).first():
            db.session.add(Lead(business_id=business.id, customer_name=n, customer_contact=phone.group()))
            db.session.commit()
        return f"تمام يا {n}! 📞 هكلمك على {phone.group()}!" if lang == 'ar' else f"Got it {n}! I'll call {phone.group()}!"
    
    if lang == 'ar':
        if 'مرحبا' in last or 'اهلا' in last or 'هاي' in last:
            return f"أهلاً بيك في {name}! 😊 إزيك؟ أقدر أساعدك بإيه؟"
        if 'ازيك' in last or 'عامل ايه' in last:
            return "الحمد لله بخير! 😊 وأنت؟ محتاج حاجة؟"
        if 'سعر' in last or 'بكم' in last:
            return f"بص يا باشا، عندنا:\n{ctx}\nإيه اللي عاجبك؟"
        if 'عندكم' in last or 'منتج' in last:
            return f"عندنا الحاجات دي:\n{ctx}\nقولي بتصور إيه؟"
        return f"أهلاً في {name}! 😊 أساعدك بإيه؟"
    else:
        if 'hello' in last or 'hi' in last:
            return f"Hey! 👋 Welcome to {name}! How can I help?"
        if 'price' in last or 'cost' in last:
            return f"Here's what we have:\n{ctx}\nWhat interests you?"
        return f"Welcome to {name}! 😊 How can I help?"


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html')

@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    if request.method == 'POST':
        d = request.form
        b = Business(
            name=d.get('business_name', '').strip(),
            industry=d.get('industry', 'Generic/Other'),
            context_data=d.get('context_data', '').strip(),
            system_prompt=generate_system_prompt(d.get('business_name', ''), d.get('industry'), d.get('context_data', ''))
        )
        b.update_subscription_limits()
        db.session.add(b)
        db.session.commit()
        return redirect(url_for('dashboard', business_id=b.id))
    return render_template('onboarding.html')

@app.route('/dashboard/<int:business_id>')
def dashboard(business_id):
    b = Business.query.get_or_404(business_id)
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return render_template('dashboard.html', business=b, leads=leads)

@app.route('/api/chat', methods=['POST'])
def chat():
    d = request.get_json()
    b = Business.query.get(d.get('business_id'))
    if not b or not b.can_access_bot():
        return jsonify({'error': 'Subscription required'}), 403
    return jsonify({'response': get_ai_response(d.get('messages', []), d.get('business_id')), 'success': True})

@app.route('/api/leads/<int:business_id>')
def get_leads(business_id):
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return jsonify({'leads': [{'name': l.customer_name, 'contact': l.customer_contact} for l in leads]})

@app.route('/api/delete-lead/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    Lead.query.get_or_404(lead_id)
    db.session.delete(Lead.query.get(lead_id))
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/create-checkout-session', methods=['POST'])
def checkout():
    d = request.get_json()
    b = Business.query.get(d.get('business_id'))
    if b:
        b.subscription_status = d.get('plan', 'pro')
        b.update_subscription_limits()
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))