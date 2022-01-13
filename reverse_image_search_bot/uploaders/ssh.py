import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

import paramiko

from .base_uploader import UploaderBase


class SSHUploader(UploaderBase):
    """Upload files to an ssh server via paramiko http://www.paramiko.org/

    Attributes:
        configuration (:obj:`dict`): Configuration of this uploader
        ssh (:obj:`paramiko.client.SSHClient`): Connection to the ssh server
        sftp (:obj:`paramiko.sftp_client.SFTPClient`): Connection via sftp to the ssh server
    Args:
        configuration (:obj:`dict`): Configuration of this uploader. Must contain these key: host, user, password,
            key_filename, upload_dir, ssh_authentication
        connect (:obj:`bool`): If the uploader should directly connect to the server
    """

    _mandatory_configuration = {'host': str, 'user': str, 'password': str, 'upload_dir': str}

    def __init__(self, configuration: dict, connect: bool = False):
        self.ssh: paramiko.SSHClient = None  # type: ignore
        self.sftp: paramiko.SFTPClient = None  # type: ignore
        super().__init__(configuration, connect)

    def connect(self):
        username, host = self.configuration['user'], self.configuration['host']
        self.logger.debug('connecting to "%s@%s"...', username, host)

        self.ssh = paramiko.SSHClient()
        self.ssh.load_host_keys(os.path.expanduser(os.path.join("~", ".ssh", "known_hosts")))

        if self.configuration.get('key_filename', None):
            self.ssh.connect(host,
                             username=username,
                             password=self.configuration['password'],
                             key_filename=self.configuration['key_filename'])
            self.logger.debug('connection established with key file')
        else:
            self.ssh.connect(host,
                             username=username,
                             password=self.configuration['password'])
            self.logger.debug('connection established with password')
        self.sftp = self.ssh.open_sftp()

    def close(self):
        self.sftp.close()
        self.ssh.close()
        self.logger.debug('connection closed')

    def upload(self, file: IO | Path, filename: str):
        """Upload file to the ssh server

        Args:
            file (:obj:`Path` | :obj:`IO`): Path or file like that will be uploaded
            filename (:obj:`str`): Filename at the destination, optional if `file` is :obj:`Path`
        """
        self.logger.debug('Uploading')

        if not isinstance(file, Path):
            with NamedTemporaryFile(delete=False) as new_file:
                file.seek(0)
                new_file.write(file.read())

                real_file = Path(new_file.name)
        else:
            real_file = file

        upload_path = Path(self.configuration['upload_dir']) / filename

        self.sftp.put(str(real_file), str(upload_path))
        self.logger.info('Uploaded file from "%s" to "%s:%s"', real_file, self.configuration['host'], upload_path)

        if not isinstance(file, Path):
            real_file.unlink()
