import requests
import sys
import json
from datetime import datetime

class ShoeHavenAPITester:
    def __init__(self, base_url="https://shoe-haven-91.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.user_token = None
        self.admin_token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.created_product_id = None

    def log_test(self, name, success, details="", error=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {error}")
        
        self.test_results.append({
            "name": name,
            "success": success,
            "details": details,
            "error": error
        })

    def make_request(self, method, endpoint, data=None, headers=None, expected_status=200):
        """Make HTTP request and return response"""
        url = f"{self.base_url}/{endpoint}"
        default_headers = {'Content-Type': 'application/json'}
        if headers:
            default_headers.update(headers)

        try:
            if method == 'GET':
                response = requests.get(url, headers=default_headers)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=default_headers)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=default_headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=default_headers)

            success = response.status_code == expected_status
            return success, response
        except Exception as e:
            return False, str(e)

    def test_seed_data(self):
        """Test data seeding"""
        success, response = self.make_request('POST', 'seed', expected_status=200)
        if success:
            self.log_test("Seed Data", True, "Data seeded successfully")
        else:
            self.log_test("Seed Data", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_user_registration(self):
        """Test user registration"""
        test_user = {
            "email": f"test_user_{datetime.now().strftime('%H%M%S')}@test.com",
            "password": "TestPass123!",
            "name": "Test User"
        }
        
        success, response = self.make_request('POST', 'auth/register', data=test_user, expected_status=200)
        if success:
            data = response.json()
            if 'token' in data and 'user' in data:
                self.user_token = data['token']
                self.log_test("User Registration", True, f"User created with ID: {data['user']['id']}")
            else:
                self.log_test("User Registration", False, error="Missing token or user in response")
        else:
            error_msg = response.json().get('detail', 'Unknown error') if hasattr(response, 'json') else str(response)
            self.log_test("User Registration", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'} - {error_msg}")

    def test_admin_login(self):
        """Test admin login with provided credentials"""
        admin_creds = {
            "email": "admin@shoehaven.com",
            "password": "admin123"
        }
        
        success, response = self.make_request('POST', 'auth/login', data=admin_creds, expected_status=200)
        if success:
            data = response.json()
            if 'token' in data and data['user']['role'] == 'admin':
                self.admin_token = data['token']
                self.log_test("Admin Login", True, f"Admin logged in: {data['user']['email']}")
            else:
                self.log_test("Admin Login", False, error="Invalid admin response or role")
        else:
            error_msg = response.json().get('detail', 'Unknown error') if hasattr(response, 'json') else str(response)
            self.log_test("Admin Login", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'} - {error_msg}")

    def test_get_products(self):
        """Test getting all products"""
        success, response = self.make_request('GET', 'products', expected_status=200)
        if success:
            products = response.json()
            if isinstance(products, list) and len(products) > 0:
                self.log_test("Get All Products", True, f"Retrieved {len(products)} products")
            else:
                self.log_test("Get All Products", False, error="No products returned or invalid format")
        else:
            self.log_test("Get All Products", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_get_products_by_category(self):
        """Test filtering products by category"""
        categories = ['men', 'women', 'kids', 'sports']
        for category in categories:
            success, response = self.make_request('GET', f'products?category={category}', expected_status=200)
            if success:
                products = response.json()
                if isinstance(products, list):
                    self.log_test(f"Get {category.title()} Products", True, f"Retrieved {len(products)} {category} products")
                else:
                    self.log_test(f"Get {category.title()} Products", False, error="Invalid response format")
            else:
                self.log_test(f"Get {category.title()} Products", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_get_featured_products(self):
        """Test getting featured products"""
        success, response = self.make_request('GET', 'products?featured=true', expected_status=200)
        if success:
            products = response.json()
            if isinstance(products, list):
                featured_count = len([p for p in products if p.get('featured', False)])
                self.log_test("Get Featured Products", True, f"Retrieved {len(products)} products, {featured_count} marked as featured")
            else:
                self.log_test("Get Featured Products", False, error="Invalid response format")
        else:
            self.log_test("Get Featured Products", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_get_single_product(self):
        """Test getting a single product by ID"""
        # First get all products to get a valid ID
        success, response = self.make_request('GET', 'products', expected_status=200)
        if success:
            products = response.json()
            if products and len(products) > 0:
                product_id = products[0]['id']
                success, response = self.make_request('GET', f'products/{product_id}', expected_status=200)
                if success:
                    product = response.json()
                    if 'id' in product and product['id'] == product_id:
                        self.log_test("Get Single Product", True, f"Retrieved product: {product['name']}")
                    else:
                        self.log_test("Get Single Product", False, error="Product ID mismatch")
                else:
                    self.log_test("Get Single Product", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")
            else:
                self.log_test("Get Single Product", False, error="No products available to test")
        else:
            self.log_test("Get Single Product", False, error="Could not fetch products list")

    def test_user_cart_operations(self):
        """Test cart operations (requires user login)"""
        if not self.user_token:
            self.log_test("Cart Operations", False, error="No user token available")
            return

        headers = {'Authorization': f'Bearer {self.user_token}'}
        
        # Get cart
        success, response = self.make_request('GET', 'cart', headers=headers, expected_status=200)
        if success:
            cart = response.json()
            self.log_test("Get User Cart", True, f"Cart retrieved with {len(cart.get('items', []))} items")
        else:
            self.log_test("Get User Cart", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")
            return

        # Add item to cart (need a product ID first)
        success, response = self.make_request('GET', 'products', expected_status=200)
        if success:
            products = response.json()
            if products and len(products) > 0:
                product = products[0]
                cart_item = {
                    "product_id": product['id'],
                    "quantity": 2,
                    "size": product['sizes'][0] if product.get('sizes') else "10",
                    "color": product['colors'][0] if product.get('colors') else "Black"
                }
                
                success, response = self.make_request('POST', 'cart/add', data=cart_item, headers=headers, expected_status=200)
                if success:
                    self.log_test("Add to Cart", True, f"Added {cart_item['quantity']} items to cart")
                else:
                    self.log_test("Add to Cart", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_admin_product_operations(self):
        """Test admin product CRUD operations"""
        if not self.admin_token:
            self.log_test("Admin Product Operations", False, error="No admin token available")
            return

        headers = {'Authorization': f'Bearer {self.admin_token}'}
        
        # Create product
        new_product = {
            "name": "Test Luxury Shoe",
            "description": "A test luxury shoe for automated testing",
            "price": 299.99,
            "category": "men",
            "images": ["https://images.unsplash.com/photo-1614252369475-531eba835eb1?w=800"],
            "sizes": ["8", "9", "10", "11"],
            "colors": ["Black", "Brown"],
            "brand": "Test Brand",
            "stock": 50,
            "featured": False
        }
        
        success, response = self.make_request('POST', 'admin/products', data=new_product, headers=headers, expected_status=200)
        if success:
            created_product = response.json()
            self.created_product_id = created_product['id']
            self.log_test("Admin Create Product", True, f"Created product: {created_product['name']}")
            
            # Update product
            update_data = {
                "price": 349.99,
                "featured": True
            }
            success, response = self.make_request('PUT', f'admin/products/{self.created_product_id}', data=update_data, headers=headers, expected_status=200)
            if success:
                self.log_test("Admin Update Product", True, "Product updated successfully")
            else:
                self.log_test("Admin Update Product", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")
                
        else:
            self.log_test("Admin Create Product", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_admin_stats(self):
        """Test admin statistics endpoint"""
        if not self.admin_token:
            self.log_test("Admin Stats", False, error="No admin token available")
            return

        headers = {'Authorization': f'Bearer {self.admin_token}'}
        success, response = self.make_request('GET', 'admin/stats', headers=headers, expected_status=200)
        if success:
            stats = response.json()
            required_fields = ['total_products', 'total_orders', 'total_users', 'total_revenue']
            if all(field in stats for field in required_fields):
                self.log_test("Admin Stats", True, f"Stats: {stats['total_products']} products, {stats['total_users']} users, ${stats['total_revenue']} revenue")
            else:
                self.log_test("Admin Stats", False, error="Missing required fields in stats response")
        else:
            self.log_test("Admin Stats", False, error=f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}")

    def test_checkout_session_creation(self):
        """Test checkout session creation (requires items in cart)"""
        if not self.user_token:
            self.log_test("Checkout Session", False, error="No user token available")
            return

        headers = {'Authorization': f'Bearer {self.user_token}'}
        checkout_data = {
            "origin_url": "https://shoe-haven-91.preview.emergentagent.com"
        }
        
        success, response = self.make_request('POST', 'checkout/create-session', data=checkout_data, headers=headers, expected_status=200)
        if success:
            session_data = response.json()
            if 'url' in session_data and 'session_id' in session_data:
                self.log_test("Checkout Session Creation", True, f"Session created: {session_data['session_id'][:16]}...")
            else:
                self.log_test("Checkout Session Creation", False, error="Missing URL or session_id in response")
        else:
            # This might fail if cart is empty, which is expected
            try:
                error_msg = response.json().get('detail', 'Unknown error') if hasattr(response, 'json') else str(response)
            except:
                error_msg = f"Status: {response.status_code if hasattr(response, 'status_code') else 'Connection Error'}"
            
            if "empty" in error_msg.lower():
                self.log_test("Checkout Session Creation", True, "Correctly rejected empty cart")
            else:
                self.log_test("Checkout Session Creation", False, error=error_msg)

    def cleanup_test_data(self):
        """Clean up test data"""
        if self.created_product_id and self.admin_token:
            headers = {'Authorization': f'Bearer {self.admin_token}'}
            success, response = self.make_request('DELETE', f'admin/products/{self.created_product_id}', headers=headers, expected_status=200)
            if success:
                self.log_test("Cleanup Test Product", True, "Test product deleted")
            else:
                self.log_test("Cleanup Test Product", False, error="Failed to delete test product")

    def run_all_tests(self):
        """Run all API tests"""
        print("🚀 Starting ShoeHaven API Tests...")
        print(f"📍 Testing API at: {self.base_url}")
        print("=" * 60)

        # Core functionality tests
        self.test_seed_data()
        self.test_user_registration()
        self.test_admin_login()
        
        # Product tests
        self.test_get_products()
        self.test_get_products_by_category()
        self.test_get_featured_products()
        self.test_get_single_product()
        
        # User functionality tests
        self.test_user_cart_operations()
        
        # Admin functionality tests
        self.test_admin_product_operations()
        self.test_admin_stats()
        
        # Checkout tests
        self.test_checkout_session_creation()
        
        # Cleanup
        self.cleanup_test_data()

        # Print summary
        print("=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"✨ Success Rate: {success_rate:.1f}%")
        
        return self.tests_passed == self.tests_run

def main():
    tester = ShoeHavenAPITester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())