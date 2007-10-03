
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


from sets import Set
from threading import RLock 
from transcluder.locked import locked
from transcluder.cookie_wrapper import get_relevant_cookies, make_cookie_string

def _merge_cookie_info(cookies):
    cookie_strings = []
    for cookie in cookies:
        extra = ''
        if cookie['domain'].startswith('.'):
            extra = ';domain=%s' % cookie['domain']
        if cookie.has_key('path'):
            extra += ';path=%s' % cookie['path']
        cookie_strings.append("%s=%s%s" % (cookie['name'], cookie['value'], extra))
    return ",".join(cookie_strings)


def make_resource_key(url, environ): 
    cookies = [] 
    if environ.has_key('transcluder.incookies'): 
        cookies = get_relevant_cookies(environ['transcluder.incookies'], url)

    cookies_id = _merge_cookie_info(cookies)

    return (url, cookies_id)

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

    


        
