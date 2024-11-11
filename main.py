"""
SafeFast virtual tours: Discover Rome's Ancient Wonders

This webapp is designed to provide virtual tours of ancient Rome using AI-generated images.
Users can generate images of Roman emperors, gladiators, and citizens, allowing them to
explore and visualize different aspects of ancient Roman life. The app includes user
authentication, a credit system for image generation, and integrates with Stripe for payments.
It aims to bring the fascinating world of ancient Rome to life through technology, offering
an immersive and educational experience.
"""

# Import necessary libraries and modules
from fastcore.parallel import threaded
from fasthtml.common import *
import uuid, os, uvicorn, requests, replicate, stripe
from PIL import Image
from starlette.responses import RedirectResponse
import os
from dotenv import load_dotenv 
import random
import secrets
from datetime import datetime, timedelta
import resend

# Flag to switch between development and production modes
dev_mode = False

print(os.environ)


if dev_mode == True:
    print("\033[1;31mRunning in development mode\033[0m")
else:
    print("Running in production mode")

# Load environment variables from .env file if running locally
# Check if the computer name is A88402735 or DESKTOP-23CHMFJ
if os.getenv("NAME") == "A88402735" or os.getenv("NAME") == "DESKTOP-23CHMFJ":  
    load_dotenv(".env_test")

# Set up Replicate client for image generation
replicate_api_token = os.environ['REPLICATE_API_KEY']
client = replicate.Client(api_token=replicate_api_token)

# Set up Stripe for payment processing
stripe.api_key = os.environ["STRIPE_KEY"]
webhook_secret = os.environ['STRIPE_WEBHOOK_SECRET']
DOMAIN = os.environ['DOMAIN']

# Set up Resend for email sending
resend_api_key = os.environ.get('RESEND_API_KEY')

if resend_api_key:
    resend.api_key = resend_api_key
else:
    print("Warning: RESEND_API_KEY not set. Email functionality may not work.")

# Remove trailing slash from DOMAIN if present
if DOMAIN.endswith('/'):
    DOMAIN = DOMAIN[:-1]

# Set up database for storing generated image details
tables = database('data/gens.db').t
gens = tables.gens
if not gens in tables:
    gens.create(prompt=str, session_id=str, id=int, folder=str, pk='id')
Generation = gens.dataclass()

# Set up database for storing user details
SQL_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY NOT NULL,
    magic_link_token TEXT,
    magic_link_expiry TIMESTAMP,
    is_active BOOLEAN DEFAULT FALSE,
    balance INTEGER DEFAULT 0  -- Balance field for user credits
);
"""

if not 'users' in tables:
    db = database('data/gens.db')
    db.execute(SQL_CREATE_USERS)   

users = tables.users
User = users.dataclass()

# Define CDN links for Tailwind CSS, DaisyUI, and FrankenUI
tailwind_cdn = Link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css")
daisyui_cdn = Link(rel="stylesheet", href="https://cdn.jsdelivr.net/npm/daisyui@latest/dist/full.css")
frankenui = Link(rel='stylesheet', href='https://unpkg.com/franken-wc@0.1.0/dist/css/zinc.min.css')

# Define login redirect response
login_redir = RedirectResponse('/', status_code=303)

# Authentication middleware
def before(req, session):
   auth = req.scope['auth'] = session.get('auth', None)
   if not auth: return login_redir
   
bware = Beforeware(before, skip=[r'/favicon\.ico', r'/static/.*', r'.*\.css', '/login', '/send_magic_link', r'/verify_magic_link/.*', '/' , '/about', '/media/.*', '/generate_images'])

# Initialize FastHTML app with Tailwind, DaisyUI, and authentication middleware
if dev_mode == True:
    app = FastHTMLWithLiveReload(hdrs=(tailwind_cdn, daisyui_cdn, frankenui))
else:
    app = FastHTMLWithLiveReload(hdrs=(tailwind_cdn, daisyui_cdn, frankenui),before=bware)

# Add inline CSS for hover zoom effect
hover_style = Style("""
    .hover-zoom {
        transition: transform 0.2s; /* Animation */
    }
    .hover-zoom:hover {
        transform: scale(1.5); /* (150% zoom) */
    }
""")

# Check if the user is logged in
def is_user_logged_in(session):
    is_logged_in = 'auth' in session and session['auth'] is not None
    return is_logged_in

# Define the common navigation bar for the app
def navigation_bar(session):
    is_logged_in = is_user_logged_in(session)
    common_links = [
        Li(A('Home', href='/', cls='btn btn-ghost btn-sm rounded-btn')),
        Li(A('About', href='/about', cls='btn btn-ghost btn-sm rounded-btn')),
    ]

    if is_logged_in:
        user_email = session['auth']
        try:
            user = users[user_email]
            user_links = [
                Li(A('Generate Images', href='/generate_images', cls='btn btn-ghost btn-sm rounded-btn')),
                Li(A('Buy Credits', href='/buy_credits', cls='btn btn-ghost btn-sm rounded-btn')),
                Li(A('Logout', href='/logout', cls='btn btn-ghost btn-sm rounded-btn')),
            ]
            balance_display = Span(f'Balance: {user.balance} credits', 
                                   cls='ml-4 text-sm', 
                                   id="credit-balance",
                                   hx_get="/get_updated_balance",
                                   hx_trigger="balanceUpdated from:body")
        except NotFoundError:
            user_links = [
                Li(A('Login', href='/login', cls='btn btn-ghost btn-sm rounded-btn')),
            ]
            balance_display = None
    else:
        user_links = [
            Li(A('Login', href='/login', cls='btn btn-ghost btn-sm rounded-btn')),
        ]
        balance_display = None

    return Nav(
        Div(
            Span('SafeFast virtual tours', cls='text-xl font-bold'),
            balance_display if balance_display else None,
            cls='flex-1 flex items-center'
        ),
        Div(
            Ul(
                *(common_links + user_links),
                cls='menu menu-horizontal p-0'
            ),
            cls='flex-none'
        ),
        cls='navbar bg-blue-500 text-white flex justify-between items-center'
    )

# Helper function to create a login form
def MyLoginForm(btn_text: str, target: str, cls: str = ""):
   # Returns a form with email input and submit button
   return Form(
       Div(
           Div(
               Input(id='email', type='email', placeholder='foo@bar.com', cls='uk-input'),
               cls='uk-form-controls'
           ),
           cls='uk-margin'
       ),
       Button(btn_text, type="submit", cls="uk-button uk-button-primary w-full", id="submit-btn"),
       P(id="error", cls="uk-text-danger uk-text-small uk-text-italic uk-margin-top"),
       hx_post=target,
       hx_target="#error",
       hx_disabled_elt="#submit-btn",
       cls=f'uk-form-stacked {cls}'
   )

# Helper function to send magic link email
def send_magic_link_email(email: str, magic_link: str):
    r = resend.Emails.send({
        "from": "noreply@alexkelly.world",
        "to": f"{email}",
        "subject": "Sign in to The App",
        "html": f"""<p>Hey there,

        Click this link to sign in to The App: <a href="{magic_link}">Sign In Link</a>

        If you didn't request this, just ignore this email.
        </p>"""
    })


# Show the image (if available) and prompt for a generation
def generation_preview(g, session):
    # Ensure the session ID matches
    if g.session_id != session['session_id']: return "Wrong session ID!"
    
    # Construct the image path
    image_path = f"{g.folder}/{g.id}.png"
    
    # If the image exists, return a preview card
    if os.path.exists(image_path):
        return Div(
            Div(
                A(
                    Img(src=image_path, alt="Card image", cls="hover-zoom rounded-lg w-full h-auto"),
                    href=image_path,
                    target="_blank",
                    cls="block"
                ),
                Div(
                    P(B("Prompt: "), g.prompt, cls="text-sm"),
                    cls="p-4"
                ),
                cls="card shadow-lg compact bg-base-100"
            ),
            id=f'gen-{g.id}',
            cls="w-full p-4"
        )
    
    # If the image is still generating, return a placeholder
    return Div(
        f"Generating with prompt '{g.prompt}'...",
        id=f'gen-{g.id}',
        hx_get=f"/gens/{g.id}",
        hx_trigger="every 2s",
        hx_swap="outerHTML",
        cls="w-full p-4"
    )

# Generate an image and save it to the folder (in a separate thread)
@threaded
def generate_and_save(prompt, id, folder):
    # Call the Replicate API to generate the image
    output = client.run(
        "resolver101757/akflux:a8a38acebd2b927ea95ab68a2e20626c81b135196116dbff8db298baf1da1fd0",
        input={
            "width": 1024,
            "height": 1024,
            "model": "dev",
            "prompt": prompt,
            "lora_scale": 1.34,
            "num_outputs": 1,
            "aspect_ratio": "1:1",
            "output_format": "webp",
            "guidance_scale": 6.09,
            "output_quality": 90,
            "prompt_strength": 0.8,
            "extra_lora_scale": 1,
            "num_inference_steps": 28
        }
    )
    print(output)
    # Save the generated image
    Image.open(requests.get(output[0], stream=True).raw).save(f"{folder}/{id}.png")
    return True

# Main route handler
@app.get("/")
def page_home(session):
    # Generate a new session ID if not present
    if 'session_id' not in session: session['session_id'] = str(uuid.uuid4())
    is_logged_in = is_user_logged_in(session)
    
    # Return the main page layout
    return (
        Title('SafeFast virtual tours: Discover Romes Ancient Wonders'),
        navigation_bar(session),
        Main(
            # Hero Section
            Section(
                Div(
                    H1('Discover Romes Ancient Wonders!', cls='text-5xl font-bold text-white'),
                    P('Explore the wonders of ancient Rome with our expertly guided virtual tours!', cls='py-6 text-white'),
                    cls='text-center bg-cover bg-center min-h-screen flex flex-col justify-center items-center',
                    style="background-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.3), rgba(0, 0, 0, 0.7)), url('media/background_tour_guide.webp'); height: 100vh; width: 100vw;"
                ),
                cls='hero'
            ),
            cls='container'
        )
    )
    
# Logout route
@app.get("/logout")
def page_logout(session):
    # Clear the session to log the user out
    session.clear()
    return Titled("Logged Out", 
        Div(
            cls="content",
            style="background-image: url('media/logout.webp'); background-size: cover; height: 100vh; color: white; position: relative;",
            children=[
                Div(
                    cls="text-center bg-black bg-opacity-50 rounded p-2",
                    style="position: absolute; top: 20px; left: 50%; transform: translateX(-50%);",
                    children=[
                        "You have been logged out successfully.",
                        "Redirecting to home page in 5 seconds..."
                    ]
                ),
            ]
        ),
        Script("""
            setTimeout(() => {
                window.location.href = '/';
            }, 5000);
        """)
    ), RedirectResponse(url="/", status_code=303)


# Login page route
@app.get("/login")
def page_login(session ):
    is_logged_in = is_user_logged_in(session)
    # Returns the login page with a form to enter email
    return Div(
       navigation_bar(session),
       Div(
           H1("Sign In", cls="text-3xl font-bold tracking-tight uk-margin text-center"),
           P("Enter your email to sign in to The App.", cls="uk-text-muted uk-text-small text-center"),
           MyLoginForm("Sign In with Email", "/send_magic_link", cls="uk-margin-top"),
           cls="uk-card uk-card-body"
       ),
       cls='w-full'
   )

# About page route
@app.get("/about")
def page_about(session):
    # Returns the about page with navigation, content, and footer
    return Title('Easy Life Tours: Discover Romes Ancient Wonders', cls='blue'), Main(
        navigation_bar(session),
        Div(
            # About page content
            Div(
                P("Welcome to Easy Life Tours! Our aim is to bring the fascinating world of ancient Rome to life through the power of technology. "
                  "With our innovative website, you can generate images of famous Roman people and immerse yourself in their stories. "
                  "Join us on this exciting journey and let's explore the wonders of ancient Rome together!"),
                cls="bg-black bg-opacity-50 p-6 rounded-lg text-white max-w-2xl mx-auto"
            ),
            cls='text-center bg-cover bg-center min-h-screen flex flex-col justify-center items-center',
            style="background-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.3), rgba(0, 0, 0, 0.7)), url('media/background_about.webp'); height: 100vh; width: 100vw;"

        ),
        cls='w-full'
    ), hover_style, Footer(
        Div(
            P("© 2023 Easy Life Tours. All rights reserved."),
            cls='footer-content'
        ),
        cls='footer bg-black bg-opacity-50 text-white'
    )   


# Route to get updated balance
@app.get("/get_updated_balance")
def get_updated_balance(session):
    if not is_user_logged_in(session):
        return "Not logged in"
    
    user_email = session['auth']
    try:
        user = users[user_email]
        return f"Balance: {user.balance} credits"
    except NotFoundError:
        return "User not found"
    
    
# Route to handle magic link sending
@app.post("/send_magic_link")
def page_send_magic_link(email: str):
   if not email:
       return "Email is required"
  
   try:
       user = users[email]
   except NotFoundError:
       # Create a new user if not found
       user = User(email=email, is_active=False, magic_link_token=None, magic_link_expiry=None, balance=0)
       users.insert(user)
  
   # Generate a new magic link token and set expiry
   magic_link_token = secrets.token_urlsafe(32)
   magic_link_expiry = datetime.now() + timedelta(minutes=15)
   
   # Update user with new magic link details
   users.update({'email': email, 'magic_link_token': magic_link_token, 'magic_link_expiry': magic_link_expiry})
   
   # TODO: Ensure this works correctly in production, change to {DOMAIN}
   magic_link = f"{DOMAIN}/verify_magic_link/{magic_link_token}"
  
   # Send the magic link email
   send_magic_link_email(email, magic_link)
  
   # Return success message and update UI
   return P("A link to sign in has been sent to your email. Please check your inbox. The link will expire in 15 minutes.", id="success", cls="uk-margin-top uk-text-muted uk-text-small"), HttpHeader('HX-Reswap', 'outerHTML'), Button("Magic link sent", type="submit", cls="uk-button uk-button-primary w-full", id="submit-btn", disabled=True, hx_swap_oob="true")

# Route to verify magic link
@app.get("/verify_magic_link/{token}")
def page_verify_magic_link(session, token: str):
   now = datetime.now()
   try:
       # Find user with valid magic link token
       user = users(where=f"magic_link_token = '{token}' AND magic_link_expiry > '{now}'")[0]
       session['auth'] = user.email
       # Update user as active and clear magic link details
       users.update({'email': user.email, 'magic_link_token': None, 'magic_link_expiry': None, 'is_active': True})
       return RedirectResponse('/')
   except IndexError:
       return Div(
            P("Invalid or expired magic link."),
            cls="error-message"
        )

# Logout route
@app.get("/generate_images")
def page_generate_images(session):
    # checks if user is logged in
    if not is_user_logged_in(session):
        return login_redir

    # checks user is in the database
    user_email = session['auth']
    try:
        user = users[user_email]
    except NotFoundError:
        return "User not found"

    # checks if user has enough credits
    if user.balance < 1:
        return Title('Insufficient Credits'), Main(
            navigation_bar(session),
            Div(
                Div(
                    H1("Insufficient Credits", cls="text-4xl font-bold mb-4 text-white"),
                    P("Oops! It looks like your coin purse is empty.", cls="mb-6 text-lg text-white"),
                    P("Purchase more credits to continue your Roman adventure!", cls="mb-6 text-lg text-white"),
                    A("Buy Credits", href="/buy_credits", cls="btn btn-primary"),
                    cls="text-center z-10 relative"
                ),
                cls="flex flex-col items-center justify-center min-h-screen bg-cover bg-center",
                style="background-image: linear-gradient(rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0.6)), url('media/generate_images_empty_coin_purses.webp');"
            ),
            Script("""
                setTimeout(() => {
                    window.location.href = '/buy_credits';
                }, 5000);
            """)
        )

    # Create form for generating images
    add = Form(
        Div(
            Label("Select Tour Type:", for_="tour_type", cls="block mb-2 text-white"),
            Select(
                Option("Emperors", value="emperors"),
                Option("Gladiators", value="gladiators"),
                Option("Citizens", value="citizens"),
                id="tour_type",
                name="tour_type",
                cls='select select-bordered w-full max-w-xs mb-4 bg-white bg-opacity-80',
            ),
            Button("Generate Image", cls="btn btn-primary w-full"),
            cls='w-full max-w-sm bg-black bg-opacity-50 p-6 rounded-lg'
        ),
        hx_post="/generate_images",
        target_id='gen-list',
        hx_swap="afterbegin",
        cls='form-control'
    )

    # Generate list of image previews
    gen_containers = [generation_preview(g, session) for g in gens(limit=10, where=f"session_id == '{session['session_id']}'")]
    gen_list = Div(*gen_containers[::-1], id='gen-list', cls="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-8") 

    # returns the page with the form and the list of image previews
    return Title('Generate Roman Images'), Main(
        navigation_bar(session),
        Div(
            Div(
                H1("Generate Roman Images", cls="text-4xl font-bold mb-4 text-white"),
                P("Create stunning images of ancient Rome with AI!", cls="mb-6 text-lg text-white"),
                add,
                Div(id="generation-status", cls="mt-4 text-white"),
                gen_list,
                cls="text-center w-full max-w-6xl"
            ),
            cls="flex flex-col items-center justify-start min-h-screen bg-cover bg-center p-8",
            style="background-image: linear-gradient(rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0.6)), url('media/generate_images_roman_collesseum.webp');"
        )
    ), hover_style

# A pending preview keeps polling this route until we return the image preview
@app.get("/gens/{id}")
def page_preview(id:int, session):
    try:
        gen = gens.get(id)
        return generation_preview(gen, session)
    except NotFoundError:
        return "Generation not found."

# Serve static files (images, CSS, etc.)
@app.get("/{fname:path}.{ext:static}")
def page_static(fname:str, ext:str): return FileResponse(f'{fname}.{ext}')



@app.get("/generate_images")
def page_generate_images(session):
    if not is_user_logged_in(session):
        return login_redir

    user_email = session['auth']
    try:
        user = users[user_email]
    except NotFoundError:
        return "User not found"

    if user.balance < 1:
        return Title('Insufficient Credits'), Main(
            navigation_bar(session),
            Div(
                Div(
                    H1("Insufficient Credits", cls="text-4xl font-bold mb-4 text-white"),
                    P("Oops! It looks like your coin purse is empty.", cls="mb-6 text-lg text-white"),
                    P("Purchase more credits to continue your Roman adventure!", cls="mb-6 text-lg text-white"),
                    A("Buy Credits", href="/buy_credits", cls="btn btn-primary"),
                    cls="text-center z-10 relative"
                ),
                cls="flex flex-col items-center justify-center min-h-screen bg-cover bg-center",
                style="background-image: linear-gradient(rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0.6)), url('media/generate_images_empty_coin_purses.webp');"
            ),
            Script("""
                setTimeout(() => {
                    window.location.href = '/buy_credits';
                }, 5000);
            """)
        )

    # Create form for generating images
    add = Form(
        Div(
            Label("Select Tour Type:", for_="tour_type", cls="block mb-2 text-white"),
            Select(
                Option("Emperors", value="emperors"),
                Option("Gladiators", value="gladiators"),
                Option("Citizens", value="citizens"),
                id="tour_type",
                name="tour_type",
                cls='select select-bordered w-full max-w-xs mb-4 bg-white bg-opacity-80',
            ),
            Button("Generate Image", cls="btn btn-primary w-full"),
            cls='w-full max-w-sm bg-black bg-opacity-50 p-6 rounded-lg'
        ),
        hx_post="/generate_images",
        target_id='gen-list',
        hx_swap="afterbegin",
        cls='form-control'
    )

    # Generate list of image previews
    gen_containers = [generation_preview(g, session) for g in gens(limit=10, where=f"session_id == '{session['session_id']}'")]
    gen_list = Div(*gen_containers[::-1], id='gen-list', cls="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-8") 

    return Title('Generate Roman Images'), Main(
        navigation_bar(session),
        Div(
            Div(
                H1("Generate Roman Images", cls="text-4xl font-bold mb-4 text-white"),
                P("Create stunning images of ancient Rome with AI!", cls="mb-6 text-lg text-white"),
                add,
                Div(id="generation-status", cls="mt-4 text-white"),
                gen_list,
                cls="text-center w-full max-w-6xl"
            ),
            cls="flex flex-col items-center justify-start min-h-screen bg-cover bg-center p-8",
            style="background-image: linear-gradient(rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0.6)), url('media/generate_images_roman_collesseum.webp');"
        )
    ), hover_style


# Stripe route to buy credits
@app.get("/buy_credits")
def page_buy_credits(session):
    print("page_buy_credits GET called")  # Debug statement

    return Title('Buy Credits'), Main(
        navigation_bar(session),
        Div(
            Div(
                H1("Purchase Credits", cls="text-4xl font-bold mb-4 text-white"),
                P("Enhance your Roman adventure with more credits!", cls="mb-6 text-lg text-white"),
                Form(
                    Label("Select Credit Amount:", for_="credit_amount", cls="block mb-2 text-white"),
                    Select(
                        Option("1 Credit - $1", value="1"),
                        Option("2 Credits - $2", value="2"),
                        Option("3 Credits - $3", value="3"),
                        Option("4 Credits - $4", value="4"),
                        Option("5 Credits - $5", value="5"),
                        id="credit_amount",
                        name="credit_amount",
                        cls="select select-bordered w-full max-w-xs mb-4 bg-white bg-opacity-80",
                    ),
                    Button("Buy Credits", type="submit", cls="btn btn-primary w-full", 
                           hx_post="/buy_credits",
                           hx_target="#payment-status",
                           hx_swap="innerHTML"),
                    cls="w-full max-w-sm bg-black bg-opacity-50 p-6 rounded-lg"
                ),
                Div(id="payment-status", cls="mt-4 text-white"),
                cls="text-center"
            ),
            cls="flex flex-col items-center justify-center min-h-screen bg-cover bg-center",
            style="background-image: linear-gradient(rgba(0, 0, 0, 0.5), rgba(0, 0, 0, 0.5)), url('/media/buy_credits_coins.webp');"
        )
    )
    
    
@app.post("/buy_credits")
def page_buy_credits_post(credit_amount: int, session):
    print("page_buy_credits POST called")  # Debug statement

    if not is_user_logged_in(session):
        print("User not logged in")  # Debug statement
        return login_redir

    user_email = session['auth']
    print(f"Processing purchase for user: {user_email}")  # Debug statement

    try:
        user = users[user_email]
    except NotFoundError:
        print(f"User {user_email} not found in database")  # Debug statement
        return "User not found."

    # Validate credit_amount
    if credit_amount < 1 or credit_amount > 5:
        print(f"Invalid credit_amount: {credit_amount}")  # Debug statement
        return Div("Invalid credit amount selected.", cls="text-red-500")

    # Create Stripe Checkout Session with variable amount
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': credit_amount * 100,  # Convert dollars to cents
                    'product_data': {
                        'name': f'Buy {credit_amount} Credit{"s" if credit_amount > 1 else ""} for ${credit_amount}',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{DOMAIN}/cancel",
            metadata={
                'user_email': user_email,
                'credit_amount': credit_amount  # Pass the selected credit amount
            }
        )
    except Exception as e:
        print(f"Stripe Checkout Session creation error: {str(e)}")  # Debug statement
        return Div(f"Error creating Stripe session: {str(e)}", cls="text-red-500")

    # Return a redirect response that HTMX can handle
    print("Stripe Checkout Session created successfully")  # Debug statement
    return Div(
        Script(f"window.location.href = '{checkout_session.url}';"),
        "Redirecting to Stripe Checkout..."
    )
    

# Generation route
@app.post("/generate_images")
def page_generate_images(tour_type: str, session):
    if 'auth' not in session: 
        return "User not authenticated"

    user_email = session['auth']
    try:
        user = users[user_email]
    except NotFoundError:
        return "User not found"
    
    if user.balance < 1:
        return Div(
            P("Insufficient balance! Please purchase more credits."),
            Script("""
                setTimeout(() => {
                    window.location.href = '/buy_credits';
                }, 5000);
            """)
        )
    else:
        # Deduct 1 credit from the user's balance
        new_balance = user.balance - 1
        users.update({'email': user_email, 'balance': new_balance})
        print(f"Debug: New balance for {user_email} is {new_balance}")

    # Predefined prompts for different tour types
    prompts = {
        "Julius Caesar at the Roman Forum": "Emperor Julius Caesar giving a speech at the Roman Forum, addressing a crowd of Roman citizens with grand Roman architecture in the background.",
        "Gladiators in the Colosseum": "Gladiators preparing for battle inside the Colosseum, with their armor gleaming, the arena packed with spectators cheering them on.",
        "A Roman Feast": "A lavish Roman feast with nobles and emperors dining in an extravagant hall, surrounded by luxurious food, wine, and ornate decorations.",
        "Architects Designing the Pantheon": "Roman architects working on detailed blueprints of the Pantheon under the guidance of Emperor Hadrian, surrounded by construction materials and models.",
        "Roman Soldiers Marching": "Roman soldiers in full armor marching through a grand triumphal arch, celebrating a victorious return from battle with flags and banners waving.",
        "Empress Livia in Palace Gardens": "Empress Livia, wife of Augustus, walking gracefully through the beautifully manicured palace gardens, with vibrant flowers and elegant statues surrounding her."
    }

    # Select prompt based on tour_type
    prompt = prompts.get(tour_type, random.choice(list(prompts.values())))
    
    # Add a specific detail to the prompt
    prompt = prompt + " Some of the people, statues, or objects in the scene should look like TOK"

    # Generate and save the image
    folder = f"data/gens/{str(uuid.uuid4())}"
    os.makedirs(folder, exist_ok=True)
    g = gens.insert(
        Generation(prompt=prompt,
                   folder=folder,
                   session_id=session['session_id'])
    )
    generate_and_save(g.prompt, g.id, g.folder)

    return Div(
        generation_preview(g, session),
        Script("htmx.trigger(document.body, 'balanceUpdated');")
    )

# Stripe route for payment cancellation
@app.get("/cancel")
def page_cancel():
    return Titled(
        "Payment Cancelled, you will be redirected to the home page in 5 seconds...",
        Div(
            cls="content",
            style="background-image: url('media/cancelled.webp'); background-size: cover; height: 100vh; color: white; position: relative;",
            children=[
                Div(
                    cls="text-center bg-black bg-opacity-50 rounded p-2",
                    style="position: absolute; top: 20px; left: 50%; transform: translateX(-50%);",
                    children=[
                        "Payment Cancelled, you will be redirected to the home page in 5 seconds..."
                    ]
                ),
            ]
        ),
        Script("""
            setTimeout(() => {
                window.location.href = '/';
            }, 5000);
        """)
    )

# Stripe route for successful payment
@app.get("/success")
def page_success(session):
    return Titled("Payment Successful", 
        Div(
            cls="content",
            style="background-image: url('media/success.webp'); background-size: cover; height: 100vh; color: white; position: relative;",
            children=[
                Div(
                    cls="text-center bg-black bg-opacity-50 rounded p-2",
                    style="position: absolute; top: 20px; left: 50%; transform: translateX(-50%);",
                    children=[
                        "Your payment was successful.",
                        "Redirecting to home page in 5 seconds..."
                    ]
                ),
            ]
        ),
        Script("""
            setTimeout(() => {
                // Trigger HTMX to fetch the updated balance
                htmx.trigger(document.body, 'balanceUpdated');
                window.location.href = '/';
            }, 5000);
        """)
    )

# Stripe webhook to handle payment events
@app.post('/webhook', include_in_schema=False)
@app.post('/webhook/')
async def page_stripe_webhook(request):
    payload = await request.body()
    signature = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return {'error': 'Invalid payload or signature'}, 400

    if event['type'] == 'checkout.session.completed':
        session_obj = event['data']['object']
        user_email = session_obj['metadata'].get('user_email')
        credit_amount = session_obj['metadata'].get('credit_amount')

        if not user_email or not credit_amount:
            return {'error': 'Missing user email or credit amount in metadata'}, 400

        try:
            user = users[user_email]
            new_balance = user.balance + int(credit_amount)  # Add the corresponding credits
            users.update({'email': user_email, 'balance': new_balance})
        except NotFoundError:
            print(f"User with email {user_email} not found.")
            return {'error': 'User not found'}, 404

        return {'status': 'success'}, 200

    return {'status': 'unhandled_event_type'}, 400

# Run the app
if __name__ == '__main__': uvicorn.run("main:app", host='0.0.0.0', port=int(os.getenv("PORT", default=5000)))