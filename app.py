"""
Nucleus AI - B2B AI SaaS Platform
"When Your Business Thinks for Itself"
"""
import os
import json
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
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PRICES = {
    'starter': os.environ.get('STRIPE_STARTER_PRICE', 'price_starter'),
    'pro': os.environ.get('STRIPE_PRO_PRICE', 'price_pro'),
    'agency': os.environ.get('STRIPE_AGENCY_PRICE', 'price_agency')
}

db = SQLAlchemy(app)

# ============== MODELS ==============

class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    industry = db.Column(db.String(50), nullable=False)
    context_data = db.Column(db.Text, nullable=True)
    system_prompt = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_status = db.Column(db.String(20), default='free')
    subscription_id = db.Column(db.String(100), nullable=True)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    subscription_end = db.Column(db.DateTime, nullable=True)
    agent_limit = db.Column(db.Integer, default=1)
    lead_limit = db.Column(db.Integer, default=10)
    leads = db.relationship('Lead', backref='business', lazy=True, cascade='all, delete-orphan')

    def can_access_bot(self):
        return self.subscription_status in ['free', 'starter', 'pro', 'agency']
    
    def update_subscription_limits(self):
        limits = {'free': {'agents': 1, 'leads': 10}, 'starter': {'agents': 1, 'leads': 500}, 'pro': {'agents': 3, 'leads': -1}, 'agency': {'agents': 10, 'leads': -1}}
        tier_limits = limits.get(self.subscription_status, limits['free'])
        self.agent_limit = tier_limits['agents']
        self.lead_limit = tier_limits['leads']

class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    customer_contact = db.Column(db.String(100), nullable=True)
    intent = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============== SYSTEM PROMPT ==============

def generate_system_prompt(business_name, industry, context_data):
    prompts = {
        'E-commerce/Clothing': f"""You are a friendly AI sales assistant for {business_name}.

KNOWLEDGE BASE:
---
{context_data}
---

RULES:
1. Be natural and conversational - like a real human
2. DO NOT dump all info - respond only to what's asked
3. Greet warmly when customer says hello, ask how to help
4. When asked about products/prices, give ONLY relevant info
5. When customer shows interest, ask for name and phone
6. Match customer's language (Arabic/English)""",

        'Gym/Fitness': f"""You are an energetic fitness consultant for {business_name}.

KNOWLEDGE BASE:
---
{context_data}
---

RULES:
1. Be motivating and energetic
2. DO NOT dump all info - respond to questions only
3. Greet warmly, ask about fitness goals
4. Share pricing only when asked
5. Ask for name and phone when interested
6. Match customer's language""",

        'Generic/Other': f"""You are a helpful AI assistant for {business_name}.

KNOWLEDGE BASE:
---
{context_data}
---

RULES:
1. Be friendly and professional
2. DO NOT dump all information at once
3. Respond only to what is asked
4. Use knowledge base for accurate answers
5. Ask for contact info when customer shows interest
6. Match customer's language"""
    }
    return prompts.get(industry, prompts['Generic/Other'])

# ============== AI FUNCTIONS ==============

def detect_language(text):
    if not text:
        return 'en'
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return 'ar' if arabic_chars > len(text) * 0.3 else 'en'

def get_grok_response(messages, business_id):
    api_key = os.environ.get('GROK_API_KEY') or os.environ.get('GROQ_API_KEY')
    
    if not api_key:
        return get_mock_response(messages, business_id)
    
    business = Business.query.get(business_id)
    if not business:
        return "Error: Business not found"
    
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    lang = detect_language(user_message)
    lang_instruction = "\n\nIMPORTANT: Respond in Arabic only." if lang == 'ar' else "\n\nIMPORTANT: Respond in English only."
    
    full_system_prompt = business.system_prompt + lang_instruction
    
    try:
        client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        full_messages = [{"role": "system", "content": full_system_prompt}]
        full_messages.extend(messages)
        
        response = client.chat.completions.create(
            model="grok-2-latest",
            messages=full_messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"API Error: {e}")
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            full_messages = [{"role": "system", "content": full_system_prompt}]
            full_messages.extend(messages)
            response = client.chat.completions.create(model="llama3-8b-8192", messages=full_messages, temperature=0.7)
            return response.choices[0].message.content
        except:
            return get_mock_response(messages, business_id)

def get_mock_response(messages, business_id):
    business = Business.query.get(business_id)
    if not business:
        return "Error: Business not found"
    
    business_name = business.name
    context_data = business.context_data or ""
    
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    lang = detect_language(user_message)
    msg_lower = user_message.lower()
    
    # Lead capture
    name_match = re.search(r'(?:my name is|i\'m|اسمي|أنا)\s+([a-zA-Z\u0600-\u06FF\s]+)', user_message, re.IGNORECASE)
    phone_match = re.search(r'(\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|\+\d[\d\s-]{10,})', user_message)
    
    if name_match and phone_match:
        name = name_match.group(1).strip()
        contact = phone_match.group(0)
        lead = Lead(business_id=business_id, customer_name=name, customer_contact=contact, intent=f"Captured: {user_message[:50]}")
        db.session.add(lead)
        db.session.commit()
        return f"شكراً {name}! ✅ تم تسجيلك." if lang == 'ar' else f"Thank you {name}! ✅ You're registered."
    
    if lang == 'ar':
        if any(w in msg_lower for w in ['مرحبا', 'اهلا', 'السلام', 'هاي']):
            return f"أهلاً بك في {business_name}! 👋 كيف يمكنني مساعدتك؟"
        elif any(w in msg_lower for w in ['سعر', 'بكم', 'اسعار']):
            return f"💰 الأسعار:\n{context_data}"
        elif any(w in msg_lower for w in ['منتج', 'عندكم']):
            return f"📦 المنتجات:\n{context_data}"
        else:
            return f"كيف يمكنني مساعدتك؟ 🙏"
    else:
        if any(w in msg_lower for w in ['hello', 'hi', 'hey']):
            return f"Hello! 👋 Welcome to {business_name}. How can I help you?"
        elif any(w in msg_lower for w in ['price', 'cost', 'how much']):
            return f"💰 Pricing:\n{context_data}"
        elif any(w in msg_lower for w in ['product', 'available']):
            return f"📦 Products:\n{context_data}"
        else:
            return f"How can I help you today? 🙏"

# ============== ROUTES ==============

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
        data = request.form
        business = Business(
            name=data.get('business_name', '').strip(),
            industry=data.get('industry', 'Generic/Other'),
            context_data=data.get('context_data', '').strip(),
            system_prompt=generate_system_prompt(data.get('business_name', ''), data.get('industry', 'Generic/Other'), data.get('context_data', ''))
        )
        business.update_subscription_limits()
        db.session.add(business)
        db.session.commit()
        return redirect(url_for('dashboard', business_id=business.id))
    return render_template('onboarding.html')

@app.route('/dashboard/<int:business_id>')
def dashboard(business_id):
    business = Business.query.get_or_404(business_id)
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return render_template('dashboard.html', business=business, leads=leads)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    business_id = data.get('business_id')
    messages = data.get('messages', [])
    
    business = Business.query.get(business_id)
    if not business or not business.can_access_bot():
        return jsonify({'error': 'Subscription required'}), 403
    
    response = get_grok_response(messages, business_id)
    return jsonify({'response': response, 'success': True})

@app.route('/api/leads/<int:business_id>')
def get_leads(business_id):
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return jsonify({'leads': [{'name': l.customer_name, 'contact': l.customer_contact} for l in leads]})

@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout_session():
    data = request.get_json()
    business = Business.query.get(data.get('business_id'))
    if business:
        business.subscription_status = data.get('plan')
        business.update_subscription_limits()
        business.subscription_end = datetime.utcnow() + timedelta(days=30)
        db.session.commit()
        return jsonify({'success': True, 'redirect': f'/dashboard/{business.id}?subscription=success'})
    return jsonify({'error': 'Not found'}), 404

with app.app_context():
    db.create_all()
    print("✅ Database ready!")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))