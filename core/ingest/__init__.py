"""Scheduled ingestion from the devices and services Klaus reads.

Every module here runs from a cron job, pulls a bounded batch, and
records a cursor so the next run resumes rather than restarting."""
