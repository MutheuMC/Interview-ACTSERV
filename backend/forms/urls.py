from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FormViewSet, FormSubmissionViewSet, FileUploadViewSet

router = DefaultRouter()
router.register(r'forms', FormViewSet, basename='form')
router.register(r'submissions', FormSubmissionViewSet, basename='submission')
router.register(r'files', FileUploadViewSet, basename='file')

urlpatterns = [
    path('', include(router.urls)),
]