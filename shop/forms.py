import json
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

from .models import (
    CustomerProfile,
    CustomerReview,
    Product,
    ProductImage,
    ProductVariant,
)

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
    options_payload = forms.CharField(required=False, widget=forms.HiddenInput())
    variants_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Product
        fields = [
            'title', 'description', 'authors', 'publisher', 'published_date', 'category',
            'base_price', 'thumbnail_url', 'is_active', 'is_configurable'
        ]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)
        if instance and instance.pk:
            self.fields['options_payload'].initial = json.dumps(self._serialize_options(instance))
            self.fields['variants_payload'].initial = json.dumps(self._serialize_variants(instance))
        else:
            self.fields['options_payload'].initial = '[]'
            self.fields['variants_payload'].initial = '[]'

    def clean(self):
        cleaned_data = super().clean()
        options_data = self._parse_payload('options_payload')
        variants_data = self._parse_payload('variants_payload')

        normalized_options = self._normalize_options(options_data)
        normalized_variants = self._normalize_variants(variants_data)

        self._validate_configuration(
            normalized_options,
            normalized_variants,
            cleaned_data.get('is_configurable', False),
        )

        cleaned_data['parsed_options'] = normalized_options
        cleaned_data['parsed_variants'] = normalized_variants
        return cleaned_data

    def _parse_payload(self, field_name):
        raw_value = (self.cleaned_data.get(field_name) or '').strip()
        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            raise forms.ValidationError(f'Invalid {field_name} payload.')
        if not isinstance(parsed, list):
            raise forms.ValidationError(f'Invalid {field_name} payload.')
        return parsed

    def _normalize_options(self, options_data):
        normalized = []
        for option_index, option in enumerate(options_data, start=1):
            if not isinstance(option, dict):
                raise forms.ValidationError('Invalid option data.')

            option_name = str(option.get('name', '')).strip()
            client_key = str(option.get('client_key') or f'option-{option_index}')
            values = option.get('values') or []

            normalized_values = []
            for value_index, value in enumerate(values, start=1):
                if not isinstance(value, dict):
                    raise forms.ValidationError('Invalid option value data.')
                value_label = str(value.get('value', '')).strip()
                value_key = str(value.get('client_key') or f'{client_key}-value-{value_index}')
                normalized_values.append({
                    'id': self._normalize_int(value.get('id')),
                    'client_key': value_key,
                    'value': value_label,
                    'price_delta': self._normalize_decimal(value.get('price_delta', '0')),
                    'display_image_url': str(value.get('display_image_url', '')).strip(),
                })

            normalized.append({
                'id': self._normalize_int(option.get('id')),
                'client_key': client_key,
                'name': option_name,
                'values': normalized_values,
            })
        return normalized

    def _normalize_variants(self, variants_data):
        normalized = []
        for variant_index, variant in enumerate(variants_data, start=1):
            if not isinstance(variant, dict):
                raise forms.ValidationError('Invalid SKU data.')
            selection_keys = variant.get('selection_keys') or []
            if not isinstance(selection_keys, list):
                raise forms.ValidationError('Invalid SKU configuration data.')
            normalized.append({
                'id': self._normalize_int(variant.get('id')),
                'sku': str(variant.get('sku', '')).strip(),
                'inventory_status': str(variant.get('inventory_status', 'in_stock')).strip(),
                'is_default': bool(variant.get('is_default')),
                'selection_keys': [str(key).strip() for key in selection_keys if str(key).strip()],
                'client_key': str(variant.get('client_key') or f'variant-{variant_index}'),
            })
        return normalized

    def _validate_configuration(self, options_data, variants_data, is_configurable):
        if not variants_data:
            raise forms.ValidationError('At least one SKU is required.')

        default_count = sum(1 for variant in variants_data if variant['is_default'])
        if default_count > 1:
            raise forms.ValidationError('Only one SKU can be marked as default.')

        inventory_choices = {choice[0] for choice in ProductVariant.INVENTORY_STATUS_CHOICES}
        existing_variant_qs = ProductVariant.objects.all()
        if self.instance.pk:
            existing_variant_qs = existing_variant_qs.exclude(product=self.instance)
        existing_skus = set(existing_variant_qs.values_list('sku', flat=True))

        seen_skus = set()
        for variant in variants_data:
            if not variant['sku']:
                raise forms.ValidationError('Each SKU row must include a SKU code.')
            sku_key = variant['sku'].lower()
            if sku_key in seen_skus:
                raise forms.ValidationError(f'Duplicate SKU in form: {variant["sku"]}.')
            seen_skus.add(sku_key)
            if variant['sku'] in existing_skus:
                raise forms.ValidationError(f'SKU already exists: {variant["sku"]}.')
            if variant['inventory_status'] not in inventory_choices:
                raise forms.ValidationError(f'Invalid inventory status for SKU {variant["sku"]}.')

        if not is_configurable:
            if options_data:
                raise forms.ValidationError('Simple products cannot define options. Disable the options or mark the product configurable.')
            if len(variants_data) != 1:
                raise forms.ValidationError('A simple product must have exactly one SKU.')
            for variant in variants_data:
                if variant['selection_keys']:
                    raise forms.ValidationError('Simple product SKUs cannot include option selections.')
            return

        if not options_data:
            raise forms.ValidationError('A configurable product must define at least one option.')

        option_names = set()
        value_key_to_option = {}
        option_count = len(options_data)

        for option in options_data:
            if not option['name']:
                raise forms.ValidationError('Each option needs a name.')
            option_key = option['name'].lower()
            if option_key in option_names:
                raise forms.ValidationError(f'Duplicate option name: {option["name"]}.')
            option_names.add(option_key)

            if not option['values']:
                raise forms.ValidationError(f'Option "{option["name"]}" must have at least one value.')

            seen_values = set()
            for value in option['values']:
                if not value['value']:
                    raise forms.ValidationError(f'Option "{option["name"]}" has a blank value.')
                value_key = value['value'].lower()
                if value_key in seen_values:
                    raise forms.ValidationError(f'Duplicate value "{value["value"]}" in option "{option["name"]}".')
                seen_values.add(value_key)
                value_key_to_option[value['client_key']] = option['client_key']

        seen_signatures = set()
        for variant in variants_data:
            if len(variant['selection_keys']) != option_count:
                raise forms.ValidationError(
                    f'SKU {variant["sku"]} must select one value for each option.'
                )

            selected_option_keys = []
            for key in variant['selection_keys']:
                option_key = value_key_to_option.get(key)
                if not option_key:
                    raise forms.ValidationError(f'SKU {variant["sku"]} references an unknown option value.')
                selected_option_keys.append(option_key)

            if len(set(selected_option_keys)) != option_count:
                raise forms.ValidationError(
                    f'SKU {variant["sku"]} must select exactly one value from each option.'
                )

            signature = tuple(sorted(variant['selection_keys']))
            if signature in seen_signatures:
                raise forms.ValidationError('Each configurable SKU must map to a unique option combination.')
            seen_signatures.add(signature)

    def _normalize_int(self, value):
        if value in (None, '', 0, '0'):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise forms.ValidationError('Invalid identifier in product configuration.')

    def _normalize_decimal(self, value):
        try:
            return Decimal(str(value or '0')).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            raise forms.ValidationError('Invalid price delta in option value.')

    def _serialize_options(self, product):
        payload = []
        for option in product.options.prefetch_related('values').all():
            payload.append({
                'id': option.id,
                'client_key': f'option-{option.id}',
                'name': option.name,
                'values': [
                    {
                        'id': value.id,
                        'client_key': f'value-{value.id}',
                        'value': value.value,
                        'price_delta': str(value.price_delta),
                        'display_image_url': value.display_image_url,
                    }
                    for value in option.values.all()
                ],
            })
        return payload

    def _serialize_variants(self, product):
        payload = []
        variants = product.variants.prefetch_related('variant_values__option_value').all()
        for variant in variants:
            payload.append({
                'id': variant.id,
                'client_key': f'variant-{variant.id}',
                'sku': variant.sku,
                'inventory_status': variant.inventory_status,
                'is_default': variant.is_default,
                'selection_keys': [
                    f'value-{selection.option_value_id}'
                    for selection in variant.variant_values.all()
                ],
            })
        return payload


class ProductImageForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image_url'].required = False
        self.fields['image_file'].required = False
        self.fields['sort_order'].required = False
        self.fields['sort_order'].initial = ''

    class Meta:
        model = ProductImage
        fields = ['image_url', 'image_file', 'alt_text', 'sort_order']

    def clean(self):
        cleaned_data = super().clean()
        image_url = (cleaned_data.get('image_url') or '').strip()
        image_file = cleaned_data.get('image_file')
        alt_text = (cleaned_data.get('alt_text') or '').strip()
        sort_order = cleaned_data.get('sort_order')

        has_content = bool(image_url or image_file or alt_text or sort_order not in (None, ''))
        if has_content and not image_url and not image_file:
            self.add_error('image_url', 'Provide an image URL or upload a file.')
            self.add_error('image_file', 'Provide an image URL or upload a file.')

        if (image_url or image_file) and sort_order in (None, ''):
            cleaned_data['sort_order'] = 0

        return cleaned_data


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
