from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import CustomerProfile, Product, ProductImage, ProductVariant


class RegisterForm(UserCreationForm):
    full_name = forms.CharField(max_length=200)
    email = forms.EmailField()
    shipping_address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))

    class Meta:
        model = User
        fields = ['username', 'full_name', 'email', 'password1', 'password2', 'shipping_address']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            CustomerProfile.objects.create(
                user=user,
                full_name=self.cleaned_data['full_name'],
                shipping_address=self.cleaned_data['shipping_address']
            )
        return user


class CartQuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'title', 'slug', 'description', 'authors', 'publisher', 'published_date', 'category',
            'base_price', 'thumbnail_url', 'is_active', 'is_configurable'
        ]


class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ['image_url', 'alt_text', 'sort_order']


class VariantStockForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['inventory_status', 'is_default']