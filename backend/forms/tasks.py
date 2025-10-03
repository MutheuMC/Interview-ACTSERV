from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
import requests
import logging

from .models import FormSubmission, NotificationLog

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=3600,  # 1 hour
)
def send_submission_notification(self, submission_id):
    """
    Send notification when a form is submitted
    
    This task is idempotent - can be safely retried
    Sends notifications via multiple channels:
    - Email
    - Webhook (if configured)
    """
    try:
        submission = FormSubmission.objects.select_related(
            'form_version__form',
            'submitted_by'
        ).get(id=submission_id)
        
        form = submission.form_version.form
        
        # Send email notifications
        if form.notification_emails:
            send_email_notification(submission, form.notification_emails)
        
        # Send webhook notification
        if form.webhook_url:
            send_webhook_notification(submission, form.webhook_url)
        
        logger.info(f"Successfully sent notifications for submission {submission_id}")
        
    except FormSubmission.DoesNotExist:
        logger.error(f"Submission {submission_id} not found")
        raise
    except Exception as e:
        logger.error(f"Error sending notification for {submission_id}: {str(e)}")
        # Log the failure
        NotificationLog.objects.create(
            submission_id=submission_id,
            channel='email',
            recipient='system',
            status='failed',
            error_message=str(e),
            attempts=self.request.retries + 1
        )
        raise


def send_email_notification(submission, recipients):
    """Send email notification about new submission"""
    form = submission.form_version.form
    
    for recipient in recipients:
        try:
            # Create notification log
            log = NotificationLog.objects.create(
                submission=submission,
                channel='email',
                recipient=recipient,
                status='pending'
            )
            
            # Prepare email context
            context = {
                'form_name': form.name,
                'submission_id': submission.id,
                'submitted_by': submission.submitted_by.get_full_name() or submission.submitted_by.email,
                'submitted_at': submission.submitted_at,
                'admin_url': f"{settings.FRONTEND_URL}/admin/submissions/{submission.id}",
            }
            
            # Render email templates
            html_message = render_to_string(
                'emails/submission_notification.html',
                context
            )
            plain_message = strip_tags(html_message)
            
            # Send email
            send_mail(
                subject=f'New Form Submission: {form.name}',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                html_message=html_message,
                fail_silently=False,
            )
            
            # Update log
            log.status = 'sent'
            log.sent_at = timezone.now()
            log.attempts += 1
            log.save()
            
            logger.info(f"Email sent to {recipient} for submission {submission.id}")
            
        except Exception as e:
            logger.error(f"Failed to send email to {recipient}: {str(e)}")
            log.status = 'failed'
            log.error_message = str(e)
            log.attempts += 1
            log.save()
            # Don't raise - continue with other recipients


def send_webhook_notification(submission, webhook_url):
    """Send webhook notification about new submission"""
    try:
        # Create notification log
        log = NotificationLog.objects.create(
            submission=submission,
            channel='webhook',
            recipient=webhook_url,
            status='pending'
        )
        
        # Prepare payload
        payload = {
            'event': 'form.submitted',
            'submission_id': str(submission.id),
            'form': {
                'id': str(submission.form_version.form.id),
                'name': submission.form_version.form.name,
            },
            'submitted_by': {
                'id': str(submission.submitted_by.id) if submission.submitted_by else None,
                'email': submission.submitted_by.email if submission.submitted_by else None,
            },
            'submitted_at': submission.submitted_at.isoformat() if submission.submitted_at else None,
            'status': submission.status,
        }
        
        # Send webhook
        response = requests.post(
            webhook_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        response.raise_for_status()
        
        # Update log
        log.status = 'sent'
        log.sent_at = timezone.now()
        log.attempts += 1
        log.save()
        
        logger.info(f"Webhook sent to {webhook_url} for submission {submission.id}")
        
    except Exception as e:
        logger.error(f"Failed to send webhook to {webhook_url}: {str(e)}")
        log.status = 'failed'
        log.error_message = str(e)
        log.attempts += 1
        log.save()
        raise  # Raise to trigger Celery retry


@shared_task
def cleanup_old_notifications():
    """
    Periodic task to clean up old notification logs
    Keeps logs for 90 days
    """
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=90)
    deleted_count = NotificationLog.objects.filter(
        created_at__lt=cutoff_date
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_count} old notification logs")
    return deleted_count


@shared_task
def retry_failed_notifications():
    """
    Periodic task to retry failed notifications
    Retries notifications that failed less than 3 times
    """
    failed_notifications = NotificationLog.objects.filter(
        status='failed',
        attempts__lt=3
    )
    
    retry_count = 0
    for notification in failed_notifications:
        try:
            submission = notification.submission
            
            if notification.channel == 'email':
                send_email_notification(
                    submission,
                    [notification.recipient]
                )
            elif notification.channel == 'webhook':
                send_webhook_notification(
                    submission,
                    notification.recipient
                )
            
            retry_count += 1
            
        except Exception as e:
            logger.error(f"Retry failed for notification {notification.id}: {str(e)}")
            continue
    
    logger.info(f"Retried {retry_count} failed notifications")
    return retry_count