class UploaderBase:
    """Base class for other uploader's to inherit from to ensure to use the same methods and attributes.

    Attributes:
        configuration (:obj:`dict`): Configuration of this uploader
    Args:
        configuration (:obj:`dict`): Configuration of this uploader
        connect (:obj:`bool`): If the uploader should directly connect to the server
    """

    _mandatory_configuration = {}
    """(:obj:`dict`): Mandatory configuration settings. 
    
    Usage:
        {'some_key': type}: 
            - 'some_key' is a key name like 'host'
            - type is a python object like :class:`str`
    """

    def __init__(self, configuration: dict, connect: bool=False):
        for key, type_ in self._mandatory_configuration.items():
            if key not in configuration:
                raise KeyError('Configuration must contain key: "%s"' % key)
            if not isinstance(configuration[key], type_):
                raise TypeError('Configuration key "%s" must be instance of "%s"' % (key, type_))

        self.configuration = configuration
        if connect:
            self.connect()

    def connect(self):
        """Connect to the server defined in the configuration"""
        pass

    def close(self):
        """Close connection to the server"""
        pass

    def upload(self, file):
        """Upload a file to the server

        Args:
            file: file like object or a path to a file
        """
        pass
