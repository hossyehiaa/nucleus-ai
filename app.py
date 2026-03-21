"""
Nucleus AI - B2B AI SaaS Platform
"When Your Business Thinks for Itself"

Features:
- Grok API (xAI) Integration
- Stripe Subscription System
- Multi-language Support (EN/AR)
- Custom Branding
"""
import os
import json
import re
import secrets
from datetime import datetime, timedelta

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import openai  # Using OpenAI SDK for Grok API

# Render gives a postgres:// URL but SQLAlchemy requires postgresql://
db_url = os.environ.get("DATABASE_URL", "sqlite:///nucleus.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Initialize Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# Stripe Configuration
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICES = {
    'starter': os.environ.get('STRIPE_STARTER_PRICE', 'price_starter'),
    'pro': os.environ.get('STRIPE_PRO_PRICE', 'price_pro'),
    'agency': os.environ.get('STRIPE_AGENCY_PRICE', 'price_agency')
}

# Initialize database
db = SQLAlchemy(app)

# ============== DATABASE MODELS ==============

class Business(db.Model):
    """Business model for storing company information"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    industry = db.Column(db.String(50), nullable=False)
    context_data = db.Column(db.Text, nullable=True)
    system_prompt = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Subscription fields
    subscription_status = db.Column(db.String(20), default='free')
    subscription_id = db.Column(db.String(100), nullable=True)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    subscription_end = db.Column(db.DateTime, nullable=True)
    
    # Agent limits based on subscription
    agent_limit = db.Column(db.Integer, default=1)
    lead_limit = db.Column(db.Integer, default=10)
    
    # Relationships
    leads = db.relationship('Lead', backref='business', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'industry': self.industry,
            'context_data': self.context_data,
            'system_prompt': self.system_prompt,
            'subscription_status': self.subscription_status,
            'agent_limit': self.agent_limit,
            'lead_limit': self.lead_limit,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def can_access_bot(self):
        return self.subscription_status in ['free', 'starter', 'pro', 'agency']
    
    def update_subscription_limits(self):
        limits = {
            'free': {'agents': 1, 'leads': 10},
            'starter': {'agents': 1, 'leads': 500},
            'pro': {'agents': 3, 'leads': -1},
            'agency': {'agents': 10, 'leads': -1}
        }
        tier_limits = limits.get(self.subscription_status, limits['free'])
        self.agent_limit = tier_limits['agents']
        self.lead_limit = tier_limits['leads']


class Lead(db.Model):
    """Lead model for storing captured customer information"""
    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)
    customer_contact = db.Column(db.String(100), nullable=True)
    intent = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'business_id': self.business_id,
            'customer_name': self.customer_name,
            'customer_contact': self.customer_contact,
            'intent': self.intent,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else None
        }


# ============== SYSTEM PROMPT GENERATOR ==============

def generate_system_prompt(business_name, industry, context_data):
    """Generate industry-specific system prompt with full context"""
    
    industry_configs = {
        'E-commerce/Clothing': {
            'en': f"""You are an AI sales representative for {business_name}, a fashion and clothing store.

═══════════════════════════════════════
📊 COMPLETE BUSINESS KNOWLEDGE BASE:
═══════════════════════════════════════
{context_data}

═══════════════════════════════════════
📋 CRITICAL INSTRUCTIONS:
═══════════════════════════════════════
1. ALWAYS use the EXACT information from the knowledge base above
2. When asked about products, quote EXACT prices and details
3. When asked about services/offers, use EXACT details from the knowledge base
4. When asked about hours/location, use EXACT information
5. Be specific - don't give generic answers when you have real data
6. If something isn't in the knowledge base, say "Let me check that for you"
7. When customer shows interest, ask for their NAME and PHONE NUMBER
8. Format lead captures as: [LEAD_CAPTURE: name="Name" contact="Phone" intent="Details"]

Your personality: Friendly, stylish, fashion-forward, helpful.""",

            'ar': f"""أنت مساعد مبيعات ذكي لـ {business_name}، متجر أزياء وملابس.

═══════════════════════════════════════
📊 قاعدة معلومات العمل الكاملة:
═══════════════════════════════════════
{context_data}

═══════════════════════════════════════
📋 تعليمات هامة جداً:
═══════════════════════════════════════
1. استخدم دائماً المعلومات المحددة أعلاه بالإجابة
2. عند السؤال عن منتجات، اذكر الأسعار والتفاصيل المحددة
3. عند السؤال عن خدمات/عروض، استخدم التفاصيل المحددة
4. كن محدداً - لا تعطِ إجابات عامة عندما لديك بيانات حقيقية
5. عندما يبدى العميل اهتمام، اطلب اسمه ورقم هاتفه
6. سجل بيانات العميل كـ: [LEAD_CAPTURE: name="الاسم" contact="الهاتف" intent="التفاصيل"]"""
        },
        'Generic/Other': {
            'en': f"""You are an AI sales and support assistant for {business_name}.

═══════════════════════════════════════
📊 COMPLETE BUSINESS KNOWLEDGE BASE:
═══════════════════════════════════════
{context_data}

═══════════════════════════════════════
📋 CRITICAL INSTRUCTIONS:
═══════════════════════════════════════
1. ALWAYS use EXACT information from the knowledge base above
2. When asked about products/services, quote EXACT prices and details
3. Be specific - don't give generic answers when you have real data
4. When customer shows interest, ask for NAME and PHONE/EMAIL""",
            'ar': f"""أنت مساعد مبيعات ودعم ذكي لـ {business_name}.

═══════════════════════════════════════
📊 قاعدة معلومات العمل الكاملة:
═══════════════════════════════════════
{context_data}

═══════════════════════════════════════
📋 تعليمات هامة جداً:
═══════════════════════════════════════
1. استخدم دائماً المعلومات المحددة أعلاه بالإجابة
2. عند السؤال عن منتجات/خدمات، اذكر الأسعار والتفاصيل المحددة
3. كن محدداً - لا تعطِ إجابات عامة"""
        }
    }
    
    config = industry_configs.get(industry, industry_configs['Generic/Other'])
    return config['en'] + "\n\n" + config['ar']


# ============== AI UTILS ==============

def detect_language(text):
    """Detect if text is primarily Arabic or English"""
    if not text:
        return 'en'
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return 'ar' if arabic_chars > len(text) * 0.3 else 'en'


# ============== GROK API INTEGRATION (xAI) ==============

def get_grok_response(messages, business_id):
    """Call Grok API (xAI) with proper context"""

    api_key = os.environ.get('GROK_API_KEY') or os.environ.get('GROQ_API_KEY')

    if not api_key:
        print("⚠️ No API key found, using mock response")
        return get_mock_response(messages, business_id)

    business = Business.query.get(business_id)
    if not business:
        return "Error: Business not found"

    # Detect user's language
    user_message = ""
    if messages:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
    
    lang = detect_language(user_message)
    
    # Add language instruction
    if lang == 'ar':
        lang_instruction = "\n\n⚠️ IMPORTANT: The user is speaking ARABIC. You MUST respond in Arabic only."
    else:
        lang_instruction = "\n\n⚠️ IMPORTANT: The user is speaking English. You MUST respond in English only."
    
    full_system_prompt = business.system_prompt + lang_instruction

    try:
        # Try Grok API first (xAI)
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1"
        )
        
        full_messages = [{"role": "system", "content": full_system_prompt}]
        full_messages.extend(messages)

        response = client.chat.completions.create(
            model="grok-2-latest",
            messages=full_messages,
            temperature=0.7,
            max_tokens=1500
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"❌ Grok API Error: {e}")
        
        # Fallback: Try Groq API
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            
            full_messages = [{"role": "system", "content": full_system_prompt}]
            full_messages.extend(messages)
            
            response = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=full_messages,
                temperature=0.7
            )
            
            return response.choices[0].message.content
            
        except Exception as e2:
            print(f"❌ Groq API also failed: {e2}")
            return get_mock_response(messages, business_id)


def get_mock_response(messages, business_id):
    """Generate intelligent mock responses using actual business context"""
    
    business = Business.query.get(business_id)
    if not business:
        return "Error: Business not found"
        
    business_name = business.name
    context_data = business.context_data if business.context_data else "Contact us for more information."
    
    user_message = ""
    if messages:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
                
    lang = detect_language(user_message)
    user_msg_lower = user_message.lower()
    
    # Check for lead capture
    name_match = re.search(r'(?:my name is|i\'m|i am|call me|اسمي|أنا)\s+([a-zA-Z\u0600-\u06FF\s]+)', user_message, re.IGNORECASE)
    phone_match = re.search(r'(\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|\b\+?\d{1,3}[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b)', user_message)
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_message)
    
    if name_match and (phone_match or email_match):
        name = name_match.group(1).strip()
        contact = phone_match.group(0) if phone_match else email_match.group(0)
        
        if lang == 'ar':
            response = f"شكراً لك، {name}! ✅ لقد سجلنا بياناتك. سيتواصل معك فريق {business_name} على {contact} قريباً."
        else:
            response = f"Thank you, {name}! ✅ I've captured your information. The {business_name} team will reach out to you at {contact} very soon."
        
        lead = Lead(
            business_id=business_id,
            customer_name=name,
            customer_contact=contact,
            intent=f"Captured during chat: {user_message[:100]}"
        )
        db.session.add(lead)
        db.session.commit()
        return response

    # Bilingual responses with context
    if lang == 'ar':
        if any(word in user_msg_lower for word in ['مرحبا', 'مرحباً', 'اهلا', 'أهلا', 'السلام']):
            return f"مرحباً! 👋 أهلاً بك في {business_name}.\n\n📊 إليك بعض المعلومات عنا:\n{context_data}"
        elif any(word in user_msg_lower for word in ['سعر', 'اسعار', 'أسعار', 'بكم', 'كم']):
            return f"💰 إليك معلومات الأسعار والمنتجات لدينا:\n\n{context_data}"
        elif any(word in user_msg_lower for word in ['منتج', 'منتجات', 'عندكم', 'متوفر']):
            return f"📦 إليك منتجاتنا وخدماتنا:\n\n{context_data}"
        else:
            return f"شكراً لتواصلك مع {business_name}! 🙏\n\n📊 إليك معلومات عنا:\n{context_data}"
    else:
        if any(word in user_msg_lower for word in ['hello', 'hi', 'hey']):
            return f"Hello! 👋 Welcome to {business_name}.\n\n📊 Here's information about us:\n{context_data}"
        elif any(word in user_msg_lower for word in ['price', 'cost', 'how much']):
            return f"💰 Here's our pricing and product information:\n\n{context_data}"
        elif any(word in user_msg_lower for word in ['product', 'products', 'available']):
            return f"📦 Here are our products and services:\n\n{context_data}"
        else:
            return f"Thank you for contacting {business_name}! 🙏\n\n📊 Here's information about us:\n{context_data}"


def extract_and_save_lead(response_text, business_id):
    """Extract lead information from AI response"""
    pattern = r'\[LEAD_CAPTURE:\s*name="([^"]*)"\s*contact="([^"]*)"\s*intent="([^"]*)"\]'
    match = re.search(pattern, response_text)
    
    if match:
        name, contact, intent = match.groups()
        
        existing = Lead.query.filter_by(business_id=business_id, customer_contact=contact).first()
        if not existing:
            lead = Lead(business_id=business_id, customer_name=name, customer_contact=contact, intent=intent)
            db.session.add(lead)
            db.session.commit()
        
        response_text = re.sub(pattern, '', response_text).strip()
    
    return response_text


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
        business_name = data.get('business_name', '').strip()
        industry = data.get('industry', 'Generic/Other')
        context_data = data.get('context_data', '').strip()
        
        if not business_name:
            return render_template('onboarding.html', error="Business name is required")
        
        system_prompt = generate_system_prompt(business_name, industry, context_data)
        
        business = Business(
            name=business_name,
            industry=industry,
            context_data=context_data,
            system_prompt=system_prompt
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
    subscription_success = request.args.get('subscription') == 'success'
    return render_template('dashboard.html', business=business, leads=leads, subscription_success=subscription_success)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    business_id = data.get('business_id')
    messages = data.get('messages', [])
    
    if not business_id or not messages:
        return jsonify({'error': 'Missing required fields'}), 400
    
    business = Business.query.get(business_id)
    if not business or not business.can_access_bot():
        return jsonify({'error': 'Subscription required'}), 403
    
    response = get_grok_response(messages, business_id)
    response = extract_and_save_lead(response, business_id)
    
    return jsonify({'response': response, 'success': True})

@app.route('/api/leads/<int:business_id>')
def get_leads(business_id):
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return jsonify({'leads': [lead.to_dict() for lead in leads], 'count': len(leads)})

@app.route('/api/delete-lead/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    lead = Lead.query.get_or_404(lead_id)
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout_session():
    data = request.get_json()
    business_id = data.get('business_id')
    plan = data.get('plan')
    
    if not STRIPE_SECRET_KEY:
        business = Business.query.get(business_id)
        if business:
            business.subscription_status = plan
            business.update_subscription_limits()
            business.subscription_end = datetime.utcnow() + timedelta(days=30)
            db.session.commit()
            return jsonify({'success': True, 'redirect': f'/dashboard/{business_id}?subscription=success'})
        return jsonify({'error': 'Business not found'}), 404
    
    return jsonify({'url': 'checkout_url'})

@app.route('/api/subscription/<int:business_id>')
def get_subscription(business_id):
    business = Business.query.get_or_404(business_id)
    return jsonify({
        'subscription_status': business.subscription_status,
        'can_access_bot': business.can_access_bot(),
        'agent_limit': business.agent_limit,
        'lead_limit': business.lead_limit
    })

# ============== INITIALIZE DATABASE ==============

with app.app_context():
    db.create_all()
    print("✅ Database initialized successfully!")

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)