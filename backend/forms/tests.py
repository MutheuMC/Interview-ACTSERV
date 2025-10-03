from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
import uuid

from .models import (
    Form, FormVersion, FormField, ValidationRule,
    FormSubmission, FieldResponse, FileUpload, NotificationLog
)
from .tasks import send_submission_notification, send_email_notification

User = get_user_model()


class FormModelTest(TestCase):
    """Test Form model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    def test_create_form(self):
        """Test creating a form"""
        form = Form.objects.create(
            name='KYC Form',
            description='Know Your Customer form',
            created_by=self.user
        )
        
        self.assertEqual(form.name, 'KYC Form')
        self.assertTrue(form.is_active)
        self.assertEqual(str(form), 'KYC Form')
    
    def test_create_new_version(self):
        """Test creating a new form version"""
        form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
        
        version1 = form.create_new_version()
        self.assertEqual(version1.version_number, 1)
        self.assertEqual(form.current_version, version1)
        
        version2 = form.create_new_version()
        self.assertEqual(version2.version_number, 2)
        self.assertEqual(form.current_version, version2)


class FormFieldModelTest(TestCase):
    """Test FormField model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
        self.version = self.form.create_new_version()
    
    def test_create_field(self):
        """Test creating a form field"""
        field = FormField.objects.create(
            form_version=self.version,
            name='full_name',
            label='Full Name',
            field_type='text',
            order=1,
            config={'required': True, 'max_length': 100}
        )
        
        self.assertEqual(field.name, 'full_name')
        self.assertEqual(field.field_type, 'text')
        self.assertTrue(field.config['required'])
    
    def test_unique_field_names_per_version(self):
        """Test that field names are unique per version"""
        FormField.objects.create(
            form_version=self.version,
            name='email',
            label='Email',
            field_type='email',
            order=1
        )
        
        # Creating duplicate field name should fail
        with self.assertRaises(Exception):
            FormField.objects.create(
                form_version=self.version,
                name='email',
                label='Email 2',
                field_type='email',
                order=2
            )


class FormSubmissionModelTest(TestCase):
    """Test FormSubmission model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
        self.version = self.form.create_new_version()
    
    def test_create_submission(self):
        """Test creating a form submission"""
        submission = FormSubmission.objects.create(
            form_version=self.version,
            submitted_by=self.user,
            status='submitted'
        )
        
        self.assertEqual(submission.status, 'submitted')
        self.assertEqual(submission.submitted_by, self.user)


class FormAPITest(APITestCase):
    """Test Form API endpoints"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True
        )
        
        # Create regular user
        self.regular_user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123'
        )
    
    def test_list_forms_authenticated(self):
        """Test listing forms as authenticated user"""
        self.client.force_authenticate(user=self.regular_user)
        
        # Create test form
        form = Form.objects.create(
            name='Test Form',
            created_by=self.admin_user,
            is_active=True
        )
        
        response = self.client.get('/api/forms/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
    
    def test_list_forms_unauthenticated(self):
        """Test listing forms without authentication"""
        response = self.client.get('/api/forms/')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    
    def test_create_form_as_admin(self):
        """Test creating a form as admin"""
        self.client.force_authenticate(user=self.admin_user)
        
        data = {
            'name': 'New Form',
            'description': 'Test description',
            'is_active': True,
            'fields': [
                {
                    'name': 'full_name',
                    'label': 'Full Name',
                    'field_type': 'text',
                    'order': 1,
                    'config': {'required': True}
                },
                {
                    'name': 'email',
                    'label': 'Email Address',
                    'field_type': 'email',
                    'order': 2,
                    'config': {'required': True}
                }
            ]
        }
        
        response = self.client.post('/api/forms/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Form.objects.count(), 1)
        
        form = Form.objects.first()
        self.assertEqual(form.name, 'New Form')
        self.assertEqual(form.current_version.fields.count(), 2)
    
    def test_create_form_as_regular_user(self):
        """Test that regular users cannot create forms"""
        self.client.force_authenticate(user=self.regular_user)
        
        data = {
            'name': 'New Form',
            'description': 'Test description',
            'is_active': True,
            'fields': []
        }
        
        response = self.client.post('/api/forms/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_get_form_schema(self):
        """Test getting form schema"""
        self.client.force_authenticate(user=self.regular_user)
        
        form = Form.objects.create(
            name='Test Form',
            created_by=self.admin_user
        )
        version = form.create_new_version()
        
        FormField.objects.create(
            form_version=version,
            name='full_name',
            label='Full Name',
            field_type='text',
            order=1,
            config={'required': True}
        )
        
        response = self.client.get(f'/api/forms/{form.id}/schema/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['fields']), 1)
        self.assertEqual(response.data['fields'][0]['name'], 'full_name')



class FormSubmissionAPITest(APITestCase):
    """Test FormSubmission API endpoints"""
    
    def setUp(self):
        self.client = APIClient()
        
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123'
        )
        
        # Create form with fields
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
        self.version = self.form.create_new_version()
        
        self.name_field = FormField.objects.create(
            form_version=self.version,
            name='full_name',
            label='Full Name',
            field_type='text',
            order=1,
            config={'required': True}
        )
        
        self.email_field = FormField.objects.create(
            form_version=self.version,
            name='email',
            label='Email',
            field_type='email',
            order=2,
            config={'required': True}
        )
    
    @patch('forms.tasks.send_submission_notification.delay')
    def test_create_submission(self, mock_task):
        """Test creating a form submission"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'form_id': str(self.form.id),
            'responses': {
                'full_name': 'John Doe',
                'email': 'john@example.com'
            },
            'status': 'submitted'
        }
        
        response = self.client.post('/api/submissions/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(FormSubmission.objects.count(), 1)
        
        submission = FormSubmission.objects.first()
        self.assertEqual(submission.status, 'submitted')
        self.assertEqual(submission.field_responses.count(), 2)
        
        # Check that notification task was called
        mock_task.assert_called_once()
    
    def test_create_submission_missing_required_field(self):
        """Test creating submission with missing required field"""
        self.client.force_authenticate(user=self.user)
        
        data = {
            'form_id': str(self.form.id),
            'responses': {
                'full_name': 'John Doe'
                # Missing required email field
            },
            'status': 'submitted'
        }
        
        response = self.client.post('/api/submissions/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_create_submission_inactive_form(self):
        """Test creating submission for inactive form"""
        self.client.force_authenticate(user=self.user)
        
        self.form.is_active = False
        self.form.save()
        
        data = {
            'form_id': str(self.form.id),
            'responses': {
                'full_name': 'John Doe',
                'email': 'john@example.com'
            },
            'status': 'submitted'
        }
        
        response = self.client.post('/api/submissions/', data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_list_own_submissions(self):
        """Test that users can only see their own submissions"""
        other_user = User.objects.create_user(
            username='other',
            email='other@example.com',
            password='otherpass123'
        )
        
        # Create submissions for both users
        FormSubmission.objects.create(
            form_version=self.version,
            submitted_by=self.user,
            status='submitted'
        )
        
        FormSubmission.objects.create(
            form_version=self.version,
            submitted_by=other_user,
            status='submitted'
        )
        
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/submissions/')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]['submitted_by'],
            self.user.id
        )


class ValidationTest(TestCase):
    """Test validation logic"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123'
        )
        
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
        self.version = self.form.create_new_version()
    
    def test_text_min_max_length(self):
        """Test text field min/max length validation"""
        field = FormField.objects.create(
            form_version=self.version,
            name='description',
            label='Description',
            field_type='text',
            order=1,
            config={
                'required': True,
                'min_length': 10,
                'max_length': 100
            }
        )
        
        # Valid value
        from forms.serializers import FormSubmissionCreateSerializer
        
        serializer = FormSubmissionCreateSerializer(data={
            'form_id': str(self.form.id),
            'responses': {
                'description': 'This is a valid description'
            },
            'status': 'draft'
        }, context={'request': MagicMock(user=self.user)})
        
        self.assertTrue(serializer.is_valid())
        
        # Too short
        serializer = FormSubmissionCreateSerializer(data={
            'form_id': str(self.form.id),
            'responses': {
                'description': 'Short'
            },
            'status': 'draft'
        }, context={'request': MagicMock(user=self.user)})
        
        self.assertFalse(serializer.is_valid())
    
    def test_number_min_max_value(self):
        """Test number field min/max value validation"""
        field = FormField.objects.create(
            form_version=self.version,
            name='age',
            label='Age',
            field_type='number',
            order=1,
            config={
                'required': True,
                'min_value': 18,
                'max_value': 100
            }
        )
        
        from forms.serializers import FormSubmissionCreateSerializer
        
        # Valid value
        serializer = FormSubmissionCreateSerializer(data={
            'form_id': str(self.form.id),
            'responses': {
                'age': 25
            },
            'status': 'draft'
        }, context={'request': MagicMock(user=self.user)})
        
        self.assertTrue(serializer.is_valid())
        
        # Too low
        serializer = FormSubmissionCreateSerializer(data={
            'form_id': str(self.form.id),
            'responses': {
                'age': 15
            },
            'status': 'draft'
        }, context={'request': MagicMock(user=self.user)})
        
        self.assertFalse(serializer.is_valid())



class NotificationTest(TestCase):
    """Test notification functionality"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123'
        )
        
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user,
            notification_emails=['admin@example.com']
        )
        self.version = self.form.create_new_version()
        
        self.submission = FormSubmission.objects.create(
            form_version=self.version,
            submitted_by=self.user,
            status='submitted'
        )
    
    @patch('forms.tasks.send_mail')
    def test_email_notification(self, mock_send_mail):
        """Test email notification is sent"""
        send_email_notification(
            self.submission,
            ['admin@example.com']
        )
        
        # Check that email was sent
        mock_send_mail.assert_called_once()
        
        # Check notification log was created
        self.assertEqual(NotificationLog.objects.count(), 1)
        log = NotificationLog.objects.first()
        self.assertEqual(log.channel, 'email')
        self.assertEqual(log.status, 'sent')
    
    @patch('forms.tasks.send_email_notification')
    @patch('forms.tasks.send_webhook_notification')
    def test_submission_notification_task(self, mock_webhook, mock_email):
        """Test submission notification task"""
        send_submission_notification(str(self.submission.id))
        
        # Check that both notification methods were called
        mock_email.assert_called_once()


class FormVersioningTest(TestCase):
    """Test form versioning"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='user',
            email='user@example.com',
            password='userpass123'
        )
        
        self.form = Form.objects.create(
            name='Test Form',
            created_by=self.user
        )
    
    def test_version_incrementing(self):
        """Test that versions increment correctly"""
        v1 = self.form.create_new_version()
        v2 = self.form.create_new_version()
        v3 = self.form.create_new_version()
        
        self.assertEqual(v1.version_number, 1)
        self.assertEqual(v2.version_number, 2)
        self.assertEqual(v3.version_number, 3)
        self.assertEqual(self.form.current_version, v3)
    
    def test_old_submissions_link_to_old_version(self):
        """Test that old submissions keep their version"""
        v1 = self.form.create_new_version()
        
        # Create submission with v1
        submission1 = FormSubmission.objects.create(
            form_version=v1,
            submitted_by=self.user,
            status='submitted'
        )
        
        # Create new version
        v2 = self.form.create_new_version()
        
        # Old submission still links to v1
        submission1.refresh_from_db()
        self.assertEqual(submission1.form_version, v1)
        self.assertEqual(submission1.form_version.version_number, 1)