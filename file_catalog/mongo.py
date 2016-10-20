from __future__ import absolute_import, division, print_function

import logging

from pymongo import MongoClient
from pymongo.errors import BulkWriteError
from bson.objectid import ObjectId

from concurrent.futures import ThreadPoolExecutor
from tornado.concurrent import run_on_executor

logger = logging.getLogger('mongo')

class Mongo(object):
    """A ThreadPoolExecutor-based MongoDB client"""
    def __init__(self, host=None):
        kwargs = {}
        if host:
            parts = host.split(':')
            if len(parts) == 2:
                kwargs['port'] = int(parts[1])
            kwargs['host'] = parts[0]
        self.client = MongoClient(**kwargs).file_catalog
        self.executor = ThreadPoolExecutor(max_workers=10)

    @run_on_executor
    def find_files(self, query={}, limit=None, start=0):
        if 'mongo_id' in query:
            query['_id'] = query['mongo_id']
            del query['mongo_id']

        if '_id' in query and not isinstance(query['_id'], dict):
            query['_id'] = ObjectId(query['_id'])

        projection = ('_id', 'uid')

        result = self.client.files.find(query, projection)
        ret = []

        # `limit` and `skip` are ignored by __getitem__:
        # http://api.mongodb.com/python/current/api/pymongo/cursor.html#pymongo.cursor.Cursor.__getitem__
        #
        # Therefore, implement it manually:
        end = None

        if limit is not None:
            end = start + limit

        for row in result[start:end]:
            row['mongo_id'] = str(row['_id'])
            del row['_id']
            ret.append(row)
        return ret

    @run_on_executor
    def create_file(self, metadata):
        result = self.client.files.insert_one(metadata)
        if (not result) or (not result.inserted_id):
            logger.warn('did not insert file')
            raise Exception('did not insert new file')
        return str(result.inserted_id)

    @run_on_executor
    def get_file(self, filters):
        if 'mongo_id' in filters:
            filters['_id'] = filters['mongo_id']
            del filters['mongo_id']

        if '_id' in filters and not isinstance(filters['_id'], dict):
            filters['_id'] = ObjectId(filters['_id'])

        ret = self.client.files.find_one(filters)

        if ret and '_id' in ret:
            ret['mongo_id'] = str(ret['_id'])
            del ret['_id']

        return ret

    @run_on_executor
    def update_file(self, metadata):
        # don't change the original dict
        metadata_cpy = metadata.copy()

        if 'mongo_id' in metadata_cpy:
            metadata_cpy['_id'] = metadata_cpy['mongo_id']
            del metadata_cpy['mongo_id']

        metadata_id = metadata_cpy['_id']

        if not isinstance(metadata_id, dict):
            metadata_id = ObjectId(metadata_id)

        # _id cannot be updated. Remove _id 
        del metadata_cpy['_id']

        result = self.client.files.update_one({'_id': metadata_id},
                                              {'$set': metadata_cpy})

        if result.modified_count is None:
            logger.warn('Cannot detrmine if document has been modified since `result.modified_count` has the value `None`. `result.matched_count` is %s' % result.matched_count)
        elif result.modified_count != 1:
            logger.warn('updated %s files with id %r',
                        result.modified_count, metadata_id)
            raise Exception('did not update')

    @run_on_executor
    def replace_file(self, metadata):
        if 'mongo_id' in metadata:
            metadata['_id'] = metadata['mongo_id']
            del metadata['mongo_id']

        metadata_id = metadata['_id']

        if not isinstance(metadata_id, dict):
            metadata_id = ObjectId(metadata_id)

        # _id cannot be updated. Make a copy and remove _id 
        metadata_cpy = metadata.copy()
        del metadata_cpy['_id']

        result = self.client.files.replace_one({'_id': metadata_id},
                                               metadata_cpy)

        if result.modified_count is None:
            logger.warn('Cannot detrmine if document has been modified since `result.modified_count` has the value `None`. `result.matched_count` is %s' % result.matched_count)
        elif result.modified_count != 1:
            logger.warn('updated %s files with id %r',
                        result.modified_count, metadata_id)
            raise Exception('did not update')

    @run_on_executor
    def delete_file(self, filters):
        if 'mongo_id' in filters:
            filters['_id'] = filters['mongo_id']
            del filters['mongo_id']

        if '_id' in filters and not isinstance(filters['_id'], dict):
            filters['_id'] = ObjectId(filters['_id'])

        result = self.client.files.delete_one(filters)

        if result.deleted_count != 1:
            logger.warn('deleted %d files with filter %r',
                        result.deleted_count, filter)
            raise Exception('did not delete')
