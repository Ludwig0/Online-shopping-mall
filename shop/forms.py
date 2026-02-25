from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import CustomerProfile, Product, ProductImage, ProductVariant, CustomerReview

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

class CustomerReviewForm(forms.ModelForm):
    class Meta:
        model = CustomerReview
        fields = ['rating', 'review_text']
        widgets = {
            'rating': forms.Select(choices=[(i, str(i)) for i in range(1, 6)]),
            'review_text': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Write your review here...'}),
        }