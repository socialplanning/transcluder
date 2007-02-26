from sets import Set
from threading import RLock 
from transcluder.cookie_wrapper import get_relevant_cookies

def make_resource_key(url, environ): 
    cookies = [] 
    if environ.has_key('transcluder.incookies'): 
        cookies = get_relevant_cookies(environ['transcluder.incookies'], url)

    return (url, make_cookie_string(cookies))


class DependencyTracker: 
    def __init__(self): 
        self._deps = {}
        self._lock = RLock() 

    def set_direct_deps(self, resource, deps): 
        self._lock.acquire() 
        self._deps[resource] = deps[:]
        self._lock.release() 
    
    def update(self, resource, dep_map): 
        self._lock.acquire()
        self._deps.update(dep_map)
        self._lock.release()

    def __len__(self): 
        self._lock.acquire()
        dep_len = len(self._deps)
        self._lock.release()
        return dep_len 

    def clear(self): 
        self._lock.acquire()
        self._deps.clear()
        self._lock.release()

    def is_tracked(self, resource): 
        self._lock.acquire()
        tracked = self._deps.has_key(resource)
        self._lock.release()
        return tracked 

    def get_direct_deps(self, resource): 
        self._lock.acquire() 
        if self._deps.has_key(resource):
            deps = self._deps[resource][:] 
        else:
            deps = []
        self._lock.release() 
        return deps 

    def get_all_deps(self, resource): 
        seen = Set() 

        self._lock.acquire() 

        deps = self.get_direct_deps(resource)

        index = 0 
        while index < len(deps): 
            new_deps = self.get_direct_deps(deps[index])
            for dep in new_deps: 
                if not dep in seen: 
                    seen.add(dep)
                    dep_list.append(dep)

        self._lock.release() 

        return deps

    


        
