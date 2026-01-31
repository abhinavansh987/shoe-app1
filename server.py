from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Header
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone
import bcrypt
import jwt
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'default_secret_key')
JWT_ALGORITHM = "HS256"

# Stripe Config
STRIPE_API_KEY = os.environ.get('STRIPE_API_KEY')

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    role: str = "user"
    created_at: str

class TokenResponse(BaseModel):
    token: str
    user: UserResponse

class ProductCreate(BaseModel):
    name: str
    description: str
    price: float
    category: str  # men, women, kids, sports
    images: List[str]
    sizes: List[str]
    colors: List[str]
    brand: str
    stock: int = 100
    featured: bool = False

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    images: Optional[List[str]] = None
    sizes: Optional[List[str]] = None
    colors: Optional[str] = None
    brand: Optional[str] = None
    stock: Optional[int] = None
    featured: Optional[bool] = None

class ProductResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    description: str
    price: float
    category: str
    images: List[str]
    sizes: List[str]
    colors: List[str]
    brand: str
    stock: int
    featured: bool
    created_at: str

class CartItem(BaseModel):
    product_id: str
    quantity: int
    size: str
    color: str

class CartResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    items: List[dict]
    updated_at: str

class OrderCreate(BaseModel):
    shipping_address: dict
    items: List[dict]

class CheckoutRequest(BaseModel):
    origin_url: str

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc).timestamp() + 86400 * 7  # 7 days
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_admin_user(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "email": user_data.email,
        "password": hash_password(user_data.password),
        "name": user_data.name,
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    
    token = create_token(user_id, user_data.email, "user")
    user_response = UserResponse(
        id=user_id, email=user_data.email, name=user_data.name,
        role="user", created_at=user["created_at"]
    )
    return TokenResponse(token=token, user=user_response)

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"], user["email"], user.get("role", "user"))
    user_response = UserResponse(
        id=user["id"], email=user["email"], name=user["name"],
        role=user.get("role", "user"), created_at=user["created_at"]
    )
    return TokenResponse(token=token, user=user_response)

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    return UserResponse(
        id=user["id"], email=user["email"], name=user["name"],
        role=user.get("role", "user"), created_at=user["created_at"]
    )

# ==================== PRODUCT ROUTES ====================

@api_router.get("/products", response_model=List[ProductResponse])
async def get_products(category: Optional[str] = None, featured: Optional[bool] = None):
    query = {}
    if category:
        query["category"] = category
    if featured is not None:
        query["featured"] = featured
    products = await db.products.find(query, {"_id": 0}).to_list(100)
    return products

@api_router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: str):
    product = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@api_router.post("/admin/products", response_model=ProductResponse)
async def create_product(product: ProductCreate, user: dict = Depends(get_admin_user)):
    product_id = str(uuid.uuid4())
    product_dict = {
        "id": product_id,
        **product.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.products.insert_one(product_dict)
    product_dict.pop("_id", None)
    return product_dict

@api_router.put("/admin/products/{product_id}", response_model=ProductResponse)
async def update_product(product_id: str, product: ProductUpdate, user: dict = Depends(get_admin_user)):
    update_data = {k: v for k, v in product.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    result = await db.products.update_one({"id": product_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    
    updated = await db.products.find_one({"id": product_id}, {"_id": 0})
    return updated

@api_router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, user: dict = Depends(get_admin_user)):
    result = await db.products.delete_one({"id": product_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted"}

# ==================== CART ROUTES ====================

@api_router.get("/cart")
async def get_cart(user: dict = Depends(get_current_user)):
    cart = await db.carts.find_one({"user_id": user["id"]}, {"_id": 0})
    if not cart:
        cart = {"id": str(uuid.uuid4()), "user_id": user["id"], "items": [], "updated_at": datetime.now(timezone.utc).isoformat()}
        await db.carts.insert_one(cart)
        cart.pop("_id", None)
    
    # Populate product details
    populated_items = []
    for item in cart.get("items", []):
        product = await db.products.find_one({"id": item["product_id"]}, {"_id": 0})
        if product:
            populated_items.append({**item, "product": product})
    cart["items"] = populated_items
    return cart

@api_router.post("/cart/add")
async def add_to_cart(item: CartItem, user: dict = Depends(get_current_user)):
    cart = await db.carts.find_one({"user_id": user["id"]}, {"_id": 0})
    if not cart:
        cart = {"id": str(uuid.uuid4()), "user_id": user["id"], "items": [], "updated_at": datetime.now(timezone.utc).isoformat()}
        await db.carts.insert_one(cart)
    
    items = cart.get("items", [])
    existing_index = next((i for i, x in enumerate(items) if x["product_id"] == item.product_id and x["size"] == item.size and x["color"] == item.color), None)
    
    if existing_index is not None:
        items[existing_index]["quantity"] += item.quantity
    else:
        items.append(item.model_dump())
    
    await db.carts.update_one(
        {"user_id": user["id"]},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"message": "Item added to cart"}

@api_router.put("/cart/update")
async def update_cart_item(item: CartItem, user: dict = Depends(get_current_user)):
    cart = await db.carts.find_one({"user_id": user["id"]}, {"_id": 0})
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    
    items = cart.get("items", [])
    for i, x in enumerate(items):
        if x["product_id"] == item.product_id and x["size"] == item.size and x["color"] == item.color:
            if item.quantity <= 0:
                items.pop(i)
            else:
                items[i]["quantity"] = item.quantity
            break
    
    await db.carts.update_one(
        {"user_id": user["id"]},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"message": "Cart updated"}

@api_router.delete("/cart/clear")
async def clear_cart(user: dict = Depends(get_current_user)):
    await db.carts.update_one(
        {"user_id": user["id"]},
        {"$set": {"items": [], "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    return {"message": "Cart cleared"}

# ==================== CHECKOUT/PAYMENT ROUTES ====================

@api_router.post("/checkout/create-session")
async def create_checkout_session(request: CheckoutRequest, http_request: Request, user: dict = Depends(get_current_user)):
    cart = await db.carts.find_one({"user_id": user["id"]}, {"_id": 0})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")
    
    # Calculate total from server-side data
    total = 0.0
    for item in cart["items"]:
        product = await db.products.find_one({"id": item["product_id"]}, {"_id": 0})
        if product:
            total += product["price"] * item["quantity"]
    
    if total <= 0:
        raise HTTPException(status_code=400, detail="Invalid cart total")
    
    origin_url = request.origin_url
    success_url = f"{origin_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/cart"
    
    host_url = str(http_request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    checkout_request = CheckoutSessionRequest(
        amount=float(total),
        currency="usd",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": user["id"], "cart_id": cart["id"]}
    )
    
    session = await stripe_checkout.create_checkout_session(checkout_request)
    
    # Create payment transaction record
    transaction = {
        "id": str(uuid.uuid4()),
        "session_id": session.session_id,
        "user_id": user["id"],
        "amount": total,
        "currency": "usd",
        "status": "pending",
        "payment_status": "initiated",
        "metadata": {"cart_id": cart["id"]},
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.payment_transactions.insert_one(transaction)
    
    return {"url": session.url, "session_id": session.session_id}

@api_router.get("/checkout/status/{session_id}")
async def get_checkout_status(session_id: str, http_request: Request, user: dict = Depends(get_current_user)):
    host_url = str(http_request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    status = await stripe_checkout.get_checkout_status(session_id)
    
    # Update transaction status
    if status.payment_status == "paid":
        transaction = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        if transaction and transaction.get("payment_status") != "paid":
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"status": "complete", "payment_status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            
            # Create order
            cart = await db.carts.find_one({"user_id": user["id"]}, {"_id": 0})
            if cart and cart.get("items"):
                order = {
                    "id": str(uuid.uuid4()),
                    "user_id": user["id"],
                    "items": cart["items"],
                    "total": status.amount_total / 100,
                    "status": "confirmed",
                    "payment_session_id": session_id,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await db.orders.insert_one(order)
                await db.carts.update_one({"user_id": user["id"]}, {"$set": {"items": []}})
    
    return {
        "status": status.status,
        "payment_status": status.payment_status,
        "amount_total": status.amount_total,
        "currency": status.currency
    }

@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    
    try:
        host_url = str(request.base_url).rstrip('/')
        webhook_url = f"{host_url}/api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
        webhook_response = await stripe_checkout.handle_webhook(body, signature)
        
        if webhook_response.payment_status == "paid":
            await db.payment_transactions.update_one(
                {"session_id": webhook_response.session_id},
                {"$set": {"status": "complete", "payment_status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        
        return {"received": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"received": True}

# ==================== ORDER ROUTES ====================

@api_router.get("/orders")
async def get_orders(user: dict = Depends(get_current_user)):
    orders = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return orders

@api_router.get("/admin/orders")
async def get_all_orders(user: dict = Depends(get_admin_user)):
    orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return orders

# ==================== ADMIN STATS ====================

@api_router.get("/admin/stats")
async def get_admin_stats(user: dict = Depends(get_admin_user)):
    total_products = await db.products.count_documents({})
    total_orders = await db.orders.count_documents({})
    total_users = await db.users.count_documents({})
    
    # Calculate total revenue
    orders = await db.orders.find({}, {"_id": 0, "total": 1}).to_list(1000)
    total_revenue = sum(order.get("total", 0) for order in orders)
    
    return {
        "total_products": total_products,
        "total_orders": total_orders,
        "total_users": total_users,
        "total_revenue": total_revenue
    }

# ==================== SEED DATA ====================

@api_router.post("/seed")
async def seed_data():
    # Check if products exist
    existing = await db.products.count_documents({})
    if existing > 0:
        return {"message": "Data already seeded"}
    
    # Seed products
    products = [
        {
            "id": str(uuid.uuid4()),
            "name": "Classic Oxford",
            "description": "Timeless elegance meets unparalleled comfort. Handcrafted from premium Italian leather with Goodyear welt construction.",
            "price": 485.00,
            "category": "men",
            "images": ["https://images.unsplash.com/photo-1614252369475-531eba835eb1?w=800", "https://images.unsplash.com/photo-1587521503498-24ac2bab8f72?w=800"],
            "sizes": ["7", "8", "9", "10", "11", "12"],
            "colors": ["Black", "Cognac", "Burgundy"],
            "brand": "Maison Luxe",
            "stock": 50,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Stiletto Elegance",
            "description": "A masterpiece of design. These stunning heels feature genuine Nappa leather and a hand-polished finish.",
            "price": 595.00,
            "category": "women",
            "images": ["https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=800", "https://images.unsplash.com/photo-1515347619252-60a4bf4fff4f?w=800"],
            "sizes": ["5", "6", "7", "8", "9"],
            "colors": ["Noir", "Crimson", "Nude"],
            "brand": "Valentina",
            "stock": 35,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Monaco Loafer",
            "description": "Effortless sophistication. Slip-on luxury crafted from supple suede with leather-wrapped soles.",
            "price": 425.00,
            "category": "men",
            "images": ["https://images.unsplash.com/photo-1626379953822-baec19c3accd?w=800", "https://images.unsplash.com/photo-1533867617858-e7b97e060509?w=800"],
            "sizes": ["7", "8", "9", "10", "11", "12"],
            "colors": ["Navy", "Tan", "Charcoal"],
            "brand": "Maison Luxe",
            "stock": 45,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Athena Sandal",
            "description": "Goddess-worthy comfort. Braided leather straps meet a cushioned footbed for all-day elegance.",
            "price": 345.00,
            "category": "women",
            "images": ["https://images.unsplash.com/photo-1603808033192-082d6919d3e1?w=800", "https://images.unsplash.com/photo-1562273138-f46be4ebdf33?w=800"],
            "sizes": ["5", "6", "7", "8", "9"],
            "colors": ["Gold", "Silver", "Bronze"],
            "brand": "Valentina",
            "stock": 40,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Junior Elite",
            "description": "Premium quality for young explorers. Durable yet stylish footwear designed for active kids.",
            "price": 185.00,
            "category": "kids",
            "images": ["https://images.unsplash.com/photo-1555274175-75f79b09d5b8?w=800", "https://images.unsplash.com/photo-1514989940723-e8e51d675571?w=800"],
            "sizes": ["1", "2", "3", "4", "5"],
            "colors": ["White", "Navy", "Red"],
            "brand": "Piccolo",
            "stock": 60,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Velocity Pro",
            "description": "Engineered for excellence. Advanced cushioning technology meets aerodynamic design.",
            "price": 275.00,
            "category": "sports",
            "images": ["https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800", "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=800"],
            "sizes": ["7", "8", "9", "10", "11", "12"],
            "colors": ["Black/Gold", "White/Silver", "Navy/Red"],
            "brand": "Athletica",
            "stock": 75,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Chelsea Boot",
            "description": "The epitome of British craftsmanship. Full-grain leather with elastic side panels.",
            "price": 545.00,
            "category": "men",
            "images": ["https://images.unsplash.com/photo-1638247025967-b4e38f787b76?w=800", "https://images.unsplash.com/photo-1605812860427-4024433a70fd?w=800"],
            "sizes": ["7", "8", "9", "10", "11", "12"],
            "colors": ["Black", "Brown", "Suede Tan"],
            "brand": "Maison Luxe",
            "stock": 30,
            "featured": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Ballet Flat",
            "description": "Parisian chic at its finest. Quilted leather with signature bow detail.",
            "price": 365.00,
            "category": "women",
            "images": ["https://images.unsplash.com/photo-1566150905458-1bf1fc113f0d?w=800", "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=800"],
            "sizes": ["5", "6", "7", "8", "9"],
            "colors": ["Blush", "Black", "Cream"],
            "brand": "Valentina",
            "stock": 55,
            "featured": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    await db.products.insert_many(products)
    
    # Create admin user
    admin_exists = await db.users.find_one({"email": "admin@shoehaven.com"})
    if not admin_exists:
        admin = {
            "id": str(uuid.uuid4()),
            "email": "admin@shoehaven.com",
            "password": hash_password("admin123"),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(admin)
    
    return {"message": "Data seeded successfully"}

@api_router.get("/")
async def root():
    return {"message": "Shoe Haven API"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
