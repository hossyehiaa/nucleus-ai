# Nucleus AI - B2B AI SaaS Platform
## "When Your Business Thinks for Itself"

### 🚀 Quick Start (Local Development)

1. **Create Virtual Environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. **Install Dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set Up Environment Variables:**
```bash
cp .env.example .env
# Edit .env with your API keys
```

4. **Run the Application:**
```bash
FLASK_DEBUG=true python app.py
```

5. **Open in Browser:**
```
http://localhost:5001
```

---

### 🌐 Deploying to Production

This app is ready to deploy on **Render**, **Railway**, or **Heroku**.

#### Environment Variables (Required)

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Flask session secret (generate with `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `GROK_API_KEY` | Your xAI Grok API key |

#### Optional Environment Variables

| Variable | Description |
|----------|-------------|
| `STRIPE_SECRET_KEY` | Stripe secret key for payments |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `STRIPE_STARTER_PRICE` | Stripe Price ID for Starter plan |
| `STRIPE_PRO_PRICE` | Stripe Price ID for Pro plan |
| `STRIPE_AGENCY_PRICE` | Stripe Price ID for Agency plan |
| `PORT` | Server port (default: 5001) |

#### Deploy on Render
1. Push your code to GitHub
2. Create a new **Web Service** on [Render](https://render.com)
3. Connect your GitHub repository
4. Render will auto-detect the `Procfile` and `runtime.txt`
5. Set environment variables in the Render dashboard
6. Deploy!

---

### 📁 Project Structure

```
nucleus-ai/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Procfile              # Production server config
├── runtime.txt           # Python version pin
├── .env.example          # Environment variable template
├── templates/
│   ├── base.html         # Base template with branding
│   ├── index.html        # Landing page
│   ├── services.html     # Services page
│   ├── pricing.html      # Pricing page
│   ├── onboarding.html   # Onboarding flow
│   └── dashboard.html    # Dashboard with chat & CRM
└── static/
    ├── css/
    ├── js/
    └── images/
```

---

### ⚙️ Configuration

#### Grok API (xAI)
```bash
export GROK_API_KEY="xai-your-key-here"
```

#### Custom Brand Colors
Edit in `templates/base.html`:
```css
:root {
    --primary-color: #3b82f6;      /* Main brand color */
    --secondary-color: #06b6d4;    /* Accent color */
    --accent-color: #10b981;       /* Success/CTA */
}
```

#### Custom Logo
Replace the SVG in `templates/base.html` with your logo URL:
```html
<img src="https://your-logo-url.com/logo.png" alt="Your Brand" class="w-10 h-10">
```

---

### 💰 Pricing Tiers

| Plan | Price (USD) | Features |
|------|-------------|----------|
| Starter | $49/mo | 1 AI Agent, 500 Leads/month |
| Pro | $99/mo | 3 AI Agents, Unlimited Leads |
| Agency | $299/mo | 10 AI Agents, Whitelabeling, API Access |

---

### 🛠️ Services Included

1. **Omnichannel Chatbot** - WhatsApp, Instagram, Messenger
2. **AI Voice Agent** - Inbound & Outbound calls
3. **Automated Proposals** - Instant proposal generation
4. **Lead Generation Machine** - Auto scraping & outreach
5. **AI Content & Video Engine** - Auto content creation
6. **Internal Knowledge Assistant** - Employee support
7. **Hidden Internal Automations** - Workflow automation

---

### 🌐 Languages

- English (EN)
- Arabic (AR) - Full RTL support

---

### 📞 Support

For questions or support, contact us at:
- WhatsApp: +20 XXX XXX XXXX
- Email: support@nucleus-ai.com

---

### 📜 License

© 2025 Nucleus AI. All rights reserved.
