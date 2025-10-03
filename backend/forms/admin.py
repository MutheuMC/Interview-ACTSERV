from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Form, FormVersion, FormField, ValidationRule,
    FormSubmission, FieldResponse, FileUpload, NotificationLog
)


@admin.register(Form)
class FormAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_by', 'submission_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'is_active', 'created_by')
        }),
        ('Notifications', {
            'fields': ('notification_emails', 'webhook_url')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def submission_count(self, obj):
        if obj.current_version:
            count = obj.current_version.submissions.count()
            return format_html(
                '<span style="font-weight: bold; color: #059669;">{}</span>',
                count
            )
        return 0
    submission_count.short_description = 'Submissions'


@admin.register(FormVersion)
class FormVersionAdmin(admin.ModelAdmin):
    list_display = ['form', 'version_number', 'field_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['form__name']
    readonly_fields = ['id', 'schema_json', 'created_at', 'updated_at']
    
    def field_count(self, obj):
        return obj.fields.count()
    field_count.short_description = 'Fields'


@admin.register(FormField)
class FormFieldAdmin(admin.ModelAdmin):
    list_display = ['label', 'name', 'field_type', 'form_version', 'order', 'is_required']
    list_filter = ['field_type', 'form_version__form']
    search_fields = ['name', 'label']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['form_version', 'order']
    
    def is_required(self, obj):
        required = obj.config.get('required', False)
        if required:
            return format_html(
                '<span style="color: #DC2626; font-weight: bold;">✓</span>'
            )
        return format_html('<span style="color: #9CA3AF;">—</span>')
    is_required.short_description = 'Required'


@admin.register(ValidationRule)
class ValidationRuleAdmin(admin.ModelAdmin):
    list_display = ['field', 'rule_type', 'error_message', 'created_at']
    list_filter = ['rule_type']
    search_fields = ['field__name', 'error_message']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'form_name', 'status_badge', 'submitted_by', 
        'submitted_at', 'created_at'
    ]
    list_filter = ['status', 'submitted_at', 'created_at']
    search_fields = ['id', 'submitted_by__email', 'form_version__form__name']
    readonly_fields = [
        'id', 'form_version', 'submitted_by', 'submitted_at', 
        'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Submission Information', {
            'fields': (
                'id', 'form_version', 'submitted_by', 
                'status', 'submitted_at'
            )
        }),
        ('Review', {
            'fields': ('reviewed_by', 'reviewed_at', 'review_notes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def form_name(self, obj):
        return obj.form_version.form.name
    form_name.short_description = 'Form'
    
    def status_badge(self, obj):
        colors = {
            'draft': '#6B7280',
            'submitted': '#2563EB',
            'under_review': '#F59E0B',
            'approved': '#059669',
            'rejected': '#DC2626',
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 4px; font-size: 11px; font-weight: 600;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def has_add_permission(self, request):
        # Submissions should be created through the API
        return False


@admin.register(FieldResponse)
class FieldResponseAdmin(admin.ModelAdmin):
    list_display = ['submission', 'field_name', 'field_type', 'has_value', 'file_count']
    list_filter = ['field__field_type']
    search_fields = ['submission__id', 'field__name']
    readonly_fields = ['id', 'submission', 'field', 'value', 'created_at', 'updated_at']
    
    def field_name(self, obj):
        return obj.field.label
    field_name.short_description = 'Field'
    
    def field_type(self, obj):
        return obj.field.field_type
    field_type.short_description = 'Type'
    
    def has_value(self, obj):
        if obj.value:
            return format_html('<span style="color: #059669;">✓</span>')
        return format_html('<span style="color: #9CA3AF;">—</span>')
    has_value.short_description = 'Value'
    
    def file_count(self, obj):
        count = obj.files.count()
        if count > 0:
            return format_html(
                '<span style="font-weight: bold; color: #2563EB;">{}</span>',
                count
            )
        return '—'
    file_count.short_description = 'Files'
    
    def has_add_permission(self, request):
        return False


@admin.register(FileUpload)
class FileUploadAdmin(admin.ModelAdmin):
    list_display = ['original_filename', 'mime_type', 'file_size_display', 'created_at']
    list_filter = ['mime_type', 'created_at']
    search_fields = ['original_filename', 'field_response__submission__id']
    readonly_fields = [
        'id', 'field_response', 'file', 'original_filename', 
        'file_size', 'mime_type', 'created_at', 'updated_at'
    ]
    
    def file_size_display(self, obj):
        size_mb = obj.file_size / (1024 * 1024)
        if size_mb < 1:
            size_kb = obj.file_size / 1024
            return f"{size_kb:.1f} KB"
        return f"{size_mb:.1f} MB"
    file_size_display.short_description = 'Size'
    
    def has_add_permission(self, request):
        return False


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = [
        'channel', 'recipient', 'status_badge', 
        'attempts', 'sent_at', 'created_at'
    ]
    list_filter = ['channel', 'status', 'created_at']
    search_fields = ['recipient', 'submission__id']
    readonly_fields = [
        'id', 'submission', 'channel', 'recipient', 
        'status', 'attempts', 'error_message', 
        'sent_at', 'created_at', 'updated_at'
    ]
    
    def status_badge(self, obj):
        colors = {
            'pending': '#F59E0B',
            'sent': '#059669',
            'failed': '#DC2626',
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 4px; font-size: 11px; font-weight: 600;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def has_add_permission(self, request):
        return False


# Customize admin site
admin.site.site_header = 'Dynamic Onboarding Forms Administration'
admin.site.site_title = 'Forms Admin'
admin.site.index_title = 'Welcome to Forms Administration'