from celery import shared_task

from .imports import process_tracking_import_job


@shared_task(name="tracking.process_tracking_import_job")
def process_tracking_import_job_task(job_id):
    return process_tracking_import_job(job_id=job_id)
