# Generated by Django 5.0.2 on 2024-08-30 21:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('devices', '0006_rename_value_device_default_value_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='device',
            name='max_value',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='device',
            name='min_value',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
