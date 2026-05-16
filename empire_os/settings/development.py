"""Development settings — DEBUG on, SQLite, verbose logging."""
from .base import *  # noqa

DEBUG = True

ALLOWED_HOSTS = ['*']

# Verbose logging in dev
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'bid_checker': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
