from functools import wraps


def personal_consumer(func):
    @wraps(func)
    async def wrapper_decorator(*args, **kwargs):
        self = args[0]

        async def accept():
            value = await func(*args, **kwargs)
            await self.accept()
            return value

        if self.scope['user'].is_authenticated:
            username = self.scope['user'].username
            room_name = self.scope['url_route']['kwargs']['username']
            if username == room_name:
                return await accept()

        await self.close()

    return wrapper_decorator


def private_consumer_event(func):
    @wraps(func)
    async def wrapper_decorator(*args, **kwargs):
        self = args[0]
        if self.scope['user'].is_authenticated:
            return await func(*args, **kwargs)

    return wrapper_decorator
