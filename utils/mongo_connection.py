"""
MongoDB connection helper for LQC Data Intelligence Team.
"""

from config.settings import MONGO_SETTINGS


def get_mongo_uri() -> str:
    """
    Get MongoDB connection URI.

    Selection rule (matches the demo deploy on EC2 + the local-dev path):
      1. If MONGO_URL is set explicitly, use it. This covers any setup where
         Mongo is reachable at a single endpoint — local docker, the EC2
         demo box where Mongo runs in compose alongside the app, a managed
         cluster reached via standard mongodb:// URI, etc.
      2. Otherwise, build a MongoDB Atlas mongodb+srv:// URI from the
         MONGO_CLUSTER / MONGO_RW_* settings. This is the "no MONGO_URL,
         use Atlas" branch.

    The previous behaviour keyed off ENVIRONMENT == 'local' which broke the
    EC2 deploy: ENVIRONMENT=prod with MONGO_URL set used to fall through to
    the Atlas branch with empty credentials and emit "empty string is not a
    valid username" at startup.
    """
    if MONGO_SETTINGS.MONGO_URL:
        return MONGO_SETTINGS.MONGO_URL

    return (
        f'mongodb+srv://{MONGO_SETTINGS.MONGO_RW_USERNAME}:{MONGO_SETTINGS.MONGO_RW_PASSWORD}@'
        f'{MONGO_SETTINGS.MONGO_CLUSTER}/{MONGO_SETTINGS.MONGO_DATABASE}'
        f'?retryWrites=true&w=majority&appName={MONGO_SETTINGS.CLUSTER_APP_NAME}'
    )
