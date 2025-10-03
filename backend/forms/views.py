from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Q, Count

from .models import (
    Form, FormVersion, FormSubmission, 
    FieldResponse, FileUpload
)
from .serializers import (
    FormListSerializer, FormDetailSerializer,
    FormCreateSerializer, FormUpdateSerializer,
    FormVersionSerializer, FormSubmissionListSerializer,
    FormSubmissionDetailSerializer, FormSubmissionCreateSerializer,
    FileUploadSerializer
)
from .tasks import send_submission_notification
from .permissions import IsAdminOrReadOnly


class FormViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing forms
    
    Admin users can create, update, delete
    Regular users can only view active forms
    """
    queryset = Form.objects.all()
    permission_classes = [IsAuthenticated, IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return FormListSerializer
        elif self.action == 'create':
            return FormCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return FormUpdateSerializer
        return FormDetailSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Non-admin users only see active forms
        if not self.request.user.is_staff:
            queryset = queryset.filter(is_active=True)
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Get all versions of a form"""
        form = self.get_object()
        versions = form.versions.all()
        serializer = FormVersionSerializer(versions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def schema(self, request, pk=None):
        """Get form schema (for client-side rendering)"""
        form = self.get_object()
        if not form.current_version:
            return Response(
                {'error': 'Form has no active version'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = FormVersionSerializer(form.current_version)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplicate an existing form"""
        original_form = self.get_object()
        
        # Create new form
        new_form = Form.objects.create(
            name=f"{original_form.name} (Copy)",
            description=original_form.description,
            created_by=request.user,
            is_active=False
        )
        
        # Create new version
        new_version = new_form.create_new_version()
        
        # Copy fields from original
        if original_form.current_version:
            original_fields = original_form.current_version.fields.all()
            for field in original_fields:
                FormField.objects.create(
                    form_version=new_version,
                    name=field.name,
                    label=field.label,
                    field_type=field.field_type,
                    order=field.order,
                    config=field.config
                )
        
        serializer = FormDetailSerializer(new_form)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['get'])
    def submissions(self, request, pk=None):
        """Get all submissions for a form"""
        form = self.get_object()
        submissions = FormSubmission.objects.filter(
            form_version__form=form
        ).select_related('form_version', 'submitted_by')
        
        # Filter by status if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            submissions = submissions.filter(status=status_filter)
        
        # Pagination
        page = self.paginate_queryset(submissions)
        if page is not None:
            serializer = FormSubmissionListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = FormSubmissionListSerializer(submissions, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        """Get analytics for a form"""
        form = self.get_object()
        
        submissions = FormSubmission.objects.filter(
            form_version__form=form
        )
        
        analytics = {
            'total_submissions': submissions.count(),
            'by_status': dict(
                submissions.values('status').annotate(
                    count=Count('id')
                ).values_list('status', 'count')
            ),
            'recent_submissions': FormSubmissionListSerializer(
                submissions.order_by('-created_at')[:10],
                many=True
            ).data
        }
        
        return Response(analytics)


class FormSubmissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for form submissions
    
    Users can create and view their own submissions
    Admins can view and update all submissions
    """
    queryset = FormSubmission.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'form_version__form']
    ordering_fields = ['created_at', 'submitted_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return FormSubmissionListSerializer
        elif self.action == 'create':
            return FormSubmissionCreateSerializer
        return FormSubmissionDetailSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Non-admin users only see their own submissions
        if not self.request.user.is_staff:
            queryset = queryset.filter(submitted_by=self.request.user)
        
        return queryset.select_related(
            'form_version__form',
            'submitted_by',
            'reviewed_by'
        ).prefetch_related(
            'field_responses__field',
            'field_responses__files'
        )
    
    def perform_create(self, serializer):
        submission = serializer.save()
        
        # Trigger async notification if status is submitted
        if submission.status == 'submitted':
            send_submission_notification.delay(str(submission.id))
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit a draft submission"""
        submission = self.get_object()
        
        # Check permission
        if submission.submitted_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if submission.status != 'draft':
            return Response(
                {'error': 'Only draft submissions can be submitted'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update status
        submission.status = 'submitted'
        submission.submitted_at = timezone.now()
        submission.save()
        
        # Trigger notification
        send_submission_notification.delay(str(submission.id))
        
        serializer = self.get_serializer(submission)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAdminUser])
    def review(self, request, pk=None):
        """Review a submission (admin only)"""
        submission = self.get_object()
        
        new_status = request.data.get('status')
        review_notes = request.data.get('review_notes', '')
        
        if new_status not in ['under_review', 'approved', 'rejected']:
            return Response(
                {'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        submission.status = new_status
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.review_notes = review_notes
        submission.save()
        
        serializer = self.get_serializer(submission)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        """Export submission data as JSON"""
        submission = self.get_object()
        serializer = self.get_serializer(submission)
        return Response(serializer.data)
    


class FileUploadViewSet(viewsets.ModelViewSet):
    """
    ViewSet for file uploads
    Handles multipart file uploads for form submissions
    """
    queryset = FileUpload.objects.all()
    serializer_class = FileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Users can only see files from their submissions
        if not self.request.user.is_staff:
            queryset = queryset.filter(
                field_response__submission__submitted_by=self.request.user
            )
        
        return queryset
    
    def create(self, request, *args, **kwargs):
        """
        Upload a file for a field response
        
        Required fields:
        - field_response_id: UUID of the field response
        - file: The file to upload
        """
        field_response_id = request.data.get('field_response_id')
        file_obj = request.FILES.get('file')
        
        if not field_response_id or not file_obj:
            return Response(
                {'error': 'field_response_id and file are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate field response exists and user has permission
        try:
            field_response = FieldResponse.objects.select_related(
                'submission', 'field'
            ).get(id=field_response_id)
            
            # Check permission
            if (field_response.submission.submitted_by != request.user and 
                not request.user.is_staff):
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Validate field type
            if field_response.field.field_type not in ['file', 'multi_file']:
                return Response(
                    {'error': 'Field does not support file uploads'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate file size
            max_size_mb = field_response.field.config.get('max_size_mb', 10)
            max_size_bytes = max_size_mb * 1024 * 1024
            
            if file_obj.size > max_size_bytes:
                return Response(
                    {'error': f'File size exceeds {max_size_mb}MB limit'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate file type
            accept = field_response.field.config.get('accept', '')
            if accept:
                allowed_types = [t.strip() for t in accept.split(',')]
                if not any(file_obj.name.endswith(t.replace('*', '')) 
                          for t in allowed_types):
                    return Response(
                        {'error': f'File type not allowed. Accepted: {accept}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Validate max files for multi_file
            if field_response.field.field_type == 'multi_file':
                max_files = field_response.field.config.get('max_files', 5)
                current_count = field_response.files.count()
                
                if current_count >= max_files:
                    return Response(
                        {'error': f'Maximum {max_files} files allowed'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Create file upload
            file_upload = FileUpload.objects.create(
                field_response=field_response,
                file=file_obj,
                original_filename=file_obj.name,
                file_size=file_obj.size,
                mime_type=file_obj.content_type
            )
            
            serializer = self.get_serializer(file_upload)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except FieldResponse.DoesNotExist:
            return Response(
                {'error': 'Field response not found'},
                status=status.HTTP_404_NOT_FOUND
            )