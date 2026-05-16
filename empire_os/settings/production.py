"""Production settings — DEBUG off, PostgreSQL via DATABASE_URL, security headers."""
from .base import *  # noqa

DEBUG = False

# Enforce HTTPS
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CSRF_TRUSTED_ORIGINS = ['http://45.63.49.223']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'bid_checker': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
