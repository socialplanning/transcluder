from sets import Set
from threading import Lock, RLock, Condition
from enum import Enum
from avl import new as avl
from transcluder.cookie_wrapper import * 
from wsgifilter.cache_utils import merge_cache_headers, parse_merged_etag
from transcluder.threadpool import WorkRequest, ThreadPool
from transcluder.deptracker import make_resource_key, locked
import time 
import traceback 

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
            print "Thread sleeping for lack of work"
            self.cv.wait()


    @locked
    def put_list(self, list):        
        assert list not in self._fetchlists
        if not hasattr(list, 'task_list_index'):
            list.task_list_index = self.next_task_list_index
            self.next_task_list_index += 1
        self._fetchlists.insert(list)
        self.cv.notifyAll() 

    @locked
    def remove_list(self, list):
        self._fetchlists.remove(list)

    def notify(self): 
        print "attempting to notify tasklist"
        self.cv.acquire()
        print "notify tasklist OK"
        self.cv.notify()
        self.cv.release() 

    def notifyAll(self): 
        self.cv.acquire()
        self.cv.notifyAll()
        self.cv.release() 


class FetchList: 
    def __init__(self, tasklist): 
        self.tasklist = tasklist
        self._lock = Lock()
        self._tasks = [] 
        self._pending = Set()
        self._in_progress = Set()


    def push(self, task): 
        print "attempting to push %s" % task.url 
        self._lock.acquire()
        try:
            if (not task.url in self._pending and 
                not task.url in self._in_progress): 
                self._tasks[0:0] = [task]
                self._pending.add(task.url)
                print "pushed %s" % task.url
                pushed = True
            else:
                pushed = False 
        finally: 
            self._lock.release() 

        self.tasklist.notify() 
        return pushed

    @locked 
    def pop(self): 
        if len(self._tasks):
            task = self._tasks.pop()
            self._pending.remove(task.url)
            self._in_progress.add(task.url)
            print "popped %s" % task.url 
            return task 
        else: 
            return None

    @locked 
    def __len__(self): 
        return len(self._tasks) 

    @locked 
    def clear(self): 
        self._tasks = []
        self._pending = Set()

    @locked 
    def completed(self, task): 
        assert (task.url in self._in_progress)
        self._in_progress.remove(task.url)
        print "completed %s" % task.url

    @locked 
    def claim(self, url): 
        if url in self._in_progress: 
            return False

        if url in self._pending: 
            self._pending.remove(url)
            tasks = [t for t in self._tasks if t.url == url]
            assert len(tasks) == 0 or len(tasks) == 1
            self._tasks.remove(tasks[0])

        self._in_progress.add(url)

        return True

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
        try: 
            self._do_fetch() 
        except: 
            traceback.print_exc() 

    def _do_fetch(self): 
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

        print "fetch of %s returned %s" % (self.url, self.response[0]) 

        if self.response[0].startswith('304'):
            self.page_manager.got_304(self)
        else:
            self.page_manager.got_200(self)

        print "finished FetchListItem(%s)" % self.url

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

        self.deptracker = deptracker 
        self.tasklist = tasklist 
        self.fetchlist = FetchList(tasklist) 
        self.find_dependencies = find_dependencies
        self.request = request_func

        self._request_url = request_url
        self._environ = environ.copy()
        self._root_resource = make_resource_key(self._request_url, self._environ)
        self._page_archive = {}         


        self._speculative_dep_info = {} 
        self._needed = Set() 
        self._actual_deps = Set()

        self._lock = RLock()
        self._cv = Condition(self._lock)

        self._state = PMState.initial 


    def __cmp__(self, other):
        return self.task_list_index - other.task_list_index    

    def is_modified(self): 
        if (self._state == PMState.modified or self._state == PMState.done or 
            self._state == PMState.get_pages):
            return True
        if self._state == PMState.not_modified:
            return False


        self._state = PMState.check_modification
        request_url, environ = self._request_url, self._environ
        if not ('HTTP_IF_NONE_MATCH' in environ or 
                'HTTP_IF_MODIFIED_SINCE' in environ):
            self._state = PMState.modified
            return True

        if not self.deptracker.is_tracked(self._root_resource): 
            #possible future todo: compute is-modified by issuing
            #conditional (for is-modified) *and* unconditional (for
            #transclusion tree) requests for each resource.
            self._state = PMState.modified
            return True

        self.tasklist.put_list(self.fetchlist)
        initial_requests = [request_url] 
        initial_requests += self.deptracker.get_all_deps(self._root_resource)
        self.expected_mod_responses = len(initial_requests)
            
        for url in initial_requests: 
            self.add_conditional_get(url)

        while self._state == PMState.check_modification:
            self._cv.acquire() 
            task = self.fetchlist.pop()
            if task:
                self._cv.release()
                print "main thread is checking modification of %s" % task.url
                task()
            else: 
                if self._state == PMState.check_modification: 
                    print "main thread is waiting for modification info..." 
                    self._cv.wait() 
                self._cv.release()

        self.tasklist.remove_list(self.fetchlist)

        print "exiting is_modified..."

        assert (self._state == PMState.not_modified or 
                self._state == PMState.modified or 
                self._state == PMState.done)

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
                return self._page_archive[url]

            if self._state == PMState.initial: 
                self._init_speculative_gets()

            should_fetch = self.fetchlist.claim(url)
        finally:
            self._lock.release()

        if should_fetch:
            #get it ourselves
            print "handing %s on main thread" % url 
            fetch = FetchListItem(url, self._environ, 
                          RequestType.get, 
                          self)
            fetch()
            print "main thread completed %s" % url 
            return self._page_archive[url]

        print "main thread waiting for arrival of %s" % url 
        self._cv.acquire()
        try:
            while 1:
                if self.have_page_content(url): 
                    return self._page_archive[url]
                self._cv.wait()
        finally:
            self._cv.release()
    

    @locked 
    def merge_headers_into(self, headers): 
        print "merge_headers_into, State = %s" % self._state
        if self._state != PMState.done and self._state != PMState.not_modified: 
            print "Page Archive: %s" % self._page_archive
            print "Needed: %s" % self._needed 
            print "Actual Deps: %s" % self._actual_deps 
            print "Speculative Deps: %s" % self._speculative_dep_info
        
        assert self._state == PMState.done or self._state == PMState.not_modified 

        response_info = {} 
        cookies = {}
        for url in self._actual_deps: 
            response_info[url] = self._page_archive[url][0:3]
            status, page_headers, body, parsed = self._page_archive[url]
            cookies.update(get_set_cookies_from_headers(page_headers, url))
        
        merge_cache_headers(response_info, headers)

        newcookie = wrap_cookies(cookies.values())        
        headers.append(('Set-Cookie', newcookie)) # replace? 


    @locked
    def add_conditional_get(self, url): 
        print "issuing conditional get for ", url
        
        if not self.have_archive(url): 
            self.fetchlist.push(FetchListItem(url, self._environ, 
                                              RequestType.conditional_get, 
                                              self))
        

    @locked 
    def add_get(self, url): 
        if not self.have_page_content(url): 
            print "issuing get for ", url
            self.fetchlist.push(FetchListItem(url, self._environ, 
                                              RequestType.get, 
                                              self))
            
    @locked
    def got_304(self, task):
        print "got 304 for ", task.url
        assert task.url not in self._page_archive
        self._page_archive[task.url] = task.archive_info() 

        self.fetchlist.completed(task)

        if self._state != PMState.check_modification: 
            assert(self._state != PMState.not_modified)
            if self._state == PMState.get_pages: 
                print "reissue %s as GET" % task.url
                self.add_get(task.url)
                self.notify() 
                print "finished reissue."                
                return 

        self.expected_mod_responses -= 1 
        
        if self.expected_mod_responses: 
            assert(self.expected_mod_responses) > 0 
            self.notify() 
            return 

        else: 
            assert(len(self.fetchlist) == 0)
            self._state = PMState.not_modified
            self.notify()


    @locked 
    def notify(self):
        print "PageManager::notify()"
        self._cv.acquire()
        self._cv.notifyAll()
        self._cv.release()
        
    @locked 
    def got_200(self, task): 
        print "got 200 for ", task.url
        self._page_archive[task.url] = task.archive_info() 
        
        print "updating dependencies"
        # update dependencies 
        status, headers, body, parsed = task.archive_info() 
        resource = make_resource_key(task.url, task.environ)
        if parsed:
            dep_list = self.find_dependencies(parsed, task.url)
        else:
            dep_list = []
        resource = make_resource_key(task.url, self._environ)
        self.deptracker.set_direct_deps(resource, dep_list)

        if self._state == PMState.check_modification: 
            self._init_speculative_gets()            

        self._speculative_dep_info[task.url] = dep_list

        print "issuing fetches for dependencies" 
        for dep in dep_list:
            self.add_get(dep)

        print "checking if %s is needed" % task.url 
        if task.url in self._needed: 
            self._got_needed(task.url) 

        print "notifying fetchlist of completion..."
        self.fetchlist.completed(task)

        print "notifying self of archived copy of %s" % task.url 
        self.notify()
        print "completed got_200 for %s" % task.url

    def _got_needed(self, url): 
        assert url in self._needed 

        self._needed.remove(url)
        self._actual_deps.add(url)

        all_deps = self.get_all_deps(url)
            
        for dep in all_deps: 
            if not self.have_page_content(dep):
                self._needed.add(dep)
            else: 
                self._actual_deps.add(dep)

        if len(self._needed) == 0:
            print "entering the done state..."
            self._state = PMState.done
            self.tasklist.remove_list(self.fetchlist)



    @locked
    def have_page_content(self, url): 
        print "entering have page content"
        self._cv.acquire() 
        try: 
            print "returning from have page content"
            return url in self._page_archive and not self._page_archive[url][0].startswith('304')
        finally: 
            self._cv.release()

    @locked
    def have_archive(self, url): 
        print "entering have page archive"
        self._cv.acquire() 
        try: 
            print "returning from have page archive"
            return url in self._page_archive
        finally: 
            self._cv.release()

    @locked 
    def get_all_deps(self, url): 
        seen = Set() 
        deps = self._speculative_dep_info.get(url, [])[:]
        index = 0
        while index < len(deps): 
            new_deps = self._speculative_dep_info.get(deps[index], [])
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

        self.tasklist.put_list(self.fetchlist)

        self._state = PMState.get_pages



    @locked 
    def _init_speculative_gets(self):         
        assert(self._state == PMState.initial or 
               self._state == PMState.check_modification)

        self._state = PMState.modified
        self.fetchlist.clear()

        self._speculative_dep_info = {} 
        
        self._needed = Set([self._request_url]) 


        self.add_get(self._request_url)        
        urls = self.deptracker.get_all_deps(self._root_resource)
        for url in urls: 
            self.add_get(url)


