from paste.proxy import TransparentProxy 
from transcluder.middleware import TranscluderMiddleware


def make_proxy(global_conf, **app_conf):
    app = TransparentProxy(force_host=app_conf.get('force_host'))
    app = TranscluderMiddleware(app)
    return app
