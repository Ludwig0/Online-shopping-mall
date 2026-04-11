from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0005_product_id_fixed_8_digits'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productimage',
            name='image_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name='productimage',
            name='image_file',
            field=models.FileField(blank=True, upload_to='product_images/'),
        ),
    ]
