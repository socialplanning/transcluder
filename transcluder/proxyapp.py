
# Copyright (c) 2007 The Open Planning Project.

# Transcluder is Free Software.  See license.txt for licensing terms


from wsgifilter.proxyapp import ForcedProxy
from transcluder.middleware import TranscluderMiddleware


class PathPrefixMiddleware:
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix
        
    def __call__(self, environ, start_response):
        new_path = self.prefix + environ['PATH_INFO']
        environ['PATH_INFO'] = new_path
        return self.app(environ, start_response)

def make_proxy(global_conf, **app_conf):
    app = ForcedProxy(remote=app_conf.get('force_host'))

    if 'path_prefix' in app_conf: 
        app = PathPrefixMiddleware(app, app_conf.get('path_prefix'))

    app = TranscluderMiddleware(app)
    return app
