import logging

import redis

from booking_system import settings
from utils.singleton import singleton

logger = logging.getLogger(__name__)


@singleton
class RedisClient:
    """
    Lazy and singleton Redis client
    """

    @property
    def conn(self):
        if not hasattr(self, "_conn"):
            self.get_connection()
        return self._conn

    def get_connection(self):
        self._conn = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
