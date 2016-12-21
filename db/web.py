#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
这是一个简单的， 轻量级的， WSGI兼容(Web Server Gateway Interface)的web 框架
WSGI概要：
    工作方式： WSGI server -----> WSGI 处理函数
    作用： 将HTTP原始的请求、解析、响应 这些交给WSGI server 完成， WSGI是HTTP的高级封装
    例子:
        def application(environ, start_response):
            method = environ['RESOURCE_METHOD']
            path = environ['PATH_INFO']
            if method == 'GET' and path == '/':
                :return handle_home(environ, start_response)
            if method == 'POST' and path == '/signin':
                :return handle_signin(environ, start_response)

         wsgi server
                def run(self, port, host='127.0.0.1'):
                    from wsgiref.simple_server import make_server
                    server = make_server(host, port, application)
                    server.serve_forever()

设计web框架的原因：
    1WSGI提供的接口虽然比HTTP接口高级不少， 但和web app 的处理逻辑比， 还是比较低级
    我们需要在WSGI接口之上能进一步抽象， 让我们专注于用一个函数处理一个URL，至于URL到函数的映射
    交给Web框架做

设计web框架接口：
    1. URL路由： 用于URL到处理函数的映射
    2. URL拦截： 用于根据URL做权限检测
    3. 视图：    用于HTML页面生成
    4. 数据模型：用于抽取数据
    5. 事物数据：request数据和response数据的封装
"""
# transwarp/web.py
import types, os, re, cgi, sys, time, datetime, functools, mimetypes, threading, logging, traceback, urllib

from db import Dict
import utils

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

#################################################################
# 实现事物数据接口, 实现request 数据和response数据的存储,
# 是一个全局ThreadLocal对象
#################################################################

# 全局ThreadLocal对象：
ctx = threading.local()

_RE_RESPONSE_STATUS = re.compile(r'^\d\d\d(\ [\w\ ]+)?$')
_HEADER_X_POWERED_BY = ('X-Powered-By', 'transwarp/1.0')

# response status
_RESPONSE_STATUSES = {
    # Informational
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',
    #Successful
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi Status',
    226: 'IM Used',

    #Redirection
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary',

    # Client Error
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request URL Too Long',
    415: 'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a teapot",
    422: 'Unprocessable Entity',
    423: 'Lock',
    424: 'Failed Dependency',
    426: 'Upgrade Required',

    # Server Error
    500: 'Internal Server Error', #
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    507: 'Insufficient Storage',
    510: 'Not Extended',
}
#response_headers 存疑
_RESPONSE_HEADERS = (
    'Accept-Ranges',
    'Age',
    'Allow',
    'Cache-Control',
    'Connection',
    'Content-Encoding',
    'Content-Language',
    'Content-Length',
    'Content-Location',
    'Content-MD5',
    'Content-Disposition',
    'Content-Range',
    'Content-Type',
    'Date',
    'ETag',
    'Expires',
    'Last-Modified',
    'Link',
    'Location',
    'P3P',
    'Pragma',
    'Proxy-Authenticate',
    'Refresh',
    'Retry-After',
    'Server',
    'Set-Cookie',
    'Strict-Transport-Security',
    'Trailer',
    'Transfer-Encoding',
    'Vary',
    'Via',
    'Warning',
    'WWW-Authenticate',
    'X-Frame-Options',
    'X-XSS-Protection',
    'X-Content-Type-Options',
    'X-Forwarded-Proto',
    'X-Powered-By',
    'X-UA-Compatible',
)
# 用于异常处理
class _HttpError(Exception):
    """
    HttpError that defines http error code.
    >>> e = _HttpError(404)
    >>> e.status
    '404 Not Found'
    """
    def __init__(self, code):
        #Init an HttpError with response code.
        super(_HttpError, self).__init__()
        self.status = '%d %s' % (code, _RESPONSE_STATUSES[code])
        self._headers = None
    def header(self, name, value):
        # 添加header, 如果header为空则添加powered by header
        if not self._headers:
            self._headers = [_HEADER_X_POWERED_BY]
        self._headers.append((name, value))
    @property
    def headers(self):
        #使用setter方法实现的 header属性
        if hasattr(self, '_headers'):
            return self._headers
        return []

    def __str__(self):
        return self.status

    __repr__ = __str__

class _RedirectError(_HttpError):
    """
    RedirectError that defines http redirect code.

    >>> e = _RedirectError(302, 'http://www.apple.com/')
    >>> e.status
    '302 Found'
    >>> e.location
    'http://www.apple.com/'
    """
    def __init__(self, code, location):
        """
        Init an HttpError with response code.
        """
        super(_RedirectError, self).__init__(code)
        self.location = location

    def __str__(self):
        return '%s, %s' % (self.status, self.location)

    __repr__ = __str__
# # HTTP错误类:
class HttpError(Exception):
    @staticmethod
    def badrequest():
        '''
        Send bad request response
        >>> raise HttpError.badrequest()
        Traceback (most recent call last):
          ...
        _HttpError: 400 Bad Request
        '''
        return _HttpError(400)

    @staticmethod
    def unauthorized():
        '''
        send an unauthorized response.

        >>> raise HttpError.unauthorized()
        Traceback (most recent call last):
            ...
        _HttpError: 401 Unauthorized
        '''
        return _HttpError(401)

    @staticmethod
    def  forbidden():
        '''
        >>> raise HttpError.forbidden()
        Traceback (most recent call last):
            ...
        _HttpError: 403 Forbidden
        '''
        return _HttpError(403)

    @staticmethod
    def forbidden():
        '''
        >>> raise HttpError.forbidden()
        Traceback (most recent call last):
            ...
        _HttpError: 403 Forbidden
        '''
        return _HttpError(403)

    @staticmethod
    def nonfound():
        '''
        >>> raise HttpError.nonfound()
        Traceback (most recent call last):
            ...
        _HttpError: 404 Not Found
        '''
        return _HttpError(404)

    @staticmethod
    def conflict():
        return _HttpError(409)

    @staticmethod
    def internalerror():
        return _HttpError(500)

    @staticmethod
    def redirect(location):
        """
        Do permanent redirect.

        >>> raise HttpError.redirect('http://www.itranswarp.com/')
        Traceback (most recent call last):
          ...
        _RedirectError: 301 Moved Permanently, http://www.itranswarp.com/
        """
        return _RedirectError(301, location)

    @staticmethod
    def found(location):
        return _RedirectError(302, location)
    @staticmethod
    def seeother(location):
        return _RedirectError(303, location)

_RESPONSE_HEADER_DICT = dict(zip(map(lambda x: x.upper(), _RESPONSE_HEADERS), _RESPONSE_HEADERS))
# # request对象:
# class Request(object):
#     # 根据key返回value:
#     def get(self, key, default=None):
#         pass
#
#     # 返回key-value的dict:
#     def input(self):
#         pass
#
#     # 返回URL的path:
#     @property
#     def path_info(self):
#         pass
#
#     # 返回HTTP Headers:
#     @property
#     def headers(self):
#         pass
#
#     # 根据key返回Cookie value:
#     def cookie(self, name, default=None):
#         pass
#
# # response对象:
# class Response(object):
#     # 设置header:
#     def set_header(self, key, value):
#         pass
#
#     # 设置Cookie:
#     def set_cookie(self, name, value, max_age=None, expires=None, path='/'):
#         pass
#
#     # 设置status:
#     @property
#     def status(self):
#         pass
#     @status.setter
#     def status(self, value):
#         pass
#
# # 定义GET:
# def get(path):
#     pass
#
# # 定义POST:
# def post(path):
#     pass
#
# # 定义模板:
# def view(path):
#     pass
#
# # 定义拦截器:
# def interceptor(pattern):
#     pass
#
# # 定义模板引擎:
# class TemplateEngine(object):
#     def __call__(self, path, model):
#         pass
#
# # 缺省使用jinja2:
# class Jinja2TemplateEngine(TemplateEngine):
#     def __init__(self, templ_dir, **kw):
#         from jinja2 import Environment, FileSystemLoader
#         self._env = Environment(loader=FileSystemLoader(templ_dir), **kw)
#
#     def __call__(self, path, model):
#         return self._env.get_template(path).render(**model).encode('utf-8')
#
# class WSGIApplication(object):
#     def __init__(self, document_root=None, **kw):
#         pass
#
#     # 添加一个URL定义:
#     def add_url(self, func):
#         pass
#
#     # 添加一个Interceptor定义:
#     def add_interceptor(self, func):
#         pass
#
#     # 设置TemplateEngine:
#     @property
#     def template_engine(self):
#         pass
#
#     @template_engine.setter
#     def template_engine(self, engine):
#         pass
#
#     # 返回WSGI处理函数:
#     def get_wsgi_application(self):
#         def wsgi(env, start_response):
#             pass
#         return wsgi
#
#     # 开发模式下直接启动服务器:
#     def run(self, port=9000, host='127.0.0.1'):
#         from wsgiref.simple_server import make_server
#         server = make_server(host, port, self.get_wsgi_application())
#         server.serve_forever()
#
# wsgi = WSGIApplication()
# if __name__ == '__main__':
#     wsgi.run()
# else:
#     application = wsgi.get_wsgi_application()
if __name__ == '__main__':
    import doctest
    doctest.testmod(verbose=True)
    # e = _HttpError(404)
    # print e.status