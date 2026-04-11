from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0007_product_chat_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='productchatsession',
            name='intro_generated',
            field=models.BooleanField(default=False),
        ),
    ]
