from reverse_image_search_bot.settings import UPLOADER
from .base_uploader import UploaderBase
from .file_system import FileSystemUploader
from .ssh import SSHUploader

__all__ = ['uploader']

match UPLOADER['uploader']:
    case 'ssh':
        uploader_cls = SSHUploader
    case 'local' | _:
        uploader_cls = FileSystemUploader

uploader: UploaderBase = uploader_cls(UPLOADER['configuration'])
