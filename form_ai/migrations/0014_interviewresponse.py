from django.db import migrations, models


def copy_extracted(apps, schema_editor):
    VoiceConversation = apps.get_model("form_ai", "VoiceConversation")
    InterviewResponse = apps.get_model("form_ai", "InterviewResponse")

    for convo in VoiceConversation.objects.all():
        data = getattr(convo, "extracted_info", None) or {}
        if not data:
            continue
        InterviewResponse.objects.update_or_create(
            conversation=convo,
            defaults={
                "interview_form": convo.interview_form,
                "data": data,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("form_ai", "0013_delete_assessment_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="InterviewResponse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "conversation",
                    models.OneToOneField(
                        on_delete=models.CASCADE,
                        related_name="interview_response",
                        to="form_ai.voiceconversation",
                    ),
                ),
                (
                    "interview_form",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="responses",
                        blank=True,
                        null=True,
                        to="form_ai.interviewform",
                    ),
                ),
            ],
            options={
                "db_table": "interview_responses",
            },
        ),
        migrations.RunPython(copy_extracted, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="voiceconversation",
            name="extracted_info",
        ),
    ]

