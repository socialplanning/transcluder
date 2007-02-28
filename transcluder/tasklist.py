from sets import Set
from threading import Lock, RLock, Condition
from decorator import decorator
from enum import Enum
from avl import new as avl
from transcluder.threadpool import WorkRequest, ThreadPool
from transcluder.deptracker import make_resource_key

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
    def __init__(self, poolsize=10):
        self._fetchlists = avl()
        self._lock = Lock()
        self.cv = Condition(self._lock)
        self.next_task_list_index = 0
        self.threadpool = ThreadPool(poolsize)

    def get(self):
        self.cv.acquire()
        while 1:
            for list in self._fetchlists:
                task = list.pop()
                if task:
                    self.cv.release()
                    return task
            self.cv.wait()


    @locked
    def put_list(self, list):        
        assert list not in self._fetchlists
        if not hasattr(list, 'task_list_index'):
            list.task_list_index = self.next_task_list_index
            self.next_task_list_index += 1
        self._fetchlists.insert(list)

    @locked
    def remove_list(self, list):
        self._fetchlists.remove(list)

    def notify(self): 
        self.cv.acquire()
        self.cv.notify()
        self.cv.release() 

RequestType = Enum('conditional_get', 'get')

class FetchListItem(WorkRequest): 
    def __init__(self, url, environ, 
                 request_type, 
                 page_manager):         
        self.url = url 
        self.environ = environ.copy() 
        self.request_type = request_type 
        self.page_manager = page_manager 
        WorkRequest.__init__(self, self)

    def __call__(self): 
        if self.request_type == RequestType.conditional_get:
            etag = get_relevant_etag(self.url, self.environ)
            if etag:
                self.environ['HTTP_IF_NONE_MATCH'] = etag
        else:
            if 'HTTP_IF_MODIFIED_SINCE' in self.environ:
                del self.environ['HTTP_IF_MODIFIED_SINCE']

            if 'HTTP_IF_NONE_MATCH' in self.environ:
                del self.environ['HTTP_IF_NONE_MATCH']

        self.response = self.page_manager.request(self.url, self.environ)
        if self.response[0].startswith('304'):
            self.page_manager.got_304(self)
        else:
            self.page_manager.got_200(self)

    def archive_info(self): 
        return self.response
    


PMState = Enum(
    'initial', 
    'check_modification',
    'not_modified', 
    'modified', 
    'get_pages', 
    'done')

class PageManager: 
    def __init__(self, request_url, environ, deptracker, 
                 find_dependencies, tasklist, request_func): 

        self.request_url = request_url
        self.environ = environ
        self.root_resource = make_resource_key(self.request_url, self.environ)
        self.deptracker = deptracker 
        self.tasklist = tasklist 
        self._fetchlist = [] 
        self.page_archive = {}         

        self.find_dependencies = find_dependencies

        self.gets_needed = 0 
        self.speculative_dep_info = {} 
        self.needed = Set() 

        self._pending_work = Set() 
        self._lock = RLock()
        self._cv = Condition()
        self._state = PMState.initial 
        self.request = request_func

    def __cmp__(self, other):
        return self.task_list_index - other.task_list_index    

    def is_modified(self): 
        request_url, environ = self.request_url, self.environ
        if not ('HTTP_IF_NONE_MATCH' in environ or 
                'HTTP_IF_MODIFIED_SINCE' in environ):
            return True

        if not self.deptracker.is_tracked(root_resource): 
            return True

        tasklist.put_list(self)
        initial_requests = [request_url] 
        initial_requests += self.deptracker.get_all_deps(self.root_resource)
        self.expected_mod_responses = len(initial_requests)
            
        for url in initial_requests: 
            self.add_conditional_get(url)

        while self._state == PMState.check_modification:
            self._lock.acquire()
            try:
                task = self.pop()
            finally:
                self._lock.release()
            if task:
                task()
       
        self.tasklist.remove_list(self)

        if self._state == PMState.not_modified: 
            return False

        return True

    def fetch(self, url):
        if url in self.page_archive:
            status, headers, body, parsed = self.page_archive[url]
            if not status.starswith('304'):
                return self.page_archive[url]

        self._lock.acquire()
        try:
            not_pending = not url in self._pending_work
            if not_pending:
                tasks = [t for t in self._fetchlist if t.url == url]
                assert len(tasks) == 0 or len(tasks) == 1
                if tasks:
                    self._fetchlist.remove(tasks[0])
                self._pending_work.add(url)
        finally:
            self._lock.release()

        if not_pending:
            #get it ourselves
            fetch = FetchListItem(url, self.environ, 
                          RequestType.get, 
                          self)
            fetch()
            return self.page_archive[url]

        self._cv.acquire()
        try:
            while 1:
                if url in self.page_archive:
                    return self.page_archive[url]
                self._cv.wait()
        finally:
            self._cv.release()
    

    @locked 
    def add_conditional_get(self, url): 
        self._fetchlist[0:0] = [FetchListItem(url, self.environ, 
                                             RequestType.conditional_get, 
                                             self)]
        self.tasklist.notify() 
        

    @locked 
    def add_get(self, url): 
        self._fetchlist[0:0] = [FetchListItem(url, self.environ, 
                                             RequestType.get, 
                                             self)]
        self.tasklist.notify()
            
    @locked
    def got_304(self, task):

        self._pending_work.remove(task.url) 

        if self._state != PMState.check_modification: 
            assert(self._state != PMState.not_modified)
            if self._state == PMState.get_pages: 
                add_get(task.url)
            return 

        self.expected_mod_responses -= 1 
        
        if self.expected_mod_responses: 
            assert(self.expected_mod_responses) > 0 
            return 

        else: 
            assert(len(self._fetchlist) == 0)
            self._state = PMState.not_modified

        self.notify()

    def notify(self):
        self._cv.acquire()
        self._cv.notify()
        self._cv.release()
        
    @locked 
    def got_200(self, task): 
        url = task.url
        self.page_archive[url] = task.archive_info() 
        
        # update dependencies 
        status, headers, body, parsed = task.archive_info() 
        resource = make_resource_key(url, task.environ)
        if parsed:
            dep_list = self.find_dependencies(parsed, url)
        else:
            dep_list = []
        self.deptracker.set_direct_deps(url, dep_list)
        
        if self._state == PMState.check_modification: 
            self._init_speculative_gets()            

        scheduled_urls = Set([t.url for t in self._fetchlist])

        for dep in dep_list:                 
            if (not dep in self.page_archive and 
                not dep in self._pending_work and 
                not dep in scheduled_urls): 
                self.add_get(dep)
                if task.url in self.needed:
                    self.gets_needed+=1

        if task.url in self.needed:
            self.gets_needed -= 1

            for dep in dep_list:                 
                if dep in self.speculative_dep_info:
                    deps = dep_list[:]
                    index = 0
                    while index < len(deps): 
                        new_deps = self.speculative_dep_info.get(deps[index], [])
                        for dep in new_deps: 
                            if not dep in self.needed: 
                                self.needed.add(dep)
                                if not dep in self.page_archive:
                                    self.gets_needed += 1
                        index += 1
            
        else: 
            self.speculative_dep_info[url] = dep_list

        self._pending_work.remove(url) 

        assert self.gets_needed >= 0
        if self.gets_needed == 0:
            self._state = PMState.done
            self.tasklist.remove_list(self)

        self.notify()

    @locked 
    def begin_speculative_gets(self): 
        assert(self._state == PMState.initial or 
               self._state == PMState.modified)
        
        if self._state == PMState.initial: 
            self._init_speculative_gets()

        self.tasklist.put_list(self)

        self._state = PMState.get_pages
        self.tasklist.notify() 

    @locked 
    def _init_speculative_gets(self): 
        assert(self._state == PMState.initial or 
               self._state == PMState.check_modification)

        self._state = PMState.modified
        self._fetchlist = [] 

        self.gets_needed = 1 
        self.speculative_dep_info = {} 
        self.needed = Set([self.request_url]) 
        
        self.add_get(self.request_url)        
        urls = self.deptracker.get_all_deps(self.root_resource)
        for url in urls: 
            if not url in self._pending_work: 
                self.add_get(url)

    def pop(self):
        """
        used by TaskList 
        """
        if self._lock.acquire(blocking=False): 
            try: 
                if (self._state != PMState.done and 
                    self._state != PMState.modified):
                    if len(self._fetchlist):
                        task = self._fetchlist.pop()
                        self._pending_work.add(task.url)
                        return task
                    else: 
                        return None 
            finally: 
                self._lock.release() 
        else: 
            return None 

