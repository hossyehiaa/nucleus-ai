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
from sqlalchemy import text
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import openai

db_url = os.environ.get("DATABASE_URL", "sqlite:///nucleus.db")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or "sqlite:///nucleus.db"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    businesses = db.relationship('Business', backref='owner', lazy=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Business(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    industry = db.Column(db.String(50), nullable=False)
    context_data = db.Column(db.Text, nullable=True)
    system_prompt = db.Column(db.Text, nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=True)
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
    return f"""You are a highly professional, human sales representative for {business_name}.
Your goal is to assist the user, answer their questions, and naturally steer the conversation to collect their Name and Phone number.

STRICTLY use this knowledge base to answer questions: 
{context_data}
Never make up prices, products, or information not found in the knowledge base.

Tone and Style:
- Be conversational, empathetic, and speak in a natural Egyptian/Arabic tone (or English if the user speaks English).
- Act like a human, not an AI bot.

WHEN contact info (both Name and Phone number) is provided or gathered successfully, you MUST output this exact format at the very end of your message:
[LEAD: name="user name" phone="user phone"]
"""


def detect_language(text):
    if not text:
        return 'ar'
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return 'ar' if arabic > len(text) * 0.2 else 'en'


def get_ai_response(messages, business_id):
    api_key = os.environ.get('GROQ_API_KEY')
    business = Business.query.get(business_id)
    
    if not business:
        return "خطأ - حاول مرة أخرى"
    
    if not api_key:
        return "SYSTEM ERROR: GROQ_API_KEY is missing from environment variables."
    
    conversation = [{"role": "system", "content": business.system_prompt}]
    conversation.extend(messages[-8:])
    
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation,
            temperature=0.7,
            max_tokens=500
        )
        reply = response.choices[0].message.content
        
        # Check for lead tag
        lead_match = re.search(r'\[LEAD:\s*name="([^"]+)"\s*phone="([^"]+)"\]', reply)
        if lead_match:
            name = lead_match.group(1)
            phone = lead_match.group(2)
            if not Lead.query.filter_by(business_id=business.id, customer_contact=phone).first():
                db.session.add(Lead(business_id=business.id, customer_name=name, customer_contact=phone))
                db.session.commit()
            
            # Remove the tag from final text
            reply = re.sub(r'\[LEAD:\s*name="[^"]+"\s*phone="[^"]+"\]', '', reply).strip()
            
        return reply
    except Exception as e:
        print(f"Groq error: {e}")
        return f"GROQ CONNECTION ERROR: {str(e)}"


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


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error="Email already exists.")
            
        user = User(email=email, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('onboarding'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        return render_template('login.html', error="Invalid email or password.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    businesses = Business.query.order_by(Business.created_at.desc()).all()
    return render_template('admin.html', businesses=businesses)

@app.route('/admin/edit_prompt/<int:business_id>', methods=['POST'])
@login_required
def edit_prompt(business_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    business = Business.query.get_or_404(business_id)
    new_prompt = request.form.get('system_prompt')
    if new_prompt:
        business.system_prompt = new_prompt
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'No prompt provided'}), 400

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
@login_required
def onboarding():
    if request.method == 'POST':
        d = request.form
        b = Business(
            user_id=current_user.id,
            name=d.get('business_name', '').strip(),
            industry=d.get('industry', 'Generic/Other'),
            context_data=d.get('context_data', '').strip(),
            system_prompt=generate_system_prompt(d.get('business_name', ''), d.get('industry'), d.get('context_data', '')),
            api_key=secrets.token_hex(32)
        )
        b.update_subscription_limits()
        db.session.add(b)
        db.session.commit()
        return redirect(url_for('dashboard', business_id=b.id))
    return render_template('onboarding.html')

@app.route('/dashboard/<int:business_id>')
@login_required
def dashboard(business_id):
    b = Business.query.get_or_404(business_id)
    if b.user_id != current_user.id and current_user.role != 'admin':
        return redirect(url_for('index'))
    if not b.api_key:
        b.api_key = secrets.token_hex(32)
        db.session.commit()
    leads = Lead.query.filter_by(business_id=business_id).order_by(Lead.created_at.desc()).all()
    return render_template('dashboard.html', business=b, leads=leads)

@app.route('/api/chat', methods=['POST'])
def chat():
    d = request.get_json()
    b = Business.query.get(d.get('business_id'))
    if not b or not b.can_access_bot():
        return jsonify({'error': 'Subscription required'}), 403
    return jsonify({'response': get_ai_response(d.get('messages', []), d.get('business_id')), 'success': True})

@app.route('/api/v1/chat/external', methods=['POST'])
def external_chat():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401
    
    api_key = auth_header.split(' ')[1]
    business = Business.query.filter_by(api_key=api_key).first()
    
    if not business:
        return jsonify({'error': 'Invalid API Key'}), 401
        
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing message'}), 400
        
    messages = [{"role": "user", "content": data['message']}]
    
    reply = get_ai_response(messages, business.id)
    return jsonify({'reply': reply})

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
    try:
        db.session.execute(text('ALTER TABLE business ADD COLUMN user_id INTEGER REFERENCES "user"(id);'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    try:
        db.session.execute(text('ALTER TABLE business ADD COLUMN api_key VARCHAR(64) UNIQUE;'))
        db.session.commit()
    except Exception:
        db.session.rollback()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)))