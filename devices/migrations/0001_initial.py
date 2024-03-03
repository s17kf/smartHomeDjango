# Generated by Django 5.0.2 on 2024-03-03 22:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='Device',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('type', models.CharField(choices=[('SW', 'Switch'), ('PWM', 'PWM regulator')], max_length=10)),
                ('address', models.CharField(max_length=100, verbose_name='HW address')),
                ('location', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='devices.location')),
            ],
        ),
    ]
