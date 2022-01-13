import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

from .base_uploader import UploaderBase


class FileSystemUploader(UploaderBase):
    """Save files on file system
    """

    _mandatory_configuration = {'path': str}

    def upload(self, file: Path | IO, filename: str):
        """Upload file to the ssh server

        Args:
            file: Path to file on file system or file like object. If a file path is given the file is copied to the new
                place not moved.
            filename (:obj:`str`): New filename, must be set if file is a file like object
            save_path (:obj:`str`): Directory where to save the file. Joins with the configurations path. Creates
                directory if it does not exist yet.
        """
        file_is_obj = not isinstance(file, Path)

        destination = Path(self.configuration['path']) / filename  # type: ignore
        if destination.is_file():
            self.logger.info('File at "%s" already exists', destination)
            return

        if file_is_obj:
            with NamedTemporaryFile(delete=False) as new_file:
                file.seek(0)  # type: ignore
                new_file.write(file.read())  # type: ignore

                real_file = Path(new_file.name)
        else:
            real_file = file

        os.makedirs(destination.parent, exist_ok=True)

        os.system('mv {src} {dst} && chmod 664 {dst}'.format(src=real_file, dst=destination))
        self.logger.info('Saved file to "%s"', destination)

    def file_exists(self, file_name: str | Path) -> bool:
        return (Path(self.configuration['path']) / file_name).is_file()
