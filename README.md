# Easy Life Tours: Discover Rome's Ancient Wonders

A web application that offers virtual tours of ancient Rome, allowing users to explore iconic landmarks and learn about Roman history through AI-generated images.

## Features

- Generate AI images based on user prompts related to ancient Rome
- Choose tour themes: Emperors, Gladiators, or Citizens
- Live-updating credit balance system
- Stripe integration for purchasing additional credits
- Session-based user experience

## Installation

1. Clone the repository
2. Install the required dependencies:
   ```
   pip install fasthtml replicate stripe python-dotenv
   ```
3. Set up environment variables in a `.env` file:
   - REPLICATE_API_KEY
   - STRIPE_KEY
   - STRIPE_WEBHOOK_SECRET
   - DOMAIN

todo: 
- addtional payments webhooks and related logic

    - payment_intent.succeeded:
    This webhook notifies your server when a payment is successfully captured. Use this to update the database and notify users of the payment success.
    
    - payment_intent.payment_failed:
    If a payment fails, Stripe can trigger this event. Use it to notify the user about the failure and suggest alternative payment methods.
    
    - invoice.payment_succeeded & invoice.payment_failed:
    For subscription-based services, these webhooks are essential to ensure proper invoicing and user notifications for payment issues.
    
    - Webhook Security:
    Ensure that your webhook endpoints validate the signature provided by Stripe. This is important to prevent unauthorized or malformed requests.
    
    - Payment Receipt:
    Consider integrating Stripe’s automatic email receipts, or if custom, trigger an email from your system using checkout.session.completed to send detailed payment information.


# Add helper functions and remove duplcates through out the codebase

def redirect_to_login():
    return RedirectResponse('/', status_code=303)

def redirect_with_message(url, message, delay=5000):
    return Div(
        P(message),
        Script(f"""
            setTimeout(() => {{
                window.location.href = '{url}';
            }}, {delay});
        """)
    )

def get_user(email):
    try:
        return users[email]
    except NotFoundError:
        return None


Add username to top bar 