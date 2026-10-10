import redis

redis_client = redis.Redis(host="cache.internal", port=6379)
