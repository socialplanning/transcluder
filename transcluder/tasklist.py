from sets import Set
from threading import Lock, RLock, Condition
from enum import Enum
from avl import new as avl
from transcluder.cookie_wrapper import * 
from wsgifilter.cache_utils import merge_cache_headers, parse_merged_etag
from transcluder.threadpool import WorkRequest, ThreadPool
from transcluder.deptracker import make_resource_key, locked
import time 

class TaskList:
    def __init__(self, poolsize=10):
        self._fetchlists = avl()
        self._lock = Lock()
        self.cv = Condition(self._lock)
        self.next_task_list_index = 0
        self.threadpool = ThreadPool(poolsize, self)

    def get(self):        
        self.cv.acquire()
        while 1:
            for list in self._fetchlists:
                task = list.pop()
                if task:
                    self.cv.release()
                    print "about to send a task along to the pool: %s" % task
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

    def notifyAll(self): 
        self.cv.acquire()
        self.cv.notifyAll()
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
        self.environ['HTTP_COOKIE'] = make_cookie_string(get_relevant_cookies(self.environ['transcluder.incookies'], self.url)) # XXX transcluder dependencey

        if self.request_type == RequestType.conditional_get:
            if 'HTTP_IF_NONE_MATCH' in self.environ:
                etags = self.environ['transcluder.etags'] # XXX transcluder dependency
                if etags.has_key(self.url):
                    self.environ['HTTP_IF_NONE_MATCH'] = etags[self.url]
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

    def __str__(self):
        return "FetchListItem(%s, %s)" % (self.url, self.request_type)

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

        self.speculative_dep_info = {} 
        self.needed = Set() 
        self.actual_deps = Set()

        self._pending_work = Set() 
        self._lock = RLock()
        self._cv = Condition()
        self._state = PMState.initial 
        self.request = request_func

    def __cmp__(self, other):
        return self.task_list_index - other.task_list_index    

    def is_modified(self): 
        if (self._state == PMState.modified or self._state == PMState.done or 
            self._state == PMState.get_pages):
            return True
        if self._state == PMState.not_modified:
            return False


        self._state = PMState.check_modification
        request_url, environ = self.request_url, self.environ
        if not ('HTTP_IF_NONE_MATCH' in environ or 
                'HTTP_IF_MODIFIED_SINCE' in environ):
            self._state = PMState.modified
            return True

        if not self.deptracker.is_tracked(self.root_resource): 
            #possible future todo: compute is-modified by issuing
            #conditional (for is-modified) *and* unconditional (for
            #transclusion tree) requests for each resource.
            self._state = PMState.modified
            return True

        self.tasklist.put_list(self)
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

        print "exiting is_modified..."

        assert self._state == PMState.not_modified or self._state == PMState.modified or self._state == PMState.done
        if self._state == PMState.not_modified: 
            return False

        return True

    def fetch(self, url):
        print "fetch(%s)" % url 
        start = time.time()
        self._lock.acquire()
        try:        
            if time.time() - start > 0.10: 
                print "waited in fetch for %d" % time.time() - start 

            if self.have_page_content(url):
                return self.page_archive[url]

            if self._state == PMState.initial: 
                self._init_speculative_gets()

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
            print "handing %s on main thread" % url 
            fetch = FetchListItem(url, self.environ, 
                          RequestType.get, 
                          self)
            fetch()
            return self.page_archive[url]

        print "main thread waiting for arrival of %s" % url 
        self._cv.acquire()
        try:
            while 1:
                if self.have_page_content(url): 
                    return self.page_archive[url]
                self._cv.wait()
        finally:
            self._cv.release()
    

    @locked 
    def merge_headers_into(self, headers): 
        print "merge_headers_into, State = %s" % self._state
        if self._state != PMState.done and self._state != PMState.not_modified: 
            print "Page Archive: %s" % self.page_archive
            print "Needed: %s" % self.needed 
            print "Actual Deps: %s" % self.actual_deps 
            print "Speculative Deps: %s" % self.speculative_dep_info
        
        assert self._state == PMState.done or self._state == PMState.not_modified 

        response_info = {} 
        cookies = {}
        for url in self.actual_deps: 
            response_info[url] = self.page_archive[url][0:3]
            status, page_headers, body, parsed = self.page_archive[url]
            cookies.update(get_set_cookies_from_headers(page_headers, url))
        
        merge_cache_headers(response_info, headers)

        newcookie = wrap_cookies(cookies.values())        
        headers.append(('Set-Cookie', newcookie)) # replace? 


    @locked
    def add_conditional_get(self, url): 
        print "issuing conditional get for ", url
        
        self._fetchlist[0:0] = [FetchListItem(url, self.environ, 
                                             RequestType.conditional_get, 
                                             self)]
        self.tasklist.notify() 
        

    @locked 
    def add_get(self, url): 
        print "issuing get for ", url
        self._fetchlist[0:0] = [FetchListItem(url, self.environ, 
                                             RequestType.get, 
                                             self)]
        self.tasklist.notify()
            
    @locked
    def got_304(self, task):
        print "got 304 for ", task.url
        assert task.url not in self.page_archive
        self.page_archive[task.url] = task.archive_info() 

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
        self._cv.notifyAll()
        self._cv.release()
        
    @locked 
    def got_200(self, task): 
        print "got 200 for ", task.url
        url = task.url
        self.page_archive[url] = task.archive_info() 
        
        # update dependencies 
        status, headers, body, parsed = task.archive_info() 
        resource = make_resource_key(url, task.environ)
        if parsed:
            dep_list = self.find_dependencies(parsed, url)
        else:
            dep_list = []
        resource = make_resource_key(url, self.environ)
        self.deptracker.set_direct_deps(resource, dep_list)
        
        if self._state == PMState.check_modification: 
            self._init_speculative_gets()            

        scheduled_urls = Set([t.url for t in self._fetchlist])

        self.speculative_dep_info[url] = dep_list

        for dep in dep_list:
            if (not self.have_page_content(dep) and 
                not dep in self._pending_work and 
                not dep in scheduled_urls): 
                self.add_get(dep)

        if task.url in self.needed: 
            self.needed.remove(task.url)
            self.actual_deps.add(task.url)

            all_deps = self.get_all_deps(task.url)
            
            for dep in all_deps: 
                if not self.have_page_content(dep):
                    self.needed.add(dep)
                else: 
                    self.actual_deps.add(dep)


        self._pending_work.remove(url) 

        if len(self.needed) == 0:
            self._state = PMState.done
            self.tasklist.remove_list(self)

        self.notify()


    def have_page_content(self, url): 
        self._cv.acquire() 
        try: 
            return url in self.page_archive and not self.page_archive[url][0].startswith('304')
        finally: 
            self._cv.release()

    @locked 
    def get_all_deps(self, url): 
        seen = Set() 
        deps = self.speculative_dep_info.get(url, [])[:]
        index = 0
        while index < len(deps): 
            new_deps = self.speculative_dep_info.get(deps[index], [])
            for dep in new_deps: 
                if not dep in seen: 
                    seen.add(dep)
                    deps.append(dep)
            index += 1
        return deps
    


    @locked 
    def begin_speculative_gets(self): 
        print "begin speculative gets..." 

        if self._state == PMState.done:
            return

        assert(self._state == PMState.initial or 
               self._state == PMState.modified)
        
        if self._state == PMState.initial: 
            self._init_speculative_gets()

        self.tasklist.put_list(self)

        self._state = PMState.get_pages
        self.tasklist.notifyAll() 

    @locked 
    def _init_speculative_gets(self):         
        assert(self._state == PMState.initial or 
               self._state == PMState.check_modification)

        self._state = PMState.modified
        self._fetchlist = [] 


        self.speculative_dep_info = {} 
        self.needed = Set([self.request_url]) 
        
        self.add_get(self.request_url)        
        urls = self.deptracker.get_all_deps(self.root_resource)
        for url in urls: 
            if not url in self._pending_work: 
                self.add_get(url)

    @locked 
    def pop(self):
        """
        used by TaskList 
        """

        if (self._state != PMState.done and 
            self._state != PMState.modified):
            if len(self._fetchlist):
                task = self._fetchlist.pop()
                self._pending_work.add(task.url)
                return task
            else: 
                return None 

