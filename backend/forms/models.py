from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
import uuid

User = get_user_model()


class TimeStampedModel(models.Model):
    """Abstract base model with timestamp fields"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Form(TimeStampedModel):
    """Main form model - represents a form template"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='created_forms'
    )
    is_active = models.BooleanField(default=True)
    current_version = models.ForeignKey(
        'FormVersion',
        on_delete=models.SET_NULL,
        null=True,
        related_name='current_for_form'
    )
    
    # Notification settings
    notification_emails = ArrayField(
        models.EmailField(),
        default=list,
        blank=True,
        help_text="Email addresses to notify on submission"
    )
    webhook_url = models.URLField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
        ]

    def __str__(self):
        return self.name

    def create_new_version(self):
        """Create a new version when form is edited"""
        last_version = self.versions.order_by('-version_number').first()
        version_number = (last_version.version_number + 1) if last_version else 1
        
        new_version = FormVersion.objects.create(
            form=self,
            version_number=version_number
        )
        
        self.current_version = new_version
        self.save()
        
        return new_version


class FormVersion(TimeStampedModel):
    """Immutable snapshot of a form's structure at a point in time"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(Form, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    schema_json = models.JSONField(
        default=dict,
        help_text="Complete JSON schema of form structure"
    )
    
    class Meta:
        ordering = ['-version_number']
        unique_together = ['form', 'version_number']
        indexes = [
            models.Index(fields=['form', '-version_number']),
        ]

    def __str__(self):
        return f"{self.form.name} v{self.version_number}"


class FormField(TimeStampedModel):
    """Individual field in a form version"""
    
    FIELD_TYPES = [
        ('text', 'Text'),
        ('textarea', 'Text Area'),
        ('number', 'Number'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('date', 'Date'),
        ('select', 'Select Dropdown'),
        ('multi_select', 'Multi Select'),
        ('radio', 'Radio Buttons'),
        ('checkbox', 'Checkbox'),
        ('file', 'File Upload'),
        ('multi_file', 'Multiple File Upload'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_version = models.ForeignKey(
        FormVersion, 
        on_delete=models.CASCADE, 
        related_name='fields'
    )
    name = models.CharField(
        max_length=100,
        help_text="Field identifier (snake_case recommended)"
    )
    label = models.CharField(max_length=255)
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    order = models.PositiveIntegerField(default=0)
    
    # Field configuration stored as JSON
    config = models.JSONField(
        default=dict,
        help_text="""
        Configuration options:
        - required: bool
        - placeholder: str
        - help_text: str
        - default_value: any
        - min_length, max_length: int (text)
        - min_value, max_value: number (number)
        - options: list (select, radio, multi_select)
        - accept: str (file types)
        - max_files: int (multi_file)
        - max_size_mb: number (file)
        """
    )
    
    class Meta:
        ordering = ['order', 'created_at']
        unique_together = ['form_version', 'name']
        indexes = [
            models.Index(fields=['form_version', 'order']),
        ]

    def __str__(self):
        return f"{self.form_version} - {self.label}"


class ValidationRule(TimeStampedModel):
    """Validation rules for form fields"""
    
    RULE_TYPES = [
        ('required', 'Required'),
        ('min_length', 'Minimum Length'),
        ('max_length', 'Maximum Length'),
        ('pattern', 'Regex Pattern'),
        ('min_value', 'Minimum Value'),
        ('max_value', 'Maximum Value'),
        ('conditional', 'Conditional'),
        ('file_type', 'File Type'),
        ('file_size', 'File Size'),
        ('email', 'Email Format'),
        ('phone', 'Phone Format'),
        ('custom', 'Custom Validation'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field = models.ForeignKey(
        FormField, 
        on_delete=models.CASCADE, 
        related_name='validation_rules'
    )
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES)
    config = models.JSONField(
        default=dict,
        help_text="""
        Rule configuration based on type:
        - conditional: {condition: {...}, then: {...}}
        - pattern: {regex: str}
        - min_length/max_length: {value: int}
        - file_type: {allowed: [str]}
        - file_size: {max_mb: number}
        """
    )
    error_message = models.CharField(max_length=255)
    
    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.field.name} - {self.rule_type}"


class FormSubmission(TimeStampedModel):
    """A submission of a form by a client"""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_version = models.ForeignKey(
        FormVersion,
        on_delete=models.PROTECT,
        related_name='submissions',
        help_text="Links to specific form version for historical integrity"
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='form_submissions'
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='draft'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_submissions'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['submitted_by', '-created_at']),
            models.Index(fields=['form_version', '-created_at']),
        ]

    def __str__(self):
        return f"Submission {self.id} - {self.form_version.form.name}"


class FieldResponse(TimeStampedModel):
    """Response to a specific field in a submission"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        related_name='field_responses'
    )
    field = models.ForeignKey(
        FormField,
        on_delete=models.PROTECT,
        related_name='responses'
    )
    
    # JSONB field to support any data type
    value = models.JSONField(
        null=True,
        blank=True,
        help_text="Actual field value (text, number, array, etc.)"
    )
    
    class Meta:
        unique_together = ['submission', 'field']
        indexes = [
            models.Index(fields=['submission', 'field']),
        ]

    def __str__(self):
        return f"{self.submission.id} - {self.field.name}"


class FileUpload(TimeStampedModel):
    """File uploaded as part of a form submission"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field_response = models.ForeignKey(
        FieldResponse,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(upload_to='form_uploads/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="File size in bytes"
    )
    mime_type = models.CharField(max_length=100)
    
    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.original_filename


class NotificationLog(TimeStampedModel):
    """Log of notification attempts"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    
    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('webhook', 'Webhook'),
        ('slack', 'Slack'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        FormSubmission,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    recipient = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['submission', 'channel']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"{self.channel} to {self.recipient} - {self.status}"