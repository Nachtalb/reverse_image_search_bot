import os
import shutil
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

from .base_uploader import UploaderBase


class FileSystemUploader(UploaderBase):
    """Save files on file system"""

    _mandatory_configuration = {"path": str}

    def upload(self, file: Path | IO, filename: str):
        """Upload file to the ssh server

        Args:
            file: Path to file on file system or file like object. If a file path is given the file is copied to the new
                place not moved.
            filename (:obj:`str`): New filename, must be set if file is a file like object
            save_path (:obj:`str`): Directory where to save the file. Joins with the configurations path. Creates
                directory if it does not exist yet.
        """
        destination = Path(self.configuration["path"]) / filename
        if destination.is_file():
            self.logger.debug('File at "%s" already exists', destination)
            return

        if isinstance(file, Path):
            real_file = file
        else:
            with NamedTemporaryFile(delete=False) as new_file:
                file.seek(0)
                new_file.write(file.read())
                real_file = Path(new_file.name)

        os.makedirs(destination.parent, exist_ok=True)

        shutil.move(real_file, destination)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)  # 0o664
        self.logger.debug('Saved file to "%s"', destination)

    def file_exists(self, file_name: str | Path) -> bool:
        return (Path(self.configuration["path"]) / file_name).is_file()
