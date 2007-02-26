from threading import RLock 
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

class TaskList:
    def __init__(self):
        self._fetchlists = []
        self._lock = RLock()

    @locked
    def get(self):
        while 1:
            for list in self._fetchlists:
                task = list.pop()
                if task:
                    return task
                    

    @locked
    def put_list(self, list):
        self._fetchlists.append(list)

    @locked
    def remove_list(self, list):
        self._fetchlists.remove(list)


class FetchList:

    def __init__(self):
        self._fetches = []
        self._lock = RLock()
        self._stopped = True
        self.
    
    @locked
    def pop(self):
        if not self._stopped:
            if len(self._fetches):
                return self._fetches.pop()

    @locked
    def put(self, fetch):
        self._fetches[0:0] = [fetch]

    @locked 
    def put_list(self, list): 
        self._fetches[0:0] = list


class PageManager: 
    def __init__(self, deptracker, tasklist): 
        self.deptracker = deptracker 
        self.tasklist = tasklist 
        self.fetchlist = FetchList()
        self.page_archive = {} 
        self.modification_state = {} 
        self._lock = RLock()
        tasklist.put_list(self.fetchlist)

    def check_mod(self, request_url, environ): 
        resource = make_resource_key(request_url, environ)
        if not self.dep_tracker.is_tracked(resource): 
            pass 

        initial_requests = [request_url] 
        initial_requests += self.deptracker.get_all_deps(resource)
            
        for url in initial_requests: 
            self.add_conditional_get(url)

        

    def add_conditional_get(self, url): 
        pass 
        
    @locked
    def got_304_back(self, url):

        self.modification_state[url][1] -= 1

        finished_children = True
        while finished_children and url:
            parent, count = self.modification_state[url]
            for child in self.deptracker.get_direct_deps(make_resource_key(url, environ)):
                if child[1]:
                    finished_children = False
                    break
            if finished_children:
                assert self.modification_state[url][1] == 1
                if parent:
                    self.modification_state[parent][1] -= 1
                    assert self.modification_state[parent][1] >= 0
                url = parent

        if not finished_children:
            return
        
