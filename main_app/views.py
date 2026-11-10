from django.urls import reverse_lazy
from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.views.generic import ListView, DetailView
from django.views.generic.edit import DeleteView
from .forms import SignUpForm, CustomLoginForm
from .models import Product, Retailer, Wishlist, PriceHistory
import urllib.parse
import requests
import re
import os

def about(request):
    return render(request, 'about.html')

class Home(LoginView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['deals_of_the_day'] = deals_of_the_day_init(self.request)
        return context

class CustomLoginView(LoginView):
    authentication_form = CustomLoginForm
    template_name = 'registration/login.html'
    
def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Account created successfully!')
            return redirect('login')  
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})

class WishlistView(LoginRequiredMixin, ListView):
    model = Wishlist
    template_name = 'products/wishlist.html'
    context_object_name = 'wishlist_items'

    def get_queryset(self):
        wishlist_items = Wishlist.objects.filter(user=self.request.user)
        for item in wishlist_items:
            latest_price = PriceHistory.objects.filter(product=item.product).order_by('-timestamp').first()
            item.product.current_price = latest_price.price if latest_price else None
        return wishlist_items

def fetch_web_api_data(endpoint, payload):
    api_key = os.environ.get('OXYLABS_WEB_API_KEY')
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    if 'output' not in payload:
        payload['output'] = ['json']
    response = requests.post(
        f'https://webapi.oxylabs.io{endpoint}',
        headers=headers,
        json=payload,
    )
    if not response.ok:
        return {}
    data = response.json()
    if 'results' in data and len(data['results']) > 0:
        return data['results'][0].get('json') or data['results'][0].get('content') or {}
    return {}

def get_logo_url(merchant_name):
    if '.' in merchant_name:
        cleaned_name = re.split(r'\.com|\.net|\.org', merchant_name)[0] + ".com"
        return f"https://img.logo.dev/{cleaned_name}?token=pk_MHqHMYHhSPqsrHGnE0dW1Q"
    
    cleaned_name = merchant_name.replace("'", "")
    cleaned_name = cleaned_name.replace(" ", "")
    
    return f"https://img.logo.dev/{cleaned_name}.com?token=pk_MHqHMYHhSPqsrHGnE0dW1Q"

def clean_merchant_name(merchant_name):
    cleaned_name = merchant_name.replace("'", "")
    cleaned_name = cleaned_name.replace(" ", "")
    cleaned_name = re.sub(r'\.com|\.net|\.org', '', cleaned_name)
    cleaned_name = cleaned_name.strip()
    return cleaned_name

def extract_url(full_url):
    parsed_url = urllib.parse.urlparse(full_url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    return query_params.get('url', [full_url])[0]

def format_top_review(review_text):
    formatted_review = review_text.replace("\n", "<br>")
    if formatted_review.endswith("<br>Read more"):
        formatted_review = formatted_review[:-len("<br>Read more")]
    return formatted_review

def product_search(request):
    if request.method == 'POST':
        query = request.POST.get('query')

        amz_data = fetch_web_api_data('/v1/scrape/amazon/search', {'query': query})
        ggl_data = fetch_web_api_data('/v1/scrape/google/shopping/search', {'query': query})
                                                     
        amz_results = amz_data.get('results', {}).get('organic', [])
        ggl_results = ggl_data.get('results', {}).get('organic', [])

        for product in amz_results:
            product['logo_url'] = get_logo_url('Amazon.com')
        
        for product in ggl_results:
            merchant_name = product['merchant']['name']
            product['logo_url'] = get_logo_url(merchant_name)

        # Add the cleaned merchant name to each Google Shopping product. (Remove the domain from the merchant name)
        for product in ggl_results:
             product['cleaned_merchant_name'] = clean_merchant_name(product['merchant']['name'])

        valid_amz_products = [
            product for product in amz_results
            if all([
                product.get('url'),
                product.get('asin'),
                product.get('price'),
                product.get('title'),
                product.get('url_image'),
            ])
        ]
        
        valid_ggl_products = [
            product for product in ggl_results
            if all([
                product.get('price'),
                product.get('title'),
                product.get('merchant'),
                product.get('thumbnail'),
                product.get('rating'),
            ])
        ]

        if not valid_ggl_products and not valid_amz_products:
            return HttpResponse("Your search didn't produce any results. Refine your search and try again! 🦸‍♀️")

        def sorting_key(product):
            return (
                    -product.get('pos', 0),  
                    1 if product.get('is_amazons_choice', False) else 0,  
                    1 if product.get('best_seller', False) else 0,  
                    product.get('reviews_count', 0),  
                    product.get('rating', 0),  
                    -product['price'],  
            )

        amz_sorted_products = sorted(valid_amz_products, key=sorting_key, reverse=True)
        amz_best_product = amz_sorted_products[0]

        ggl_sorted_products = sorted(valid_ggl_products, key=sorting_key, reverse=True)
        ggl_best_product = ggl_sorted_products[0] if ggl_sorted_products else None
        
        amz_best_product['rating_width'] = float(amz_best_product['rating']) * 20
        ggl_best_product['rating_width'] = float(ggl_best_product['rating']) * 20 if ggl_best_product else 0

        for product in amz_sorted_products:
            if product.get('rating'):
                product['rating_width'] = float(product['rating']) * 20

        for product in ggl_sorted_products:
            if product.get('rating'):
                product['rating_width'] = float(product['rating']) * 20

        return render(request, 'products/products_index.html', {
            'amz_best_product': amz_best_product,
            'amz_products': amz_sorted_products,
            'gg_best_product': ggl_best_product,
            'ggl_products': ggl_sorted_products,
        })

    return redirect('home')

def fetch_product_details(product_asin, user):
    product_data = fetch_web_api_data('/v1/scrape/amazon/product', {'query': f'{product_asin}'})
    
    product_name = product_data.get('product_name') or product_data.get('title')
    asin = product_data.get('asin') or product_asin
    category = product_data.get('category', [{}])[0].get('ladder', [{}])[0].get('name', 'Miscelaneous') if product_data.get('category') else 'Miscelaneous'
    product_url = product_data.get('url', '')
    images = product_data.get('images', [])
    image_url = images[0] if images else product_data.get('url_image', '')
    description = product_data.get('description', '')
    rating = product_data.get('rating', 0)
    stock_value = product_data.get('stock', "in stock")
    in_stock = stock_value.lower() == 'in stock' if isinstance(stock_value, str) else True
    price = product_data.get('price', 0)
    manufacturer = product_data.get('manufacturer')
    retailer_name = manufacturer if manufacturer else (product_name.split()[0] if product_name else 'Amazon')
    more_images = images
    amazon_choice = product_data.get('amazon_choice', product_data.get('is_amazons_choice', False))
    is_prime_eligible = product_data.get('is_prime_eligible', product_data.get('is_prime', False))
    raw_bullet_points = product_data.get('bullet_points', [])
    if isinstance(raw_bullet_points, str):
        bullet_points = raw_bullet_points.split('\n')
    elif isinstance(raw_bullet_points, list):
        bullet_points = raw_bullet_points
    else:
        bullet_points = []
    reviews_count = product_data.get('reviews_count', 0)
    top_review_raw = product_data.get('top_review', '')
    formatted_review = format_top_review(top_review_raw) if top_review_raw else ''
    rating_stars_distribution = product_data.get('rating_stars_distribution', {})

    # The rating_width is the value used to render the star ratings in the templates dynamically ⭐⭐⭐.
    rating_width = float(rating) * 20
    
    retailer, created = Retailer.objects.get_or_create(name=retailer_name)      
    product, created = Product.objects.get_or_create(
        name = product_name,
        defaults={
            'asin': asin,
            'category': category,
            'product_url': product_url,
            'image_url': image_url,
            'description': description,
            'rating': rating,
            'rating_width': rating_width,
            'in_stock': in_stock,
            'price_drop_threshold': 1,
            'user': user,
            'retailer': retailer,
            'more_images': more_images,
            'amazon_choice': amazon_choice,
            'is_prime_eligible': is_prime_eligible,
            'bullet_points': bullet_points,
            'reviews_count': reviews_count,
            'top_review': formatted_review,
            'rating_stars_distribution': rating_stars_distribution,
        }
    )

    PriceHistory.objects.create(
        product=product,
        price=price
    )
    
    return product

@login_required
def add_to_wishlist(request, product_asin):
    if request.method == 'POST':
        product = fetch_product_details(product_asin, request.user)
        
        Wishlist.objects.get_or_create(
            product=product,
            user=request.user
        )

        return redirect('wishlist')

class DeleteProduct(LoginRequiredMixin, DeleteView):
    model = Wishlist
    template_name = 'products/product_confirm_delete.html'
    # success_url = '/wishlist/'
    success_url = reverse_lazy('wishlist')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Assuming the Wishlist model has a ForeignKey to Product
        context['product'] = self.object.product
        return context

class ProductDetail(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'products/product_detail.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.get_object()
        latest_price = PriceHistory.objects.filter(product=product).order_by('-timestamp').first()
        price_history = PriceHistory.objects.filter(product=product).order_by('-timestamp')
        context['latest_price'] = latest_price.price if latest_price else None
        context['price_history'] = price_history
        return context
    
def update_price(request, pk):
    product = Product.objects.get(pk=pk)
    current_price = PriceHistory.objects.filter(product=product).order_by('-timestamp').first()
    
    pricing_data = fetch_web_api_data('/v1/scrape/amazon/pricing', {'query': product.asin})
    pricing_list = pricing_data.get('pricing', [])
    
    if pricing_list:
        sellers = {}
        for seller_info in pricing_list:
            seller_name = seller_info.get('seller') or 'Amazon'
            sellers[seller_name] = {
                'seller_name': seller_name,
                'seller_link': seller_info.get('seller_link') or '',
                'price': seller_info.get('price') or (current_price.price if current_price else 0),
            }

        best_seller = min(sellers, key=lambda x: sellers[x]['price'])
        seller = sellers[best_seller]

        retailer, created = Retailer.objects.get_or_create(
            name=seller['seller_name'],
            defaults={'merchant_url': seller['seller_link']}
        )
        
        PriceHistory.objects.create(
            product=product,
            price=seller['price'],
            retailer=retailer
        )
    price_history = PriceHistory.objects.filter(product=product).order_by('-timestamp')
    current_retailer = price_history.first().retailer if price_history.exists() else None
    return render(request, 'htmx/update_price_table.html', {
        'price_history': price_history,
        'retailer': current_retailer,
    })


def deals_of_the_day_init(request):

    category = 'Electronics' 

    if request.method == 'POST':
        category = request.POST.get('category', '')
    
    data = fetch_web_api_data('/v1/scrape/amazon/search', {'query': f'deals of the day {category}'})
    deals_of_the_day = data.get('results', {}).get('organic', [])
    
    valid_deal_products = [
        product for product in deals_of_the_day
        if all([
            product.get('url'),
            product.get('asin'),
            product.get('price'),
            product.get('title'),
            product.get('url_image'),
            product.get('price_strikethrough'),
            product.get('reviews_count', 0) > 10,
            ])
        ]
    
    for product in valid_deal_products:
        price = product.get('price')
        strike_through_price = product.get('price_strikethrough')
        product['price'] = price
        product['strike_through_price'] = strike_through_price
        if strike_through_price and strike_through_price > 0:
            discount = (1 - price / strike_through_price) * 100
        else:
            discount = 0

        product['discount'] = int(round(discount))
        product['rating_width'] = float(product['rating']) * 20
        product['logo_url'] = get_logo_url('Amazon.com')
        
    sorted_deals = sorted(valid_deal_products, key=lambda x: x['discount'], reverse=True)
    return sorted_deals

def deals_of_the_day(request):

    category = 'Electronics'

    if request.method == 'POST':
        category = request.POST.get('category', '')
    
    data = fetch_web_api_data('/v1/scrape/amazon/search', {'query': f'deals of the day {category}'})
    deals_of_the_day = data.get('results', {}).get('organic', [])
    
    valid_deal_products = [
        product for product in deals_of_the_day
        if all([
            product.get('url'),
            product.get('asin'),
            product.get('price'),
            product.get('title'),
            product.get('url_image'),
            product.get('price_strikethrough'),
            product.get('reviews_count', 0) > 10,
            ])
        ]
    
    for product in valid_deal_products:
        price = product.get('price')
        strike_through_price = product.get('price_strikethrough')
        product['price'] = price
        product['strike_through_price'] = strike_through_price
        if strike_through_price and strike_through_price > 0:
            discount = (1 - price / strike_through_price) * 100
        else:
            discount = 0

        product['discount'] = int(round(discount))
        product['rating_width'] = float(product['rating']) * 20
        product['logo_url'] = get_logo_url('Amazon.com')
        
    sorted_deals = sorted(valid_deal_products, key=lambda x: x['discount'], reverse=True)
    return render(request, 'home.html', {'deals_of_the_day': sorted_deals})


