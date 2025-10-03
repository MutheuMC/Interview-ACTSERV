from rest_framework import serializers
from .models import (
    Form, FormVersion, FormField, ValidationRule,
    FormSubmission, FieldResponse, FileUpload, NotificationLog
)
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class ValidationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidationRule
        fields = [
            'id', 'rule_type', 'config', 'error_message', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class FormFieldSerializer(serializers.ModelSerializer):
    validation_rules = ValidationRuleSerializer(many=True, read_only=True)
    
    class Meta:
        model = FormField
        fields = [
            'id', 'name', 'label', 'field_type', 'order', 
            'config', 'validation_rules', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class FormVersionSerializer(serializers.ModelSerializer):
    fields = FormFieldSerializer(many=True, read_only=True)
    
    class Meta:
        model = FormVersion
        fields = [
            'id', 'version_number', 'schema_json', 
            'fields', 'created_at'
        ]
        read_only_fields = ['id', 'version_number', 'created_at']


class FormListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for form listings"""
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', 
        read_only=True
    )
    submission_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Form
        fields = [
            'id', 'name', 'description', 'is_active',
            'created_by_name', 'submission_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_submission_count(self, obj):
        if obj.current_version:
            return obj.current_version.submissions.count()
        return 0


class FormDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer with full form structure"""
    current_version = FormVersionSerializer(read_only=True)
    versions = FormVersionSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', 
        read_only=True
    )
    
    class Meta:
        model = Form
        fields = [
            'id', 'name', 'description', 'is_active',
            'notification_emails', 'webhook_url',
            'current_version', 'versions',
            'created_by', 'created_by_name',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class FormCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new forms"""
    fields = FormFieldSerializer(many=True, write_only=True)
    
    class Meta:
        model = Form
        fields = [
            'name', 'description', 'is_active',
            'notification_emails', 'webhook_url', 'fields'
        ]
    
    def create(self, validated_data):
        fields_data = validated_data.pop('fields', [])
        
        # Create form
        form = Form.objects.create(**validated_data)
        
        # Create initial version
        version = form.create_new_version()
        
        # Create fields
        for field_data in fields_data:
            FormField.objects.create(form_version=version, **field_data)
        
        # Update schema_json
        version.schema_json = self._build_schema_json(version)
        version.save()
        
        return form
    
    def _build_schema_json(self, version):
        """Build complete JSON schema from fields"""
        fields = version.fields.all()
        return {
            'fields': [
                {
                    'id': str(field.id),
                    'name': field.name,
                    'label': field.label,
                    'type': field.field_type,
                    'order': field.order,
                    'config': field.config,
                    'validation_rules': [
                        {
                            'type': rule.rule_type,
                            'config': rule.config,
                            'error_message': rule.error_message
                        }
                        for rule in field.validation_rules.all()
                    ]
                }
                for field in fields
            ]
        }


class FormUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating forms (creates new version)"""
    fields = FormFieldSerializer(many=True, write_only=True, required=False)
    
    class Meta:
        model = Form
        fields = [
            'name', 'description', 'is_active',
            'notification_emails', 'webhook_url', 'fields'
        ]
    
    def update(self, instance, validated_data):
        fields_data = validated_data.pop('fields', None)
        
        # Update form metadata
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # If fields updated, create new version
        if fields_data is not None:
            version = instance.create_new_version()
            
            # Create new fields
            for field_data in fields_data:
                FormField.objects.create(form_version=version, **field_data)
            
            # Update schema_json
            version.schema_json = self._build_schema_json(version)
            version.save()
        
        return instance
    
    def _build_schema_json(self, version):
        """Build complete JSON schema from fields"""
        fields = version.fields.all()
        return {
            'fields': [
                {
                    'id': str(field.id),
                    'name': field.name,
                    'label': field.label,
                    'type': field.field_type,
                    'order': field.order,
                    'config': field.config
                }
                for field in fields
            ]
        }


class FileUploadSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    
    class Meta:
        model = FileUpload
        fields = [
            'id', 'original_filename', 'file_size', 
            'mime_type', 'url', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class FieldResponseSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source='field.name', read_only=True)
    field_label = serializers.CharField(source='field.label', read_only=True)
    field_type = serializers.CharField(source='field.field_type', read_only=True)
    files = FileUploadSerializer(many=True, read_only=True)
    
    class Meta:
        model = FieldResponse
        fields = [
            'id', 'field', 'field_name', 'field_label', 
            'field_type', 'value', 'files'
        ]
        read_only_fields = ['id']


class FormSubmissionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for submission listings"""
    form_name = serializers.CharField(source='form_version.form.name', read_only=True)
    form_version_number = serializers.IntegerField(
        source='form_version.version_number', 
        read_only=True
    )
    submitted_by_name = serializers.CharField(
        source='submitted_by.get_full_name', 
        read_only=True
    )
    
    class Meta:
        model = FormSubmission
        fields = [
            'id', 'form_name', 'form_version_number', 'status',
            'submitted_by', 'submitted_by_name',
            'submitted_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class FormSubmissionDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer with all responses"""
    form_version = FormVersionSerializer(read_only=True)
    field_responses = FieldResponseSerializer(many=True, read_only=True)
    submitted_by_name = serializers.CharField(
        source='submitted_by.get_full_name', 
        read_only=True
    )
    reviewed_by_name = serializers.CharField(
        source='reviewed_by.get_full_name', 
        read_only=True
    )
    
    class Meta:
        model = FormSubmission
        fields = [
            'id', 'form_version', 'status', 'field_responses',
            'submitted_by', 'submitted_by_name',
            'submitted_at', 'reviewed_by', 'reviewed_by_name',
            'reviewed_at', 'review_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'submitted_by', 'submitted_at', 
            'created_at', 'updated_at'
        ]


class FormSubmissionCreateSerializer(serializers.Serializer):
    """Serializer for creating form submissions"""
    form_id = serializers.UUIDField()
    responses = serializers.DictField(
        child=serializers.JSONField(),
        help_text="Dictionary of field_name: value pairs"
    )
    status = serializers.ChoiceField(
        choices=['draft', 'submitted'],
        default='submitted'
    )
    
    def validate_form_id(self, value):
        """Ensure form exists and is active"""
        try:
            form = Form.objects.get(id=value, is_active=True)
            if not form.current_version:
                raise serializers.ValidationError("Form has no active version")
            return value
        except Form.DoesNotExist:
            raise serializers.ValidationError("Form not found or inactive")
    
    def validate(self, data):
        """Validate responses against form schema"""
        form = Form.objects.get(id=data['form_id'])
        version = form.current_version
        
        # Get all fields
        fields = {field.name: field for field in version.fields.all()}
        responses = data['responses']
        
        # Validate required fields
        for field_name, field in fields.items():
            is_required = field.config.get('required', False)
            
            if is_required and field_name not in responses:
                raise serializers.ValidationError(
                    f"Field '{field.label}' is required"
                )
            
            # Validate field-specific rules
            if field_name in responses:
                self._validate_field_value(
                    field, 
                    responses[field_name]
                )
        
        return data
    
    def _validate_field_value(self, field, value):
        """Validate individual field value"""
        config = field.config
        
        # Text validations
        if field.field_type in ['text', 'textarea', 'email']:
            if not isinstance(value, str):
                raise serializers.ValidationError(
                    f"{field.label}: Expected text value"
                )
            
            min_length = config.get('min_length')
            max_length = config.get('max_length')
            
            if min_length and len(value) < min_length:
                raise serializers.ValidationError(
                    f"{field.label}: Minimum length is {min_length}"
                )
            
            if max_length and len(value) > max_length:
                raise serializers.ValidationError(
                    f"{field.label}: Maximum length is {max_length}"
                )
        
        # Number validations
        if field.field_type == 'number':
            if not isinstance(value, (int, float)):
                raise serializers.ValidationError(
                    f"{field.label}: Expected number value"
                )
            
            min_value = config.get('min_value')
            max_value = config.get('max_value')
            
            if min_value is not None and value < min_value:
                raise serializers.ValidationError(
                    f"{field.label}: Minimum value is {min_value}"
                )
            
            if max_value is not None and value > max_value:
                raise serializers.ValidationError(
                    f"{field.label}: Maximum value is {max_value}"
                )
        
        # Select validations
        if field.field_type in ['select', 'radio']:
            options = config.get('options', [])
            if value not in options:
                raise serializers.ValidationError(
                    f"{field.label}: Invalid option selected"
                )
        
        # Multi-select validations
        if field.field_type == 'multi_select':
            if not isinstance(value, list):
                raise serializers.ValidationError(
                    f"{field.label}: Expected list of values"
                )
            options = config.get('options', [])
            for v in value:
                if v not in options:
                    raise serializers.ValidationError(
                        f"{field.label}: Invalid option '{v}'"
                    )
    
    def create(self, validated_data):
        """Create submission with field responses"""
        form = Form.objects.get(id=validated_data['form_id'])
        version = form.current_version
        user = self.context['request'].user
        
        # Create submission
        submission = FormSubmission.objects.create(
            form_version=version,
            submitted_by=user,
            status=validated_data['status']
        )
        
        if validated_data['status'] == 'submitted':
            submission.submitted_at = timezone.now()
            submission.save()
        
        # Create field responses
        fields = {field.name: field for field in version.fields.all()}
        
        for field_name, value in validated_data['responses'].items():
            if field_name in fields:
                FieldResponse.objects.create(
                    submission=submission,
                    field=fields[field_name],
                    value=value
                )
        
        return submission


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = [
            'id', 'channel', 'recipient', 'status', 
            'attempts', 'error_message', 'sent_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']