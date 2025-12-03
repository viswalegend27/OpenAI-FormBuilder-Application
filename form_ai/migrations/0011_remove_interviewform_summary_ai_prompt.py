from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("form_ai", "0010_remove_interviewform_role"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="interviewform",
            name="summary",
        ),
        migrations.RemoveField(
            model_name="interviewform",
            name="ai_prompt",
        ),
    ]

