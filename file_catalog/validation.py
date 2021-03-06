
import re

class Validation:
    def __init__(self, config):
        self.config = config

    def is_valid_sha512(self, hash_str):
        """Checks if `hash_str` is a valid SHA512 hash"""
        return re.match(r"[0-9a-f]{128}", str(hash_str), re.IGNORECASE) is not None
    
    def has_forbidden_attributes_creation(self, apihandler, metadata):
        """
        Checks if dict (`metadata`) has forbidden attributes.
    
        Returns `True` if it has forbidden attributes.
        """
    
        if set(self.config.get_list('metadata', 'forbidden_fields_creation')) & set(metadata):
            # forbidden fields
            apihandler.send_error(400, message='forbidden attributes',
                            file=apihandler.files_url)
            return True
    
    def has_forbidden_attributes_modification(self, apihandler, metadata):
        """
        Same as `has_forbidden_attributes_creation()` but it has additional forbidden attributes.
        """
    
        if set(self.config.get_list('metadata', 'forbidden_fields_update')) & set(metadata):
            # forbidden fields
            apihandler.send_error(400, message='forbidden attributes',
                            file=apihandler.files_url)
            return True
        else:
            return self.has_forbidden_attributes_creation(apihandler, metadata)
    
    def validate_metadata_creation(self, apihandler, metadata):
        """
        Validates metadata for creation
    
        Utilizes `send_error` and returnes `False` if validation failed.
        If validation was successful, `True` is returned.
        """
    
        if self.has_forbidden_attributes_creation(apihandler, metadata):
            return False
        
        return self.validate_metadata_modification(apihandler, metadata)
    
    def validate_metadata_modification(self, apihandler, metadata):
        """
        Validates metadata for modification
    
        Utilizes `send_error` and returnes `False` if validation failed.
        If validation was successful, `True` is returned.
        """
    
        if not set(self.config.get_list('metadata', 'mandatory_fields')).issubset(metadata):
            # check metadata for mandatory fields
            apihandler.send_error(400, message='mandatory metadata missing (mandatory fields: %s)' % self.config['metadata']['mandatory_fields'],
                            file=apihandler.files_url)
            return False
        if not self.is_valid_sha512(metadata['checksum']):
            # force to use SHA512
            apihandler.send_error(400, message='`checksum` needs to be a SHA512 hash',
                            file=apihandler.files_url)
            return False
        elif not isinstance(metadata['locations'], list):
            # locations needs to be a list
            apihandler.send_error(400, message='member `locations` must be a list',
                            file=apihandler.files_url)
            return False
        elif not metadata['locations']:
            # location needs have at least one entry
            apihandler.send_error(400, message='member `locations` must be a list with at least one url',
                            file=apihandler.files_url)
            return False
        elif not all(l for l in metadata['locations']):
            # locations aren't allowed to be empty
            apihandler.send_error(400, message='member `locations` must be a list with at least one non-empty url',
                            file=apihandler.files_url)
            return False
    
        return True
