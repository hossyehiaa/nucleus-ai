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
    subscription_status = db.Column(db.String(20), default='free')  # free, starter, pro, agency
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
        """Check if business can access the AI bot"""
        return self.subscription_status in ['starter', 'pro', 'agency']
    
    def update_subscription_limits(self):
        """Update limits based on subscription tier"""
        limits = {
            'free': {'agents': 1, 'leads': 10},
            'starter': {'agents': 1, 'leads': 500},
            'pro': {'agents': 3, 'leads': -1},  # -1 = unlimited
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
    """Generate industry-specific system prompt"""
    
    industry_prompts = {
        'E-commerce/Clothing': f"""You are an AI sales representative for {business_name}, a fashion and clothing e-commerce store.

YOUR GOALS:
1. Help customers find the right sizes and styles for their needs
2. Explain return policies, shipping options, and product details
3. Guide customers through the purchasing process
4. COLLECT customer information (Name and Phone Number) when they're ready to place an order or have questions

YOUR PERSONALITY:
- Friendly, stylish, and fashion-forward
- Knowledgeable about trends and fit
- Patient with sizing questions
- Enthusiastic about helping customers look their best

KNOWLEDGE BASE:
{context_data}

LEAD CAPTURE INSTRUCTION:
When a customer shows purchase intent or asks about ordering, politely ask for their:
- Full Name
- Phone Number
When you receive this information, acknowledge it and continue helping. Format lead captures as:
[LEAD_CAPTURE: name="Customer Name" contact="Phone/Email" intent="Purchase interest details"]

Always maintain a helpful, professional tone. If you don't know something specific, offer to help them find the answer.""",

        'Gym/Fitness': f"""You are a fitness sales consultant for {business_name}, a gym and fitness center.

YOUR GOALS:
1. Explain membership options, pricing, and benefits
2. Share information about classes, equipment, and personal training
3. Help potential members understand what makes your gym special
4. COLLECT visitor information (Name and Phone Number) to book facility tours or trials

YOUR PERSONALITY:
- Energetic, motivating, and health-conscious
- Knowledgeable about fitness and wellness
- Encouraging but not pushy
- Passionate about helping people achieve their fitness goals

KNOWLEDGE BASE:
{context_data}

LEAD CAPTURE INSTRUCTION:
When someone shows interest in joining or visiting, ask for:
- Full Name
- Phone Number
When you receive this information, acknowledge it and continue helping. Format lead captures as:
[LEAD_CAPTURE: name="Customer Name" contact="Phone/Email" intent="Membership/trial interest details"]

Always maintain an encouraging, supportive tone. Inspire them to take the first step!""",

        'Marketing Agency': f"""You are an AI business consultant for {business_name}, a marketing agency.

YOUR GOALS:
1. Qualify B2B leads by understanding their business needs
2. Explain your agency's services: digital marketing, SEO, content, ads, branding
3. Demonstrate expertise and build trust with potential clients
4. COLLECT contact information (Name and Phone/Email) to schedule discovery calls

YOUR PERSONALITY:
- Professional, strategic, and results-oriented
- Articulate about marketing trends and ROI
- Consultative approach - ask questions before prescribing solutions
- Confident but approachable

KNOWLEDGE BASE:
{context_data}

LEAD CAPTURE INSTRUCTION:
When a prospect shows genuine interest, offer a free consultation and ask for:
- Full Name
- Phone Number or Email
When you receive this information, acknowledge it and continue helping. Format lead captures as:
[LEAD_CAPTURE: name="Customer Name" contact="Phone/Email" intent="Service interest details"]

Always maintain professional credibility. Ask qualifying questions to understand their needs better.""",

        'Generic/Other': f"""You are an AI sales and support assistant for {business_name}.

YOUR GOALS:
1. Understand customer needs and provide helpful information
2. Explain your products/services clearly and professionally
3. Answer questions and resolve concerns
4. COLLECT customer information (Name and Contact Details) when appropriate

YOUR PERSONALITY:
- Professional, helpful, and attentive
- Knowledgeable about your business
- Patient and thorough
- Solution-oriented

KNOWLEDGE BASE:
{context_data}

LEAD CAPTURE INSTRUCTION:
When a customer shows interest in your services/products, ask for:
- Full Name
- Phone Number or Email
When you receive this information, acknowledge it and continue helping. Format lead captures as:
[LEAD_CAPTURE: name="Customer Name" contact="Phone/Email" intent="Interest details"]

Always maintain a helpful, professional tone. Build trust through genuine assistance."""
    }
    
    return industry_prompts.get(industry, industry_prompts['Generic/Other'])


# ============== GROQ AI INTEGRATION ==============

def get_grok_response(messages, business_id):
    """Call Groq API or fall back to mock response if no API key is set"""

    api_key = os.environ.get('GROQ_API_KEY')

    if not api_key:
        return get_mock_response(messages, business_id)

    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        # Get business system prompt
        business = Business.query.get(business_id)
        if not business:
            return "Error: Business not found"

        # Build full message list: system prompt + conversation history
        full_messages = [{"role": "system", "content": business.system_prompt}]
        full_messages.extend(messages)

        chat_completion = client.chat.completions.create(
            messages=full_messages,
            model="llama3-8b-8192",
            temperature=0.7,
        )

        return chat_completion.choices[0].message.content

    except Exception as e:
        print(f"Groq API Error: {e}")
        return get_mock_response(messages, business_id)


def get_mock_response(messages, business_id):
    """Generate intelligent mock responses for demo purposes"""
    
    business = Business.query.get(business_id)
    business_name = business.name if business else "our business"
    
    # Get the last user message
    user_message = ""
    if messages:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "").lower()
                break
    
    # Check if user is providing contact info
    name_match = re.search(r'(?:my name is|i\'m|i am|call me|this is|it\'s)\s+([a-zA-Z\s]+?)(?:\s+(?:and|my|phone|email|contact)|$)', user_message, re.IGNORECASE)
    # More flexible phone detection
    phone_match = re.search(r'(?:phone|number|cell|mobile|call)[\s:]*([\d\s\-\(\)\+]{10,})', user_message, re.IGNORECASE)
    if not phone_match:
        phone_match = re.search(r'(\b\d{3}[-.]?\d{3}[-.]?\d{4}\b|\b\+?\d{1,3}[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b)', user_message)
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_message)
    
    responses = {
        'greeting': f"Hello! Welcome to {business_name}. I'm your AI assistant, here to help you with any questions about our products and services. How can I assist you today?",
        
        'price': f"I'd be happy to share our pricing information! We offer competitive rates tailored to your needs. Would you like me to provide specific details? Also, I can connect you with our team - just share your name and phone number!",
        
        'service': f"At {business_name}, we offer a range of services designed to meet your needs. Our team is dedicated to providing exceptional quality and customer satisfaction. What specific area are you interested in learning more about?",
        
        'contact': f"I'd love to help you get in touch with our team! Could you please share your name and phone number? I'll make sure they reach out to you promptly.",
        
        'hours': f"We're available to serve you during our regular business hours. For the most up-to-date schedule and availability, feel free to ask! Would you like me to help schedule something for you?",
        
        'default': f"Thank you for reaching out to {business_name}! I'm here to help answer your questions and assist you with anything you need. Could you tell me a bit more about what you're looking for?"
    }
    
    # Check for lead capture FIRST (before other keyword checks)
    if name_match and (phone_match or email_match):
        # User provided contact info
        name = name_match.group(1).strip() if name_match else "Unknown"
        contact = phone_match.group(1).strip() if phone_match else (email_match.group(0) if email_match else "Unknown")
        
        response = f"Thank you, {name}! I've captured your information. Our team will reach out to you at {contact} very soon. Is there anything else I can help you with in the meantime?"
        
        # Simulate lead capture
        lead = Lead(
            business_id=business_id,
            customer_name=name,
            customer_contact=contact,
            intent=f"Captured during chat: {user_message[:100]}"
        )
        db.session.add(lead)
        db.session.commit()
        
    elif any(word in user_message for word in ['hello', 'hi', 'hey', 'good morning', 'good afternoon']):
        response = responses['greeting']
    elif any(word in user_message for word in ['price', 'cost', 'how much', 'pricing', 'rate', 'fee']):
        response = responses['price']
    elif any(word in user_message for word in ['service', 'offer', 'provide', 'do you']):
        response = responses['service']
    elif any(word in user_message for word in ['contact', 'reach', 'call', 'speak', 'talk']):
        response = responses['contact']
    elif any(word in user_message for word in ['hour', 'open', 'close', 'when', 'time']):
        response = responses['hours']
    else:
        response = responses['default']
    
    return response


def extract_and_save_lead(response_text, business_id):
    """Extract lead information from AI response and save to database"""
    
    # Look for lead capture pattern
    pattern = r'\[LEAD_CAPTURE:\s*name="([^"]*)"\s*contact="([^"]*)"\s*intent="([^"]*)"\]'
    match = re.search(pattern, response_text)
    
    if match:
        name = match.group(1)
        contact = match.group(2)
        intent = match.group(3)
        
        # Check if lead already exists
        existing = Lead.query.filter_by(
            business_id=business_id,
            customer_contact=contact
        ).first()
        
        if not existing:
            lead = Lead(
                business_id=business_id,
                customer_name=name,
                customer_contact=contact,
                intent=intent
            )
            db.session.add(lead)
            db.session.commit()
        
        # Remove the lead capture tag from response
        response_text = re.sub(pattern, '', response_text).strip()
    
    return response_text


# ============== STRIPE INTEGRATION ==============

def init_stripe():
    """Initialize Stripe with API key"""
    if STRIPE_SECRET_KEY:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        return stripe
    return None


def create_stripe_checkout_session(business_id, plan, email=None):
    """Create a Stripe checkout session for subscription"""
    stripe = init_stripe()
    
    if not stripe:
        return None, "Stripe not configured"
    
    business = Business.query.get(business_id)
    if not business:
        return None, "Business not found"
    
    try:
        # Create or get customer
        if business.stripe_customer_id:
            customer_id = business.stripe_customer_id
        else:
            customer = stripe.Customer.create(
                email=email or f"business_{business_id}@nucleus-ai.com",
                metadata={'business_id': business_id}
            )
            customer_id = customer.id
            business.stripe_customer_id = customer_id
            db.session.commit()
        
        # Get price ID for plan
        price_id = STRIPE_PRICES.get(plan)
        if not price_id or price_id.startswith('price_'):
            # Demo mode - use placeholder
            return None, "Stripe prices not configured. Please set environment variables."
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{request.host_url}dashboard/{business_id}?subscription=success",
            cancel_url=f"{request.host_url}pricing?canceled=true",
            metadata={'business_id': business_id, 'plan': plan}
        )
        
        return checkout_session.url, None
        
    except Exception as e:
        return None, str(e)


def handle_stripe_webhook(payload, sig_header):
    """Handle Stripe webhook events"""
    stripe = init_stripe()
    
    if not stripe:
        return False, "Stripe not configured"
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        return False, str(e)
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        business_id = session.get('metadata', {}).get('business_id')
        plan = session.get('metadata', {}).get('plan')
        
        if business_id and plan:
            business = Business.query.get(business_id)
            if business:
                business.subscription_status = plan
                business.subscription_id = session.get('subscription')
                business.update_subscription_limits()
                
                # Set subscription end date (1 month from now)
                business.subscription_end = datetime.utcnow() + timedelta(days=30)
                db.session.commit()
                
        return True, "Subscription updated"
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        customer_id = subscription.get('customer')
        
        business = Business.query.filter_by(stripe_customer_id=customer_id).first()
        if business:
            business.subscription_status = 'free'
            business.subscription_id = None
            business.update_subscription_limits()
            db.session.commit()
        
        return True, "Subscription cancelled"
    
    return True, "Event processed"


# ============== ROUTES ==============

@app.route('/')
def index():
    """Landing page"""
    return render_template('index.html')


@app.route('/services')
def services():
    """Services page showcasing all automation services"""
    return render_template('services.html')


@app.route('/pricing')
def pricing():
    """Picing page with subscription tiers"""
    return render_template('pricing.html')


@app.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    """Onboarding flow for new businesses"""
    if request.method == 'POST':
        data = request.form
        
        business_name = data.get('business_name', '').strip()
        industry = data.get('industry', 'Generic/Other')
        context_data = data.get('context_data', '').strip()
        
        if not business_name:
            return render_template('onboarding.html', error="Business name is required")
        
        # Generate system prompt
        system_prompt = generate_system_prompt(business_name, industry, context_data)
        
        # Create business
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
    """Main dashboard with bot tester and CRM"""
    business = Business.query.get_or_404(business_id)
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    
    # Check for subscription success message
    subscription_success = request.args.get('subscription') == 'success'
    
    return render_template('dashboard.html', 
                         business=business, 
                         leads=leads,
                         subscription_success=subscription_success)


@app.route('/api/chat', methods=['POST'])
def chat():
    """Chat API endpoint"""
    data = request.get_json()
    
    business_id = data.get('business_id')
    messages = data.get('messages', [])
    
    if not business_id:
        return jsonify({'error': 'Business ID is required'}), 400
    
    if not messages:
        return jsonify({'error': 'Messages are required'}), 400
    
    # Check subscription status
    business = Business.query.get(business_id)
    if not business or not business.can_access_bot():
        return jsonify({
            'error': 'Subscription required',
            'message': 'Please upgrade to access the AI Bot. Visit /pricing to subscribe.',
            'requires_subscription': True
        }), 403
    
    # Get AI response from Grok
    response = get_grok_response(messages, business_id)
    
    # Extract and save lead if present
    response = extract_and_save_lead(response, business_id)
    
    return jsonify({
        'response': response,
        'success': True
    })


@app.route('/api/leads/<int:business_id>')
def get_leads(business_id):
    """Get all leads for a business"""
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return jsonify({
        'leads': [lead.to_dict() for lead in leads],
        'count': len(leads)
    })


@app.route('/api/delete-lead/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    """Delete a lead"""
    lead = Lead.query.get_or_404(lead_id)
    business_id = lead.business_id
    db.session.delete(lead)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Lead deleted'})


# ============== STRIPE ROUTES ==============

@app.route('/api/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session"""
    data = request.get_json()
    business_id = data.get('business_id')
    plan = data.get('plan')  # starter, pro, agency
    email = data.get('email')
    
    if not business_id or not plan:
        return jsonify({'error': 'Missing required fields'}), 400
    
    if plan not in STRIPE_PRICES:
        return jsonify({'error': 'Invalid plan'}), 400
    
    # For demo mode without Stripe keys, simulate subscription
    if not STRIPE_SECRET_KEY or STRIPE_PRICES[plan].startswith('price_'):
        # Demo mode - update subscription directly
        business = Business.query.get(business_id)
        if business:
            business.subscription_status = plan
            business.update_subscription_limits()
            business.subscription_end = datetime.utcnow() + timedelta(days=30)
            db.session.commit()
            return jsonify({
                'success': True,
                'demo_mode': True,
                'message': f'Subscribed to {plan} plan (demo mode)',
                'redirect': f'/dashboard/{business_id}?subscription=success'
            })
        return jsonify({'error': 'Business not found'}), 404
    
    checkout_url, error = create_stripe_checkout_session(business_id, plan, email)
    
    if error:
        return jsonify({'error': error}), 400
    
    return jsonify({'url': checkout_url})


@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhooks"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    
    success, message = handle_stripe_webhook(payload, sig_header)
    
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 400


@app.route('/api/subscription/<int:business_id>')
def get_subscription(business_id):
    """Get subscription status for a business"""
    business = Business.query.get_or_404(business_id)
    return jsonify({
        'subscription_status': business.subscription_status,
        'can_access_bot': business.can_access_bot(),
        'agent_limit': business.agent_limit,
        'lead_limit': business.lead_limit,
        'subscription_end': business.subscription_end.isoformat() if business.subscription_end else None
    })


# ============== INITIALIZE DATABASE ==============

def init_db():
    """Initialize the database with tables"""
    with app.app_context():
        db.create_all()
        print("Database initialized successfully!")


if __name__ == '__main__':
    init_db()
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)
