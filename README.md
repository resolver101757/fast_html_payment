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
