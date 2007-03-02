from sets import Set
from threading import RLock 
from decorator import decorator
from transcluder.cookie_wrapper import get_relevant_cookies, make_cookie_string

def make_resource_key(url, environ): 
    cookies = [] 
    if environ.has_key('transcluder.incookies'): 
        cookies = get_relevant_cookies(environ['transcluder.incookies'], url)

    return (url, make_cookie_string(cookies))


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
def locked(func, *args, **kw):
    lock = args[0]._lock

    import time
    start = time.time()
    lock.acquire()
    try:
        if time.time() - start > 0.10:
            print "waited %s on %s" % (time.time() - start, func)
        return func(*args, **kw)
    finally:
        lock.release()
    


class DependencyTracker: 
    def __init__(self): 
        self._deps = {}
        self._lock = RLock() 

    @locked
    def set_direct_deps(self, resource, deps): 
        self._deps[resource] = deps[:]

    @locked
    def update(self, dep_map): 
        self._deps.update(dep_map)

    @locked
    def __len__(self): 
        return len(self._deps)


    @locked
    def clear(self): 
        self._deps.clear()

    @locked
    def is_tracked(self, resource): 
        return self._deps.has_key(resource)

    @locked
    def get_direct_deps(self, resource): 
        if self._deps.has_key(resource):
            return self._deps[resource][:] 
        else:
            return []

    @locked
    def get_all_deps(self, resource): 
        seen = Set() 

        deps = self.get_direct_deps(resource)

        index = 0 
        while index < len(deps): 
            new_deps = self.get_direct_deps(deps[index])
            for dep in new_deps: 
                if not dep in seen: 
                    seen.add(dep)
                    dep_list.append(dep)
            index += 1

        return deps

    


        
