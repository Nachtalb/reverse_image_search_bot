import os
from tempfile import NamedTemporaryFile

from .base_uploader import UploaderBase


class FileSystemUploader(UploaderBase):
    """Save files on file system
    """

    _mandatory_configuration = {'path': str}

    def upload(self, file, filename: str = None, save_path: str = None):
        """Upload file to the ssh server

        Args:
            file: Path to file on file system or file like object. If a file path is given the file is copied to the new
                place not moved.
            filename (:obj:`str`): New filename, must be set if file is a file like object
            save_path (:obj:`str`): Directory where to save the file. Joins with the configurations path. Creates
                directory if it does not exist yet.
        """
        is_file_object = bool(getattr(file, 'read', False))
        if is_file_object:
            if filename is None:
                raise ValueError('filename must be set when file is a file like object')
            with NamedTemporaryFile(delete=False) as new_file:
                file.seek(0)
                new_file.write(file.read())

                real_file = new_file.name
                filename = filename
        else:
            real_file = file
            filename = filename or os.path.basename(real_file)

        save_dir = os.path.join(self.configuration['path'], save_path) if save_path else \
            self.configuration['path']
        save_path = os.path.join(save_dir, filename)
        os.makedirs(save_dir, exist_ok=True)

        os.system('cp {src} {dst} && chmod 664 {dst}'.format(src=real_file, dst=save_path))
        if is_file_object:
            os.unlink(real_file)
