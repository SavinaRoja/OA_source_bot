# -*- coding: utf-8 -*-

from functools import wraps
import time


def timer(t):
    """
    Function decorator that enforces a time interval between function calls.
    """
    def wrapper(f):
        @wraps(f)
        def wrapped_func(*args, **kwargs):
            now = time.time()
            if now - wrapped_func.latest > t:
                f(*args, **kwargs)
                wrapped_func.latest = now
        wrapped_func.latest = time.time()
        return wrapped_func
    return wrapper