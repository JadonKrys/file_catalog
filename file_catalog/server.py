from __future__ import absolute_import, division, print_function

import sys
import os
import logging
from functools import wraps
from pkgutil import get_loader
from collections import OrderedDict

import datetime

import pymongo.errors

import tornado.ioloop
import tornado.web
from tornado.escape import json_encode,json_decode
from tornado.gen import coroutine

from file_catalog.validation import Validation

import file_catalog
from file_catalog.mongo import Mongo
from file_catalog import urlargparse

logger = logging.getLogger('server')

def get_pkgdata_filename(package, resource):
    """Get a filename for a resource bundled within the package"""
    loader = get_loader(package)
    if loader is None or not hasattr(loader, 'get_data'):
        return None
    mod = sys.modules.get(package) or loader.load_module(package)
    if mod is None or not hasattr(mod, '__file__'):
        return None

    # Modify the resource name to be compatible with the loader.get_data
    # signature - an os.path format "filename" starting with the dirname of
    # the package's __file__
    parts = resource.split('/')
    parts.insert(0, os.path.dirname(mod.__file__))
    return os.path.join(*parts)

def tornado_logger(handler):
    """Log levels based on status code"""
    if handler.get_status() < 400:
        log_method = logger.debug
    elif handler.get_status() < 500:
        log_method = logger.warning
    else:
        log_method = logger.error
    request_time = 1000.0 * handler.request.request_time()
    log_method("%d %s %.2fms", handler.get_status(),
            handler._request_summary(), request_time)

def sort_dict(d):
    """
    Creates an OrderedDict by taking the `dict` named `d` and orderes its keys.
    If a key contains a `dict` it will call this function recursively.
    """

    od = OrderedDict(sorted(d.items()))

    # check for dicts in values
    for key, value in od.iteritems():
        if isinstance(value, dict):
            od[key] = sort_dict(value)

    return od

def set_last_modification_date(d):
    d['meta_modify_date'] = str(datetime.datetime.utcnow())

class Server(object):
    """A file_catalog server instance"""

    def __init__(self, config, port=8888, db_host='localhost', debug=False):
        static_path = get_pkgdata_filename('file_catalog', 'data/www')
        if static_path is None:
            raise Exception('bad static path')
        template_path = get_pkgdata_filename('file_catalog', 'data/www_templates')
        if template_path is None:
            raise Exception('bad template path')

        # print configuration
        logger.info('db host: %s' % db_host)
        logger.info('server port: %s' % port)
        logger.info('debug: %s' % debug)

        main_args = {
            'base_url': '/api',
            'debug': debug,
        }

        api_args = main_args.copy()
        api_args.update({
            'db': Mongo(db_host),
            'config': config,
        })

        app = tornado.web.Application([
                (r"/", MainHandler, main_args),
                (r"/api", HATEOASHandler, api_args),
                (r"/api/files", FilesHandler, api_args),
                (r"/api/files/(.*)", SingleFileHandler, api_args),
            ],
            static_path=static_path,
            template_path=template_path,
            log_function=tornado_logger,
        )
        app.listen(port)

    def run(self):
        tornado.ioloop.IOLoop.current().start()

class MainHandler(tornado.web.RequestHandler):
    """Main HTML handler"""
    def initialize(self, base_url='/', debug=False):
        self.base_url = base_url
        self.debug = debug

    def get_template_namespace(self):
        namespace = super(MainHandler,self).get_template_namespace()
        namespace['version'] = file_catalog.__version__
        return namespace

    def get(self):
        try:
            self.render('index.html')
        except Exception as e:
            logger.warn('Error in main handler', exc_info=True)
            message = 'Error generating page.'
            if self.debug:
                message += '\n' + str(e)
            self.send_error(message=message)

    def write_error(self,status_code=500,**kwargs):
        """Write out custom error page."""
        self.set_status(status_code)
        if status_code >= 500:
            self.write('<h2>Internal Error</h2>')
        else:
            self.write('<h2>Request Error</h2>')
        if 'message' in kwargs:
            self.write('<br />'.join(kwargs['message'].split('\n')))
        self.finish()


def catch_error(method):
    """Decorator to catch and handle errors on api handlers"""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            logger.warn('Error in api handler', exc_info=True)
            kwargs = {'message':'Internal error in '+self.__class__.__name__}
            if self.debug:
                kwargs['exception'] = str(e)
            self.send_error(**kwargs)
    return wrapper

class APIHandler(tornado.web.RequestHandler):
    """Base class for API handlers"""
    def initialize(self, config, db=None, base_url='/', debug=False, rate_limit=10):
        self.db = db
        self.base_url = base_url
        self.debug = debug
        self.config = config
        
        # subtract 1 to test before current connection is added
        self.rate_limit = rate_limit-1
        self.rate_limit_data = {}

    def set_default_headers(self):
        self.set_header('Content-Type', 'application/hal+json; charset=UTF-8')

    def prepare(self):
        # implement rate limiting
        ip = self.request.remote_ip
        if ip in self.rate_limit_data:
            if self.rate_limit_data[ip] > self.rate_limit:
                self.send_error(429, 'rate limit exceeded for IP address')
            else:
                self.rate_limit_data[ip] += 1
        else:
            self.rate_limit_data[ip] = 1

    def on_finish(self):
        ip = self.request.remote_ip
        self.rate_limit_data[ip] -= 1
        if self.rate_limit_data[ip] <= 0:
            del self.rate_limit_data[ip]

    def write(self, chunk):
        # override write so we don't output a json header
        if isinstance(chunk, dict):
            chunk = json_encode(sort_dict(chunk))
        super(APIHandler, self).write(chunk)

    def write_error(self,status_code=500,**kwargs):
        """Write out custom error page."""
        self.set_status(status_code)
        kwargs.pop('exc_info',None)
        if kwargs:
            self.write(kwargs)
        self.finish()

class HATEOASHandler(APIHandler):
    def initialize(self, **kwargs):
        super(HATEOASHandler, self).initialize(**kwargs)

        # response is known ahead of time, so pre-compute it
        self.data = {
            '_links':{
                'self': {'href': self.base_url},
            },
            'files': {'href': os.path.join(self.base_url,'files')},
        }

    @catch_error
    def get(self):
        self.write(self.data)

class FilesHandler(APIHandler):
    def initialize(self, **kwargs):
        super(FilesHandler, self).initialize(**kwargs)
        self.files_url = os.path.join(self.base_url,'files')
        self.validation = Validation(self.config)

    @catch_error
    @coroutine
    def get(self):
        try:
            kwargs = urlargparse.parse(self.request.query)
            if 'limit' in kwargs:
                kwargs['limit'] = int(kwargs['limit'])
                if kwargs['limit'] < 1:
                    raise Exception('limit is not positive')

                # check with config
                if kwargs['limit'] > self.config['filelist']['max_files']:
                    kwargs['limit'] = self.config['filelist']['max_files']
            else:
                # if no limit has been defined, set max limit
                kwargs['limit'] = self.config['filelist']['max_files']

            if 'start' in kwargs:
                kwargs['start'] = int(kwargs['start'])
                if kwargs['start'] < 0:
                    raise Exception('start is negative')

            if 'query' in kwargs:
                kwargs['query'] = json_decode(kwargs['query'])
                
                # _id and mongo_id means the same (mongo_id will be renamed to _id in self.db.find_files())
                # make sure that not both keys are in query
                if '_id' in kwargs['query'] and 'mongo_id' in kwargs['query']:
                    logging.warn('`query` contains `_id` and `mongo_id`', exc_info=True)
                    self.send_error(400, message='`query` contains `_id` and `mongo_id`')
                    return
        except:
            logging.warn('query parameter error', exc_info=True)
            self.send_error(400, message='invalid query parameters')
            return
        files = yield self.db.find_files(**kwargs)
        self.write({
            '_links':{
                'self': {'href': self.files_url},
                'parent': {'href': self.base_url},
            },
            '_embedded':{
                'files': files,
            },
            'files': [os.path.join(self.files_url,f['mongo_id']) for f in files],
        })

    @catch_error
    @coroutine
    def post(self):
        metadata = json_decode(self.request.body)

        if not self.validation.validate_metadata_creation(self, metadata):
            return

        set_last_modification_date(metadata)

        ret = yield self.db.get_file({'uid':metadata['uid']})

        if ret:
            # file uid already exists, check checksum
            if ret['checksum'] != metadata['checksum']:
                # the uid already exists (no replica since checksum is different
                self.send_error(409, message='conflict with existing file (uid already exists)',
                                file=os.path.join(self.files_url,ret['mongo_id']))
                return
            elif any(f in ret['locations'] for f in metadata['locations']):
                # replica has already been added
                self.send_error(409, message='replica has already been added',
                                file=os.path.join(self.files_url,ret['mongo_id']))
                return
            else:
                # add replica
                ret['locations'].extend(metadata['locations'])

                yield self.db.update_file(ret)
                self.set_status(200)
                ret = ret['mongo_id']
        else:
            ret = yield self.db.create_file(metadata)
            self.set_status(201)
        self.write({
            '_links':{
                'self': {'href': self.files_url},
                'parent': {'href': self.base_url},
            },
            'file': os.path.join(self.files_url, ret),
        })

class SingleFileHandler(APIHandler):
    def initialize(self, **kwargs):
        super(SingleFileHandler, self).initialize(**kwargs)
        self.files_url = os.path.join(self.base_url,'files')
        self.validation = Validation(self.config)

    @catch_error
    @coroutine
    def get(self, mongo_id):
        try:
            ret = yield self.db.get_file({'mongo_id':mongo_id})
    
            if ret:
                ret['_links'] = {
                    'self': {'href': os.path.join(self.files_url,mongo_id)},
                    'parent': {'href': self.files_url},
                }
    
                self.write(ret)
            else:
                self.send_error(404, message='not found')
        except pymongo.errors.InvalidId:
            self.send_error(400, message='Not a valid mongo_id')

    @catch_error
    @coroutine
    def delete(self, mongo_id):
        try:
            yield self.db.delete_file({'mongo_id':mongo_id})
        except pymongo.errors.InvalidId:
            self.send_error(400, message='Not a valid mongo_id')
        except:
            self.send_error(404, message='not found')
        else:
            self.set_status(204)

    @catch_error
    @coroutine
    def patch(self, mongo_id):
        metadata = json_decode(self.request.body)

        if self.validation.has_forbidden_attributes_modification(self, metadata):
            return

        set_last_modification_date(metadata)

        links = {
            'self': {'href': os.path.join(self.files_url,mongo_id)},
            'parent': {'href': self.files_url},
        }

        try:
            ret = yield self.db.get_file({'mongo_id':mongo_id})
        except pymongo.errors.InvalidId:
            self.send_error(400, message='Not a valid mongo_id')
            return

        if ret:
            # check if this is the same version we're trying to patch
            test_write = ret.copy()
            test_write['_links'] = links
            self.write(test_write)
            self.set_etag_header()
            same = self.check_etag_header()
            self._write_buffer = []
            if same:
                ret.update(metadata)

                if not self.validation.validate_metadata_modification(self, ret):
                    return

                yield self.db.update_file(ret.copy())
                ret['_links'] = links
                self.write(ret)
                self.set_etag_header()
            else:
                self.send_error(409, message='conflict (version mismatch)',
                                _links=links)
        else:
            self.send_error(404, message='not found')

    @catch_error
    @coroutine
    def put(self, mongo_id):
        metadata = json_decode(self.request.body)

        # check if user wants to set forbidden fields
        # `uid` is not allowed to be changed
        if self.validation.has_forbidden_attributes_modification(self, metadata):
            return

        set_last_modification_date(metadata)

        if 'mongo_id' not in metadata:
            metadata['mongo_id'] = mongo_id

        links = {
            'self': {'href': os.path.join(self.files_url,mongo_id)},
            'parent': {'href': self.files_url},
        }

        try:
            ret = yield self.db.get_file({'mongo_id':mongo_id})
        except pymongo.errors.InvalidId:
            self.send_error(400, message='Not a valid mongo_id')
            return

        # keep `uid`:
        metadata['uid'] = str(ret['uid'])

        if ret:
            # check if this is the same version we're trying to patch
            test_write = ret.copy()
            test_write['_links'] = links
            self.write(test_write)

            self.set_etag_header()
            same = self.check_etag_header()
            self._write_buffer = []
            if same:
                if not self.validation.validate_metadata_modification(self, metadata):
                    return

                yield self.db.replace_file(metadata.copy())
                metadata['_links'] = links
                self.write(metadata)
                self.set_etag_header()
            else:
                self.send_error(409, message='conflict (version mismatch)',
                                _links=links)
        else:
            self.send_error(404, message='not found')


