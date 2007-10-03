
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


from decorator import decorator

@decorator
def locked(func, *args, **kw):
    lock = args[0]._lock
    lock.acquire()
    try:
        result = func(*args, **kw)
    finally:
        lock.release()
    return result

@decorator
def xlocked(func, *args, **kw):
    if hasattr(args[0], 'cv'):
        lock = args[0].cv
    else:
        lock = args[0]._lock

    import time
    start = time.time()
    lock.acquire()
    try:
        bad = False
        if time.time() - start > 0.10:
            bad = True
            print "waited %s on %s" % (time.time() - start, func)
            if hasattr(lock, 'oldThread'):
                print lock.oldThread
        start = time.time()
        out = func(*args, **kw)
        end = time.time()
        if end - start > 0.1:
            print "func %s itself took %s" % (func, end - start)
        return out
    finally:
        lock.release()
    

