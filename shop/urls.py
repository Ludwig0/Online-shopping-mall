from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views
from .models import PurchaseOrder

urlpatterns = [
    # Storefront
    path('', views.product_list, name='product_list'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('product/<int:product_id>/review/', views.submit_product_review, name='submit_product_review'),

    # Auth
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # Cart / checkout
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/item/<int:item_id>/update/', views.cart_update_item, name='cart_update_item'),
    path('cart/item/<int:item_id>/remove/', views.cart_remove_item, name='cart_remove_item'),
    path('checkout/', views.checkout_view, name='checkout'),

    # Customer orders
    path('orders/', views.order_list, name='order_list'),
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),
    path('orders/<int:order_id>/cancel/', views.customer_cancel_order, name='customer_cancel_order'),
    path('order/<int:order_id>/pay/', views.order_pay, name='order_pay'),
    # Admin portal (basic spec allows no authentication)
    path('admin-portal/products/', views.admin_product_list, name='admin_product_list'),
    path('admin-portal/products/create/', views.admin_product_create, name='admin_product_create'),
    path('admin-portal/products/<int:product_id>/edit/', views.admin_product_edit, name='admin_product_edit'),
    path('admin-portal/products/<int:product_id>/toggle/', views.admin_product_toggle_active, name='admin_product_toggle_active'),

    path('admin-portal/orders/', views.admin_order_list, name='admin_order_list'),
    path('admin-portal/orders/<int:order_id>/', views.admin_order_detail, name='admin_order_detail'),
    path('admin-portal/orders/<int:order_id>/status/pending/', views.admin_order_change_status, {'new_status': PurchaseOrder.STATUS_PENDING}, name='admin_order_pending'),
    path('admin-portal/orders/<int:order_id>/status/hold/', views.admin_order_change_status, {'new_status': PurchaseOrder.STATUS_HOLD}, name='admin_order_hold'),
    path('admin-portal/orders/<int:order_id>/status/shipped/', views.admin_order_change_status, {'new_status': PurchaseOrder.STATUS_SHIPPED}, name='admin_order_shipped'),
    path('admin-portal/orders/<int:order_id>/status/cancelled/', views.admin_order_change_status, {'new_status': PurchaseOrder.STATUS_CANCELLED}, name='admin_order_cancelled'),
]