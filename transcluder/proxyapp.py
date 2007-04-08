from wsgifilter.proxyapp import ForcedProxy
from transcluder.middleware import TranscluderMiddleware


def make_proxy(global_conf, **app_conf):
    app = ForcedProxy(remote=app_conf.get('force_host'))
    app = TranscluderMiddleware(app)
    return app
