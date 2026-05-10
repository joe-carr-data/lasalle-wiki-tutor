"""
MongoDB connection helper for LQC Data Intelligence Team.
"""

from config.settings import MONGO_SETTINGS, PROJECT_SETTINGS


def get_mongo_uri() -> str:
    """
    Get MongoDB connection URI based on environment.

    Returns:
        MongoDB connection string

    Examples:
        Local: mongodb://admin:password@host.docker.internal:27017
        Atlas: mongodb+srv://user:pass@cluster/database
    """
    if PROJECT_SETTINGS.ENVIRONMENT == 'local':
        # Use MONGO_URL from environment variable (supports Docker host.docker.internal)
        uri = MONGO_SETTINGS.MONGO_URL
    else:
        # MongoDB Atlas (production)
        uri = (
            f'mongodb+srv://{MONGO_SETTINGS.MONGO_RW_USERNAME}:{MONGO_SETTINGS.MONGO_RW_PASSWORD}@'
            f'{MONGO_SETTINGS.MONGO_CLUSTER}/{MONGO_SETTINGS.MONGO_DATABASE}'
            f'?retryWrites=true&w=majority&appName={MONGO_SETTINGS.CLUSTER_APP_NAME}'
        )

    return uri
